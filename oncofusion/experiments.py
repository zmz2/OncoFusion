"""Predeclared treatments, data perturbations, resumable studies and paired analysis."""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from .config import presets, legacy_presets
from .datasets import GoldRecord, validate_splits
from .engine import Engine, implementation_digest
from .evaluation import evaluate, paired_cluster_bootstrap
from .providers import provider_identity
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
    validate_splits(gold)
    labels = {g.case_id: g for g in gold}
    if len(labels) != len(gold) or set(labels) != {c.id for c in cases}:
        raise ValueError("case/gold mismatch")
    chosen = [c for c in cases if c.task == plan.task and labels[c.id].split == plan.split]
    groups = sorted({labels[c.id].group_id for c in chosen},
                    key=lambda x: hashlib.sha256(x.encode()).digest())
    if plan.group_limit:
        groups = groups[:plan.group_limit]
    selected = [c for c in chosen if labels[c.id].group_id in set(groups)]
    if not selected:
        raise ValueError("study selection is empty")
    return selected, [labels[c.id] for c in selected]


def plan_identity(plan: StudyPlan, cases: list[CaseInput], gold: list[GoldRecord], engine: Engine) -> str:
    payload = {"implementation": implementation_digest(), "plan": plan.model_dump(), "provider": provider_identity(engine.provider),
               "inputs": [c.model_dump() for c in cases], "gold": [g.model_dump() for g in gold]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def run_study(plan: StudyPlan, cases: list[CaseInput], gold: list[GoldRecord], engine: Engine,
              output: Path, resume: bool = False, retry_failed: bool = False) -> dict:
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
    summaries = []
    for treatment in plan.treatments:
        for seed in plan.seeds:
            directory = output / treatment.name / str(seed)
            summary_file = directory / "summary.json"
            if resume and summary_file.exists():
                report = json.loads(summary_file.read_text())
                if not report["failed_or_incomplete"] or not retry_failed:
                    summaries.append({"treatment": treatment.name, "seed": seed, "report": report})
                    continue
            transformed = [perturb(c, treatment.perturbation, seed) for c in cases]
            report = evaluate(transformed, gold, engine, treatment.config(seed), directory, resume=resume,
                              retry_failed=retry_failed)
            summaries.append({"treatment": treatment.name, "seed": seed, "report": report})
    result = analyze(plan, summaries)
    result.update({"identity": identity, "simulated": engine.provider.simulated,
                   "case_count": len(cases), "group_count": len({g.group_id for g in gold})})
    atomic_json(output / "study.json", result)
    return result


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
    return {"plan": plan.model_dump(), "table": table,
            "inference": "CI clusters by patient/article; repeated seeds averaged within case before bootstrap. Exploratory comparisons are not multiplicity-adjusted."}


def standard_plan(task: str, split: str = "dev", group_limit: int | None = None, smoke: bool = False) -> StudyPlan:
    names = ["full", "single_direct", "single_tools", "single_iterative", "fixed_five"] if smoke else list(legacy_presets())
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
