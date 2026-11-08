"""Predeclared treatments, data perturbations, resumable studies and paired analysis."""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from .config import presets
from .datasets import GoldRecord, validate_alignment
from .engine import Engine, implementation_digest
from .evaluation import classification_metrics, evaluate, paired_cluster_bootstrap, run_case, summarize
from .providers import provider_identity
from .profiles import coverage_report
from .workflow import dependency_identity
from .schemas import CaseInput, Document, Identifier, RunConfig, StrictModel

PERTURBATIONS = ("none", "shuffle", "duplicate", "irrelevant", "future_canary",
                 "without_genomics", "without_pathology", "without_therapy", "without_literature", "without_clinical")


class Treatment(StrictModel):
    name: Identifier
    preset: str = "full"
    overrides: dict = Field(default_factory=dict)
    perturbation: str = "none"

    @model_validator(mode="after")
    def valid(self):
        if self.preset not in presets() or self.perturbation not in PERTURBATIONS:
            raise ValueError("unknown preset or perturbation")
        self.config(0)
        return self

    def config(self, seed: int) -> RunConfig:
        base = presets()[self.preset].model_dump()
        for key, value in self.overrides.items():
            if key == "ablations":
                base[key].update(value)
            else:
                base[key] = value
        base["seed"] = seed
        return RunConfig.model_validate(base)


