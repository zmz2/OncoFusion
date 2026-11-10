"""Rebuild multi-route rankings from frozen rows and raw traces."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if not 0 < q <= 1:
        raise ValueError("percentile must be in (0, 1]")
    if q == .5:
        return statistics.median(values)
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def macro_f1(gold: list[str], prediction: list[str], labels: list[str]) -> float:
    scores = []
    for label in labels:
        tp = sum(g == p == label for g, p in zip(gold, prediction))
        fp = sum(g != label and p == label for g, p in zip(gold, prediction))
        fn = sum(g == label and p != label for g, p in zip(gold, prediction))
        scores.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    return statistics.mean(scores)


def dataset_labels(dataset: Path) -> list[str]:
    inputs = [
        json.loads(line)
        for line in (dataset / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not inputs:
        raise ValueError("dataset contains no cases")
    if inputs[0]["task"] == "verification":
        labels = inputs[0].get("verification_labels")
        if isinstance(labels, list) and labels:
            return labels
        scheme = inputs[0].get("verification_scheme")
        if scheme == "revisions":
            return ["SUPPORTS", "REVISIONS", "NEI"]
        if scheme == "refutes":
            return ["SUPPORTS", "REFUTES", "NEI"]
        raise ValueError("verification dataset has no declared label vocabulary")
    labels = sorted({label for case in inputs for label in case.get("options", {})})
    if not labels:
        raise ValueError("mcq dataset has no answer options")
    return labels


def _trace_counts(events: list[dict]) -> tuple[int, int, int, int, dict[str, int]]:
    starts = [
        event for event in events
        if event.get("kind") in {"agent_started", "route_node_started"}
    ]
    roles = Counter(event.get("role") or "" for event in starts)
    return (
        len(starts),
        sum(event.get("kind") == "model_usage" for event in events),
        sum(event.get("kind") == "route_repair_requested" for event in events),
        sum(event.get("kind") == "route_invalid_output" for event in events),
        dict(sorted(roles.items())),
    )


def _protocol_record(raw: dict) -> dict:
    reports = raw.get("reports", [])
    claims = []
    duplicate_claim_ids = 0
    wrong_owner = 0
    invalid_scope = 0
    allowed_scopes = {
        "timeline": {"temporal"},
        "genomics": {"molecular"},
        "pathology": {"pathologic"},
        "drug": {"exposure", "relationship"},
        "literature": {"source"},
        "verifier": {"verification", "source"},
    }
    seen_claim_ids = set()
    for report in reports:
        role = report.get("role")
        for finding in report.get("output", {}).get("findings", []):
            claim_id = finding.get("claim_id")
            claims.append(finding)
            duplicate_claim_ids += bool(claim_id and claim_id in seen_claim_ids)
            seen_claim_ids.add(claim_id)
            wrong_owner += finding.get("author_role") != role
            invalid_scope += finding.get("scope") not in allowed_scopes.get(role, set())

    verdicts = []
    assigned = []
    verifier_evidence_ids = None
    for event in raw.get("trace", []):
        details = event.get("details", {})
        if (event.get("kind") in {"agent_started", "route_node_started"}
                and event.get("role") == "verifier"):
            if "claim_roster" in details:
                assigned = list(details["claim_roster"])
            if details.get("evidence_ids") is not None:
                verifier_evidence_ids = set(details["evidence_ids"])
        if event.get("kind") == "route_verification":
            entries = details.get("verifier") or []
            if entries:
                verdicts = entries
        elif event.get("kind") == "verification_ledger":
            entries = [
                entry for entry in details.get("entries", [])
                if entry.get("reviewer") == "verifier" or entry.get("final") is True
            ]
            if entries:
                verdicts = entries
    if not assigned:
        assigned = sorted({
            finding.get("claim_id") for finding in claims if finding.get("claim_id")})
    targets = [entry.get("target_claim_id") for entry in verdicts]
    target_set = set(targets)
    assigned_set = set(assigned)
    verdict_by_claim = {
        entry["target_claim_id"]: entry.get("verdict")
        for entry in verdicts
        if entry.get("target_claim_id")
    }
    decision = raw.get("decision") or {}
    adopted = decision.get("adopted_claim_ids") or []
    rejected = decision.get("rejected_claim_ids") or []
    invalid_verifier_citations = None
    if verifier_evidence_ids is not None:
        invalid_verifier_citations = sum(
            citation.get("evidence_id") not in verifier_evidence_ids
            for entry in verdicts
            for citation in entry.get("citations", [])
        )
    return {
        "claims": len(claims),
        "duplicate_claim_ids": duplicate_claim_ids,
        "wrong_claim_owner": wrong_owner,
        "invalid_claim_scope": invalid_scope,
        "verifier_present": bool(verdicts),
        "assigned_claims": len(assigned_set),
        "verdicts": len(verdicts),
        "duplicate_verdict_targets": len(targets) - len(target_set),
        "missing_verdicts": len(assigned_set - target_set),
        "unregistered_verdict_targets": len(target_set - assigned_set),
        "verdict_counts": dict(sorted(Counter(
            entry.get("verdict") for entry in verdicts).items())),
        "invalid_verifier_citations": invalid_verifier_citations,
        "decisions": bool(decision.get("answer")),
        "adopted_rejected": sum(verdict_by_claim.get(cid) == "rejected" for cid in adopted),
        "adopted_insufficient": sum(verdict_by_claim.get(cid) == "insufficient" for cid in adopted),
        "adopted_corrected": sum(verdict_by_claim.get(cid) == "corrected" for cid in adopted),
        "rejected_confirmed": sum(verdict_by_claim.get(cid) == "confirmed" for cid in rejected),
    }


def read_rows(directory: Path, plan: dict) -> tuple[list[dict], dict]:
    if len(plan["seeds"]) != 1:
        raise ValueError("multi-route development report expects exactly one frozen seed")
    rows = []
    diagnostics = {}
    expected_cases = set(plan["case_ids"])
    for treatment in plan["treatments"]:
        name = treatment["name"]
        arm_dir = directory / name / str(plan["seeds"][0])
        summary = arm_dir / "summary.json"
        if not summary.exists():
            raise ValueError(f"missing arm summary: {summary}")
        report = json.loads(summary.read_text())
        if "rows" not in report:
            raise ValueError(f"arm summary has no raw rows: {summary}")
        seen = {row["case_id"] for row in report["rows"]}
        if seen != expected_cases or len(report["rows"]) != len(expected_cases):
            missing = sorted(expected_cases - seen)
            extra = sorted(seen - expected_cases)
            raise ValueError(
                f"{name} does not cover the frozen plan exactly; missing={missing}, extra={extra}")
        arm_calls = model_usage_events = repairs = invalid_outputs = 0
        call_roles = Counter()
        for row in report["rows"]:
            row = dict(row)
            result_path = arm_dir / (row["case_id"] + ".json")
            failure_path = arm_dir / (row["case_id"] + ".failed.json")
            raw_path = result_path if result_path.exists() else failure_path
            if not raw_path.exists():
                raise ValueError(f"missing raw result or failure trace: {row['case_id']} ({name})")
            raw = json.loads(raw_path.read_text())
            calls, usage_events, row_repairs, row_invalid, roles = _trace_counts(
                raw.get("trace", []))
            row["trace_calls"] = calls
            row["model_usage_events"] = usage_events
            row["repair_requests"] = row_repairs
            row["invalid_outputs"] = row_invalid
            row["calls_by_role"] = roles
            row["protocol"] = _protocol_record(raw)
            row["treatment"] = name
            rows.append(row)
            arm_calls += calls
            model_usage_events += usage_events
            repairs += row_repairs
            invalid_outputs += row_invalid
            call_roles.update(roles)
        diagnostics[name] = {
            "cases": len(report["rows"]),
            "trace_calls": arm_calls,
            "model_usage_events": model_usage_events,
            "calls_without_usage_event": arm_calls - model_usage_events,
            "repair_requests": repairs,
            "invalid_outputs": invalid_outputs,
            "calls_by_role": dict(sorted(call_roles.items())),
        }
    return rows, diagnostics


def provider_log_count(path: Path | None) -> int | None:
    if path is None:
        return None
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


def _aggregate_protocol(rows: list[dict]) -> dict:
    protocol_keys = (
        "claims",
        "duplicate_claim_ids",
        "wrong_claim_owner",
        "invalid_claim_scope",
        "assigned_claims",
        "verdicts",
        "duplicate_verdict_targets",
        "missing_verdicts",
        "unregistered_verdict_targets",
        "invalid_verifier_citations",
        "adopted_rejected",
        "adopted_insufficient",
        "adopted_corrected",
        "rejected_confirmed",
    )
    protocol = {
        key: sum(
            row["protocol"][key] for row in rows
            if row["protocol"][key] is not None)
        for key in protocol_keys
    }
    protocol["verifier_cases"] = sum(
        row["protocol"]["verifier_present"] for row in rows)
    protocol["decision_cases"] = sum(
        row["protocol"]["decisions"] for row in rows)
    verdict_counts = Counter()
    for row in rows:
        verdict_counts.update(row["protocol"]["verdict_counts"])
    protocol["verdict_counts"] = dict(sorted(verdict_counts.items()))
    return protocol


def arm_metrics(rows: list[dict], labels: list[str]) -> dict:
    gold = [row["gold"] for row in rows]
    prediction = [
        row["prediction"] if row["status"] == "completed" else "__FAILED__"
        for row in rows
    ]
    usage = [row.get("usage", row.get("observed_usage", {})) for row in rows]
    times = [
        row["duration_seconds"]
        for row in rows
        if row.get("duration_seconds") is not None
    ]
    calls_by_role = Counter()
    for row in rows:
        calls_by_role.update(row["calls_by_role"])
    output = {
        "cases": len(rows),
        "completed": sum(row["status"] == "completed" for row in rows),
        "completion_rate": sum(row["status"] == "completed" for row in rows) / len(rows),
        "accuracy": sum(g == p for g, p in zip(gold, prediction)) / len(rows),
        "macro_f1": macro_f1(gold, prediction, labels),
        "calls": sum(int(row["trace_calls"]) for row in rows),
        "model_usage_events": sum(int(row["model_usage_events"]) for row in rows),
        "calls_without_usage_event": sum(
            int(row["trace_calls"]) - int(row["model_usage_events"])
            for row in rows),
        "input_tokens": sum(int(item.get("input_tokens", 0)) for item in usage),
        "output_tokens": sum(int(item.get("output_tokens", 0)) for item in usage),
        "usage_incomplete_runs": sum(bool(row.get("usage_incomplete")) for row in rows),
        "mean_seconds": statistics.mean(times) if times else None,
        "p50_seconds": percentile(times, .50),
        "p95_seconds": percentile(times, .95),
        "timed_cases": len(times),
        "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
        "repair_requests": sum(row["repair_requests"] for row in rows),
        "invalid_outputs": sum(row["invalid_outputs"] for row in rows),
        "calls_by_role": dict(sorted(calls_by_role.items())),
        "protocol_audit": _aggregate_protocol(rows),
        "completed_protocol_audit": _aggregate_protocol(
            [row for row in rows if row["status"] == "completed"]),
        "per_class": {},
    }
    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(gold, prediction))
        fp = sum(g != label and p == label for g, p in zip(gold, prediction))
        fn = sum(g == label and p != label for g, p in zip(gold, prediction))
        output["per_class"][label] = {
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
            "support": sum(g == label for g in gold),
        }
    return output


def paired_rows(by_arm: dict[str, dict[str, dict]], reference: str) -> dict[str, dict]:
    result = {}
    ref = by_arm[reference]
    for arm, rows in by_arm.items():
        if arm == reference:
            continue
        common = sorted(set(ref) & set(rows))
        ref_correct = {cid: ref[cid]["prediction"] == ref[cid]["gold"] for cid in common}
        arm_correct = {cid: rows[cid]["prediction"] == rows[cid]["gold"] for cid in common}
        result[arm] = {
            "compared_cases": len(common),
            "fixed": sum(not ref_correct[cid] and arm_correct[cid] for cid in common),
            "broke": sum(ref_correct[cid] and not arm_correct[cid] for cid in common),
            "reference_only_correct": sum(
                ref_correct[cid] and not arm_correct[cid] for cid in common),
            "candidate_only_correct": sum(
                not ref_correct[cid] and arm_correct[cid] for cid in common),
            "both_correct": sum(
                ref_correct[cid] and arm_correct[cid] for cid in common),
            "both_wrong": sum(
                not ref_correct[cid] and not arm_correct[cid] for cid in common),
            "candidate_completed_reference_incomplete": sum(
                rows[cid]["status"] == "completed" and ref[cid]["status"] != "completed"
                for cid in common),
            "candidate_incomplete_reference_completed": sum(
                rows[cid]["status"] != "completed" and ref[cid]["status"] == "completed"
                for cid in common),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--provider-log", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    rows, trace_diagnostics = read_rows(args.run, plan)
    by_arm: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_arm.setdefault(row["treatment"], {})[row["case_id"]] = row
    labels = dataset_labels(args.dataset)
    metrics = {
        arm: arm_metrics(list(cases.values()), labels)
        for arm, cases in by_arm.items()
    }
    paired = paired_rows(by_arm, plan["reference"])
    provider_calls = provider_log_count(args.provider_log)
    trace_calls = sum(item["calls"] for item in metrics.values())
    if provider_calls is not None and provider_calls != trace_calls:
        raise ValueError(
            f"provider log has {provider_calls} calls but raw traces account for {trace_calls}")
    output = {
        "plan": str(args.plan),
        "plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(),
        "run": str(args.run),
        "dataset": str(args.dataset),
        "dataset_sha256": {
            name: hashlib.sha256((args.dataset / name).read_bytes()).hexdigest()
            for name in ("inputs.jsonl", "_gold/labels.jsonl", "manifest.json")
        },
        "task": plan["task"],
        "case_count": len(plan["case_ids"]),
        "labels": labels,
        "metrics": metrics,
        "paired_vs_reference": paired,
        "trace_diagnostics": trace_diagnostics,
        "provider_log": {
            "path": str(args.provider_log) if args.provider_log else None,
            "calls": provider_calls,
            "trace_calls": trace_calls,
            "matches": provider_calls is None or provider_calls == trace_calls,
        },
        "failed_rows": [
            {
                key: row.get(key)
                for key in (
                    "case_id", "group_id", "treatment", "status", "error",
                    "trace_calls", "model_usage_events", "repair_requests",
                    "invalid_outputs")
            }
            for row in rows
            if row["status"] != "completed"
        ],
        "source": "raw run_case rows, result/failure traces, and per-arm summary.json",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Multi-route development comparison",
        "",
        f"- task: {plan['task']}",
        f"- cases: {len(plan['case_ids'])}",
        f"- reference: {plan['reference']}",
        "",
        "| arm | completed | Accuracy | Macro-F1 | calls | input tokens | output tokens | p50 s | p95 s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for treatment in plan["treatments"]:
        arm = treatment["name"]
        item = metrics[arm]
        lines.append(
            "| {arm} | {completed}/{cases} ({completion:.1%}) | "
            "{acc:.4f} | {f1:.4f} | {calls} | {inp} | {out} | {p50} | {p95} |".format(
                arm=arm,
                completed=item["completed"],
                cases=item["cases"],
                completion=item["completion_rate"],
                acc=item["accuracy"],
                f1=item["macro_f1"],
                calls=item["calls"],
                inp=item["input_tokens"],
                out=item["output_tokens"],
                p50=round(item["p50_seconds"], 2)
                if item["p50_seconds"] is not None else "n/a",
                p95=round(item["p95_seconds"], 2)
                if item["p95_seconds"] is not None else "n/a",
            ))
    lines += [
        "",
        "## Class metrics",
        "",
        "| arm | class | precision | recall | F1 | support |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for treatment in plan["treatments"]:
        arm = treatment["name"]
        for label in labels:
            item = metrics[arm]["per_class"][label]
            lines.append(
                f"| {arm} | {label} | {item['precision']:.4f} | "
                f"{item['recall']:.4f} | {item['f1']:.4f} | {item['support']} |")
    lines += [
        "",
        "## Paired outcomes versus reference",
        "",
        "| arm | fixed | broke | reference-only correct | candidate-only correct | both correct | both wrong |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, item in paired.items():
        lines.append(
            f"| {arm} | {item['fixed']} | {item['broke']} | "
            f"{item['reference_only_correct']} | {item['candidate_only_correct']} | "
            f"{item['both_correct']} | {item['both_wrong']} |")
    lines += [
        "",
        "All failures remain in the denominator. Calls count every started model node and "
        "must match the provider log.",
        "p50 is the standard median; p95 uses nearest rank. Timings cover only rows that "
        "stored a duration and are comparable only within this same run window.",
        f"Timed cases: {sum(item['timed_cases'] for item in metrics.values())}/"
        f"{sum(item['cases'] for item in metrics.values())} across arms.",
    ]
    (args.out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "summary": str(args.out / "summary.json"),
        "report": str(args.out / "REPORT.md"),
        "trace_calls": trace_calls,
        "provider_calls": provider_calls,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
