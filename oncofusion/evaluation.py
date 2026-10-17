"""Objective metrics. Source-span validity is not semantic citation support."""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from .datasets import GoldRecord, read_jsonl, validate_splits
from .engine import Engine, run_fingerprint
from .providers import ProviderError
from .schemas import CaseInput, RunConfig, RunResult, TraceEvent


def classification_metrics(gold: list[str], predicted: list[str], labels: list[str]) -> dict:
    if not gold or len(gold) != len(predicted):
        raise ValueError("nonempty aligned labels required")
    if not labels or len(labels) != len(set(labels)) or not set(gold) <= set(labels):
        raise ValueError("invalid label universe")
    scores = {}
    for label in labels:
        tp = sum(g == p == label for g, p in zip(gold, predicted))
        fp = sum(g != label and p == label for g, p in zip(gold, predicted))
        fn = sum(g == label and p != label for g, p in zip(gold, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
        scores[label] = {"precision": precision, "recall": recall, "f1": f1, "support": gold.count(label)}
    return {"accuracy": sum(g == p for g, p in zip(gold, predicted)) / len(gold),
            "macro_f1": statistics.mean(v["f1"] for v in scores.values()), "per_class": scores}


def retrieval_metrics(relevant: set[str], ranked: list[str], k: int) -> dict:
    if not relevant or k < 1:
        raise ValueError("retrieval metrics need nonempty relevance labels and positive k")
    unique = list(dict.fromkeys(ranked))[:k]
    hits, precisions = 0, []
    for rank, doc_id in enumerate(unique, 1):
        if doc_id in relevant:
            hits += 1
            precisions.append(hits / rank)
    return {"recall_at_k": hits / len(relevant), "average_precision_at_k": sum(precisions) / min(len(relevant), k)}


def paired_cluster_bootstrap(groups: list[str], a: list[float], b: list[float],
                             repeats: int = 2000, seed: int = 0) -> dict:
    if not groups or len(groups) != len(a) or len(a) != len(b) or repeats < 1:
        raise ValueError("aligned nonempty samples and positive repeats required")
    buckets = defaultdict(list)
    for group, left, right in zip(groups, a, b):
        buckets[group].append(left - right)
    keys, rng = sorted(buckets), random.Random(seed)
    deltas = []
    for _ in range(repeats):
        sample = [value for key in rng.choices(keys, k=len(keys)) for value in buckets[key]]
        deltas.append(statistics.mean(sample))
    deltas.sort()
    return {"mean_delta": statistics.mean(x - y for x, y in zip(a, b)),
            "ci95": [deltas[int(.025 * (repeats - 1))], deltas[int(.975 * (repeats - 1))]],
            "groups": len(keys), "repeats": repeats, "seed": seed}


def risk_coverage(correct: list[bool], confidence: list[float]) -> list[dict]:
    if not correct or len(correct) != len(confidence) or any(not 0 <= c <= 1 for c in confidence):
        raise ValueError("aligned nonempty samples and confidence in [0,1] required")
    order = sorted(range(len(correct)), key=lambda i: (-confidence[i], i))
    results, errors = [], 0
    for n, index in enumerate(order, 1):
        errors += not correct[index]
        results.append({"coverage": n / len(correct), "risk": errors / n})
    return results


def evaluate(cases: list[CaseInput], gold: list[GoldRecord], engine: Engine, config: RunConfig,
             output: Path | None = None, resume: bool = False, retry_failed: bool = False) -> dict:
    validate_splits(gold)
    labels = {g.case_id: g for g in gold}
    if not cases or len(labels) != len(gold) or len({c.id for c in cases}) != len(cases) or set(labels) != {c.id for c in cases}:
        raise ValueError("unique and exactly aligned case/gold sets required")
    if len({c.task for c in cases}) != 1 or cases[0].task == "synthesis":
        raise ValueError("evaluate one labeled task at a time; synthesis requires a separate rubric")
    if cases[0].task == "verification" and len({c.verification_scheme for c in cases}) != 1:
        raise ValueError("evaluate one verification vocabulary at a time")
    universe = list(cases[0].verification_labels) if cases[0].task == "verification" else sorted({key for case in cases for key in case.options})
    if not all(g.label in universe for g in gold):
        raise ValueError("gold labels must belong to the declared task vocabulary")
    if output:
        output.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cases:
        events = []
        # Only this label-free CaseInput crosses the inference boundary.
        try:
            result_path = output / (case.id + ".json") if output else None
            failure_path = output / (case.id + ".failed.json") if output else None
            result = None
            if resume and result_path and result_path.exists():
                cached = RunResult.model_validate_json(result_path.read_text())
                if cached.fingerprint != run_fingerprint(case, config, engine.provider):
                    raise ValueError("cached result identity mismatch; use a new output directory")
                if cached.status == "completed" or not retry_failed:
                    result = cached
            if resume and result is None and failure_path and failure_path.exists() and not retry_failed:
                failure = json.loads(failure_path.read_text())
                if failure.get("fingerprint") != run_fingerprint(case, config, engine.provider):
                    raise ValueError("failed-result identity mismatch; use a new output directory")
                events.extend(TraceEvent.model_validate(e) for e in failure["trace"])
                raise ProviderError(failure["error"])
            if result is None:
                result = engine.run(case, config, events.append)
            prediction = result.decision.answer if result.decision else "__INCOMPLETE__"
            row = {"case_id": case.id, "group_id": labels[case.id].group_id,
                   "gold": labels[case.id].label, "prediction": prediction,
                   "status": result.status, "usage": result.usage.model_dump(),
                   "duration_seconds": result.duration_seconds, "fingerprint": result.fingerprint}
            if output:
                (output / (case.id + ".json")).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        except ProviderError as exc:
            row = {"case_id": case.id, "group_id": labels[case.id].group_id,
                   "gold": labels[case.id].label, "prediction": "__FAILED__", "status": "failed", "error": str(exc), "usage_incomplete": True,
                   "observed_usage": {"input_tokens": sum(e.details["input_tokens"] for e in events if e.kind == "model_usage"),
                                      "output_tokens": sum(e.details["output_tokens"] for e in events if e.kind == "model_usage")}}
            if output:
                (output / (case.id + ".failed.json")).write_text(json.dumps({
                    "error": str(exc), "fingerprint": run_fingerprint(case, config, engine.provider), "trace": [e.model_dump() for e in events]}, ensure_ascii=False), encoding="utf-8")
        rows.append(row)
    metrics = classification_metrics([r["gold"] for r in rows], [r["prediction"] for r in rows], universe)
    group_scores = defaultdict(list)
    for row in rows:
        group_scores[row["group_id"]].append(row["prediction"] == row["gold"])
    metrics["group_macro_accuracy"] = statistics.mean(statistics.mean(values) for values in group_scores.values())
    observed = [r["usage"] for r in rows if "usage" in r]
    times = sorted(r["duration_seconds"] for r in rows if "duration_seconds" in r)
    efficiency = {"observed_completed_runs": len(observed), "usage_incomplete_runs": len(rows) - len(observed),
                  "total_calls": sum(u["calls"] for u in observed),
                  "total_input_tokens": sum(u["input_tokens"] for u in observed),
                  "total_output_tokens": sum(u["output_tokens"] for u in observed),
                  "mean_seconds": statistics.mean(times) if times else None,
                  "p95_seconds": times[min(len(times) - 1, int(.95 * len(times)))] if times else None,
                  "known_cost_usd": sum(u["cost_usd"] for u in observed if u["cost_usd"] is not None),
                  "cost_complete": len(observed) == len(rows) and all(u["cost_usd"] is not None for u in observed)}
    report = {"provider": engine.provider.name, "model": engine.provider.model,
              "simulated": engine.provider.simulated,
              "interpretation": "software-only; no biomedical efficacy claim" if engine.provider.simulated else "requires benchmark protocol audit",
              "task": cases[0].task, "verification_scheme": cases[0].verification_scheme if cases[0].task == "verification" else None, "count": len(rows), "config": config.model_dump(), "metrics": metrics, "efficiency": efficiency,
              "failed_or_incomplete": sum(r["status"] != "completed" for r in rows), "rows": rows}
    if output:
        (output / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def load_evaluation(inputs: Path, labels: Path) -> tuple[list[CaseInput], list[GoldRecord]]:
    return ([CaseInput.model_validate(row) for row in read_jsonl(inputs)],
            [GoldRecord.model_validate(row) for row in read_jsonl(labels)])