class StudyPlan(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: Identifier
    task: Literal["verification", "mcq"]
    split: Literal["dev", "test", "train"] = "dev"
    seeds: list[int] = Field(default_factory=lambda: [0, 1, 2], min_length=1, max_length=20)
    group_limit: int | None = Field(default=None, ge=1)
    # Pin the exact cases a run must cover (classroom demos, defect reproductions). Empty keeps
    # the task/split/group sampling behaviour every existing plan relies on.
    case_ids: list[str] = Field(default_factory=list, max_length=500)
    treatments: list[Treatment] = Field(min_length=1, max_length=200)
    reference: str = "full"
    bootstrap_repeats: int = Field(default=2000, ge=100, le=10000)

    @model_validator(mode="after")
    def valid(self):
        names = [t.name for t in self.treatments]
        if len(set(names)) != len(names) or self.reference not in names:
            raise ValueError("unique treatment names and an existing reference required")
        if len(self.seeds) != len(set(self.seeds)) or any(s < 0 for s in self.seeds):
            raise ValueError("seeds must be unique nonnegative integers")
        return self


def stratified_case_ids(cases: list[CaseInput], gold: list[GoldRecord], *, task: str,
                        split: str, per_label: int, max_per_group: int,
                        sampling_seed: int = 0) -> list[str]:
    """Choose a balanced, article-capped test subset before any model call.

    Candidates are ordered by a digest of the fixed sampling seed and case ID. Labels are then
    admitted round-robin, which prevents a large article or the dataset's source order from
    deciding the subset.
    """
    if per_label < 1 or max_per_group < 1:
        raise ValueError("per_label and max_per_group must be positive")
    labels_by_id = {record.case_id: record for record in gold}
    eligible = [case for case in cases
                if case.task == task and case.id in labels_by_id
                and labels_by_id[case.id].split == split]
    labels = sorted({labels_by_id[case.id].label for case in eligible})
    if not labels:
        raise ValueError("no eligible cases for the requested task and split")

    queues = {}
    for label in labels:
        rows = [case for case in eligible if labels_by_id[case.id].label == label]
        queues[label] = sorted(
            rows,
            key=lambda case: hashlib.sha256(
                f"{sampling_seed}:{label}:{case.id}".encode()
            ).digest(),
        )
    target = per_label * len(labels)
    selected: list[str] = []
    label_counts = Counter()
    group_counts = Counter()
    cursors = Counter()
    while len(selected) < target:
        progressed = False
        for label in labels:
            if label_counts[label] >= per_label:
                continue
            queue = queues[label]
            while cursors[label] < len(queue):
                case = queue[cursors[label]]
                cursors[label] += 1
                group = labels_by_id[case.id].group_id
                if group_counts[group] >= max_per_group:
                    continue
                selected.append(case.id)
                label_counts[label] += 1
                group_counts[group] += 1
                progressed = True
                break
        if not progressed:
            raise ValueError(
                f"only {len(selected)} of {target} cases remain after group cap {max_per_group}"
            )
    return sorted(selected)


def perturb(case: CaseInput, name: str, seed: int) -> CaseInput:
    if name not in PERTURBATIONS:
        raise ValueError("unknown perturbation")
    result = case.model_copy(deep=True)
    rng = random.Random(hashlib.sha256(f"{seed}:{case.id}".encode()).digest())
    if name == "shuffle":
        rng.shuffle(result.documents)
    elif name == "duplicate":
        # Same provenance, same text; distinct IDs. Tests repeated-source sensitivity.
        copies = [d.model_copy(update={"id": "dup-" + hashlib.sha256(d.id.encode()).hexdigest()[:24]})
                  for d in result.documents[:20]]
        result.documents.extend(copies)
    elif name == "irrelevant":
        result.documents.append(Document(id="perturb-distractor", origin_id="synthetic-distractor", kind="literature",
                                          text="Synthetic distractor: mineral crystals form cubic lattice structures."))
    elif name == "future_canary":
        result.documents.append(Document(id="perturb-future", origin_id="synthetic-future-canary", kind="clinical",
                                          text="FUTURE_CANARY_PRIVATE_SENTINEL", available_stage=result.stage + 100))
    elif name.startswith("without_"):
        kind = name.removeprefix("without_")
        result.documents = [d for d in result.documents if d.kind != kind]
    return CaseInput.model_validate(result.model_dump())


def select_cases(cases: list[CaseInput], gold: list[GoldRecord], plan: StudyPlan):
    validate_alignment(cases, gold)
    labels = {g.case_id: g for g in gold}
    if len(labels) != len(gold) or set(labels) != {c.id for c in cases}:
        raise ValueError("case/gold mismatch")
    chosen = [c for c in cases if c.task == plan.task and labels[c.id].split == plan.split]
    if plan.case_ids:
        wanted = list(dict.fromkeys(plan.case_ids))
        missing = [c for c in wanted if c not in {x.id for x in chosen}]
        if missing:
            raise ValueError("plan case_ids are not in this task/split: " + ", ".join(missing))
        wanted_set = set(wanted)
        chosen = [c for c in chosen if c.id in wanted_set]
        order = {c: i for i, c in enumerate(wanted)}
        chosen.sort(key=lambda c: order[c.id])
    groups = sorted({labels[c.id].group_id for c in chosen},
                    key=lambda x: hashlib.sha256(x.encode()).digest())
    if plan.group_limit:
        groups = groups[:plan.group_limit]
    selected = [c for c in chosen if labels[c.id].group_id in set(groups)]
    if not selected:
        raise ValueError("study selection is empty")
    return selected, [labels[c.id] for c in selected]


def plan_identity(plan: StudyPlan, cases: list[CaseInput], gold: list[GoldRecord], engine: Engine) -> str:
    payload = {"dependencies": {t.name: dependency_identity(t.config(0)) for t in plan.treatments},
               "implementation": implementation_digest(), "plan": plan.model_dump(), "provider": provider_identity(engine.provider),
               "inputs": [c.model_dump() for c in cases], "gold": [g.model_dump() for g in gold]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def run_study(plan: StudyPlan, cases: list[CaseInput], gold: list[GoldRecord], engine: Engine,
              output: Path, resume: bool = False, retry_failed: bool = False,
              workers: int = 1, interleave_treatments: bool = False) -> dict:
    cases, gold = select_cases(cases, gold, plan)
    identity = plan_identity(plan, cases, gold, engine)
    identity_file = output / "identity.json"
    if identity_file.exists():
        old = json.loads(identity_file.read_text())
        if old["identity"] != identity:
            raise ValueError("study inputs, plan or provider changed; choose a new output directory")
        if not resume:
            raise ValueError("study exists; use --resume or choose a new output directory")
    atomic_json(identity_file, {"identity": identity, "plan": plan.model_dump(),
                               "case_ids": [c.id for c in cases], "simulated": engine.provider.simulated})
    if interleave_treatments and len(plan.treatments) > 1 and len(plan.seeds) == 1:
        summaries = _interleaved_summaries(plan, cases, gold, engine, output,
                                           resume=resume, retry_failed=retry_failed,
                                           workers=workers)
    else:
        summaries = []
        for treatment in plan.treatments:
            for seed in plan.seeds:
                summaries.append(_run_treatment(
                    plan, cases, gold, engine, output, treatment, seed,
                    resume=resume, retry_failed=retry_failed, workers=workers))
    result = analyze(plan, summaries)
    result.update({"identity": identity, "simulated": engine.provider.simulated,
                   "case_count": len(cases), "group_count": len({g.group_id for g in gold}),
                   "role_coverage": coverage_report(cases),
                   "execution_order": ("case_interleaved" if interleave_treatments
                                       and len(plan.treatments) > 1 and len(plan.seeds) == 1
                                       else "treatment_sequential")})
    atomic_json(output / "study.json", result)
    return result


def _cached_summary(directory: Path, resume: bool, retry_failed: bool) -> dict | None:
    summary_file = directory / "summary.json"
    if not (resume and summary_file.exists()):
        return None
    report = json.loads(summary_file.read_text())
    return None if report["failed_or_incomplete"] and retry_failed else report


def _run_treatment(plan: StudyPlan, cases: list[CaseInput], gold: list[GoldRecord], engine: Engine,
                   output: Path, treatment: Treatment, seed: int, *, resume: bool,
                   retry_failed: bool, workers: int) -> dict:
    directory = output / treatment.name / str(seed)
    report = _cached_summary(directory, resume, retry_failed)
    if report is None:
        transformed = [perturb(c, treatment.perturbation, seed) for c in cases]
        report = evaluate(transformed, gold, engine, treatment.config(seed), directory,
                          resume=resume, retry_failed=retry_failed, workers=workers)
    return {"treatment": treatment.name, "seed": seed, "report": report}


def _interleaved_summaries(plan: StudyPlan, cases: list[CaseInput], gold: list[GoldRecord],
                           engine: Engine, output: Path, *, resume: bool,
                           retry_failed: bool, workers: int) -> list[dict]:
    """Run each case through every arm together, with at most `workers` cases in flight."""
    seed = plan.seeds[0]
    directories = {t.name: output / t.name / str(seed) for t in plan.treatments}
    initial = {t.name: _cached_summary(directories[t.name], resume, retry_failed)
               for t in plan.treatments}
    indexes = {case.id: index for index, case in enumerate(cases)}
    pending = [case for case in cases
               if any(initial[t.name] is None for t in plan.treatments)]

    def run_pair(case: CaseInput):
        reports = {}
        for treatment in plan.treatments:
            report = initial[treatment.name]
            if report is None:
                transformed = perturb(case, treatment.perturbation, seed)
                directory = directories[treatment.name]
                directory.mkdir(parents=True, exist_ok=True)
                reports[treatment.name] = run_case(
                    transformed, gold[indexes[case.id]], engine, treatment.config(seed),
                    directory, resume, retry_failed)
            else:
                reports[treatment.name] = report["rows"][indexes[case.id]]
        return indexes[case.id], reports

    paired_rows = {index: {t.name: initial[t.name]["rows"][index] for t in plan.treatments}
                   for index in range(len(cases)) if all(initial[t.name] is not None for t in plan.treatments)}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, rows in pool.map(run_pair, pending):
            paired_rows[index] = rows
    summaries = []
    for treatment in plan.treatments:
        report = initial[treatment.name]
        if report is None:
            report = {"provider": engine.provider.name, "model": engine.provider.model,
                      "simulated": engine.provider.simulated,
                      "interpretation": ("software-only; no biomedical efficacy claim"
                                         if engine.provider.simulated else "requires benchmark protocol audit"),
                      "task": cases[0].task,
                      "verification_scheme": cases[0].verification_scheme,
                      "count": len(cases), "config": treatment.config(seed).model_dump(),
                      "rows": [paired_rows[index][treatment.name] for index in range(len(cases))],
                      "efficiency": {"estimated_cost_usd": 0.0, "cost_complete": False}}
        report = summarize(report["rows"], engine, treatment.config(seed), cases)
        (directories[treatment.name] / "summary.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        summaries.append({"treatment": treatment.name, "seed": seed, "report": report})
    return summaries


def analyze(plan: StudyPlan, summaries: list[dict]) -> dict:
    by_name = {t.name: [s["report"] for s in summaries if s["treatment"] == t.name] for t in plan.treatments}
    reference = by_name[plan.reference]
    def per_case(reports):
        ids = [r["case_id"] for r in reports[0]["rows"]]
        indexed = [{r["case_id"]: r for r in report["rows"]} for report in reports]
        if any(set(m) != set(ids) for m in indexed):
            raise ValueError("paired reports must use identical case IDs")
        return {cid: statistics.mean(m[cid]["prediction"] == m[cid]["gold"] for m in indexed) for cid in ids}
    ref = per_case(reference)
    ids = sorted(ref)
    groups = {r["case_id"]: r["group_id"] for r in reference[0]["rows"]}
    table = []
    for treatment in plan.treatments:
        reports = by_name[treatment.name]
        scores = per_case(reports)
        comparison = paired_cluster_bootstrap([groups[cid] for cid in ids], [scores[cid] for cid in ids],
                                               [ref[cid] for cid in ids], plan.bootstrap_repeats)
        table.append({"treatment": treatment.name, "preset": treatment.preset, "perturbation": treatment.perturbation,
                      "accuracy_mean": statistics.mean(r["metrics"]["accuracy"] for r in reports),
                      "accuracy_std": statistics.stdev(r["metrics"]["accuracy"] for r in reports) if len(reports) > 1 else 0,
                      "macro_f1_mean": statistics.mean(r["metrics"]["macro_f1"] for r in reports),
                      "failed_or_incomplete": sum(r["failed_or_incomplete"] for r in reports),
                      "observed_calls": sum(r["efficiency"]["total_calls"] for r in reports),
                      "observed_input_tokens": sum(r["efficiency"]["total_input_tokens"] for r in reports),
                      "observed_output_tokens": sum(r["efficiency"]["total_output_tokens"] for r in reports),
                      "known_cost_usd": sum(r["efficiency"]["known_cost_usd"] for r in reports),
                      "cost_complete": all(r["efficiency"]["cost_complete"] for r in reports),
                      "usage_incomplete_runs": sum(r["efficiency"]["usage_incomplete_runs"] for r in reports),
                      "delta_vs_reference": comparison})
    groups = {r["case_id"]: r["group_id"] for r in reference[0]["rows"]}
    all_cases = [row["case_id"] for row in reference[0]["rows"]]
    by_group = defaultdict(list)
    for case_id in all_cases:
        by_group[groups[case_id]].append(case_id)
    group_profiles = defaultdict(lambda: {"cases": [], "groups": []})
    for group, ids in by_group.items():
        signature = tuple(sorted(
            (t.name, t.config(0).model_dump_json(), t.perturbation) for t in plan.treatments
        ))
        group_profiles[signature]["groups"].append(group)
        group_profiles[signature]["cases"].extend(ids)
    group_table = []
    for profile in group_profiles.values():
        selected = set(profile["cases"])
        for treatment in plan.treatments:
            rows = [row for report in by_name[treatment.name]
                    for row in report["rows"] if row["case_id"] in selected]
            if not rows:
                continue
            metrics = classification_metrics(
                [row["gold"] for row in rows], [row["prediction"] for row in rows],
                list(plan_labels(rows)))
            group_table.append({
                "group_scope": (sorted(profile["groups"])[0]
                                if len(profile["groups"]) == 1 else "group_profile"),
                "groups": sorted(profile["groups"]), "treatment": treatment.name,
                "count": len(rows), "metrics": metrics,
                "failed_or_incomplete": sum(row["status"] != "completed" for row in rows),
                "observed_calls": sum(row.get("usage", row.get("observed_usage", {})).get("calls", 0)
                                      for row in rows),
                "observed_input_tokens": sum(row.get("usage", row.get("observed_usage", {})).get("input_tokens", 0)
                                             for row in rows),
                "observed_output_tokens": sum(row.get("usage", row.get("observed_usage", {})).get("output_tokens", 0)
                                              for row in rows),
                "interpretation": "Grouped metrics retain every failure in the denominator.",
            })
    return {"plan": plan.model_dump(), "table": table, "group_table": group_table,
            "inference": "CI clusters by patient/article; repeated seeds averaged within case before bootstrap. Exploratory comparisons are not multiplicity-adjusted."}


def plan_labels(rows: list[dict]) -> list[str]:
    """Stable label universe from observed rows; used only for grouped summaries."""
    return sorted({row["gold"] for row in rows} | {row["prediction"] for row in rows})


def standard_plan(task: str, split: str = "dev", group_limit: int | None = None, smoke: bool = False) -> StudyPlan:
    names = ["full", "single_direct", "single_tools", "single_iterative", "fixed_five"] if smoke else list(presets())
    treatments = [Treatment(name=n, preset=n) for n in names]
    if not smoke:
        treatments += [Treatment(name="robust_" + n, perturbation=n) for n in PERTURBATIONS if n != "none"]
        treatments += [Treatment(name="retrieval_top" + str(k), overrides={"top_k": k}) for k in (1, 3, 10)]
        # Same cap for full and compute-matched single-agent at each budget.
        for cap in (40_000, 80_000):
            for preset in ("full", "single_iterative"):
                treatments.append(Treatment(name=f"budget_{cap}_{preset}", preset=preset,
                                             overrides={"max_total_tokens": cap}))
    return StudyPlan(name=f"{task}_{split}_{'smoke' if smoke else 'complete'}", task=task, split=split,
                     group_limit=group_limit, seeds=[0] if smoke else [0, 1, 2], treatments=treatments)
