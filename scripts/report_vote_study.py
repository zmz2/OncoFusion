"""Build the B0/G-K/P-K report and reuse stored ballots for V0/V1/V2/C-raw."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

from oncofusion.datasets import GoldRecord, read_jsonl
from oncofusion.evaluation import classification_metrics
from oncofusion.schemas import CaseInput, RunResult, Usage, VoteCalibration
from oncofusion.voting import aggregate_ballots


def read_arm(run: Path, arm: str, gold: dict[str, str]):
    rows = []
    folder = run / arm / "0"
    completed = set()
    for path in sorted(folder.glob("*.json")):
        if path.name == "summary.json" or path.name.endswith(".failed.json"):
            continue
        result = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        if result.case_id not in gold:
            continue
        rows.append((result, gold[result.case_id]))
        completed.add(result.case_id)
    for path in sorted(folder.glob("*.failed.json")):
        case_id = path.name.removesuffix(".failed.json")
        if case_id in completed or case_id not in gold:
            continue
        failure = json.loads(path.read_text(encoding="utf-8"))
        observed = failure.get("observed_usage") or {}
        if not observed:
            trace = failure.get("trace", [])
            observed = {
                "calls": sum(
                    event.get("kind") == "agent_started"
                    for event in trace),
                "input_tokens": sum(
                    event.get("details", {}).get("input_tokens", 0)
                    for event in trace
                    if event.get("kind") == "model_usage"),
                "output_tokens": sum(
                    event.get("details", {}).get("output_tokens", 0)
                    for event in trace
                    if event.get("kind") == "model_usage"),
            }
        result = SimpleNamespace(
            case_id=case_id,
            status="failed",
            decision=None,
            vote_result=None,
            ballots=[],
            usage=Usage.model_validate(observed),
            duration_seconds=None,
        )
        rows.append((result, gold[case_id]))
    rows.sort(key=lambda item: item[0].case_id)
    return rows


def summarize(rows, labels):
    predictions = [
        result.decision.answer
        if result.status == "completed" and result.decision is not None
        else "__FAILED__"
        for result, _ in rows
    ]
    metrics = classification_metrics(
        [gold for _, gold in rows], predictions, labels)
    calls = sum(result.usage.calls for result, _ in rows)
    input_tokens = sum(result.usage.input_tokens for result, _ in rows)
    output_tokens = sum(result.usage.output_tokens for result, _ in rows)
    times = sorted(
        result.duration_seconds for result, _ in rows
        if result.duration_seconds is not None)
    failure_reasons = Counter(
        result.vote_result.failure_reason
        for result, _ in rows
        if result.vote_result is not None
        and result.vote_result.completion_status == "failed"
        and result.vote_result.failure_reason
    )
    return {
        "cases": len(rows),
        "completed": sum(result.status == "completed" for result, _ in rows),
        "full_completion": sum(
            result.vote_result is not None
            and result.vote_result.completion_status == "full"
            for result, _ in rows),
        "degraded_completion": sum(
            result.vote_result is not None
            and result.vote_result.completion_status == "degraded"
            for result, _ in rows),
        "vote_failed": sum(
            result.vote_result is not None
            and result.vote_result.completion_status == "failed"
            for result, _ in rows),
        "failed_or_incomplete": sum(result.status != "completed" for result, _ in rows),
        "failure_reasons": dict(failure_reasons),
        "metrics": metrics,
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "p50_seconds": statistics.median(times) if times else None,
        "p95_seconds": (
            times[max(1, math.ceil(.95 * len(times))) - 1]
            if times else None),
    }


def disagreement_metrics(rows, labels):
    members = defaultdict(lambda: {"valid": 0, "correct": 0})
    distinct_label_counts = Counter()
    oracle_union = 0
    for result, gold in rows:
        ballots = [
            ballot for ballot in result.ballots
            if ballot.status == "vote" and ballot.label in labels
        ]
        distinct_label_counts[len({ballot.label for ballot in ballots})] += 1
        oracle_union += any(ballot.label == gold for ballot in ballots)
        for ballot in ballots:
            member = members[ballot.role]
            member["valid"] += 1
            member["correct"] += ballot.label == gold
    return {
        "distinct_label_counts": dict(sorted(distinct_label_counts.items())),
        "oracle_union_cases": oracle_union,
        "members": {
            role: {
                **item,
                "accuracy": item["correct"] / item["valid"]
                if item["valid"] else None,
            }
            for role, item in sorted(members.items())
        },
    }


def provider_audit(run: Path, rows) -> dict:
    usage_calls = sum(
        result.usage.calls for arm_rows in rows.values() for result, _ in arm_rows)
    provider_logs = sorted(run.glob("provider_calls*.jsonl"))
    provider_counts = {
        path.name: sum(1 for _ in path.open(encoding="utf-8"))
        for path in provider_logs
    }
    provider_lines = (
        sum(provider_counts.values()) if provider_counts else None)
    concurrency_path = run / "concurrency.json"
    concurrency = (
        json.loads(concurrency_path.read_text(encoding="utf-8"))
        if concurrency_path.exists() else None
    )
    return {
        "usage_calls": usage_calls,
        "provider_log_lines": provider_lines,
        "provider_log_files": provider_counts,
        "provider_log_minus_usage": (
            provider_lines - usage_calls if provider_lines is not None else None),
        "concurrency": concurrency,
    }


def aggregate_saved(
        rows,
        labels,
        rule,
        weights=None,
        calibration=None,
        use_saved_arbitration=False,
):
    predictions = []
    metadata = []
    per_case = []
    for result, gold in rows:
        if result.vote_result is None:
            predictions.append("__FAILED__")
            continue
        vote = aggregate_ballots(
            case_id=result.case_id,
            ballots=result.ballots,
            labels=labels,
            planned_roles=result.vote_result.planned_roles,
            pool=result.vote_result.pool,
            rule=rule,
            role_weights=weights,
            calibration=calibration,
            arbitration=(
                result.vote_result.arbitration
                if use_saved_arbitration
                and result.vote_result.rule == "v3"
                else None),
        )
        predictions.append(
            vote.label if vote.completion_status != "failed" and vote.label
            else "__FAILED__")
        metadata.append(vote)
        per_case.append({
            "case_id": result.case_id,
            "gold": gold,
            "rule": rule,
            "label": vote.label,
            "valid_votes": vote.valid_votes,
            "planned_votes": vote.planned_votes,
            "counts": vote.counts,
            "scores": vote.scores,
            "tied": vote.tied,
            "completion_status": vote.completion_status,
        })
    metrics = classification_metrics(
        [gold for _, gold in rows], predictions, labels)
    return {
        "metrics": metrics,
        "full_completion": sum(v.completion_status == "full" for v in metadata),
        "degraded_completion": sum(v.completion_status == "degraded" for v in metadata),
        "failed": len(rows) - sum(
            v.completion_status in {"full", "degraded"} for v in metadata),
        "ties": sum(v.tied for v in metadata),
        "predictions": predictions,
        "per_case": per_case,
    }


def paired_breakdown(rows, predictions, reference_rows):
    refs = {
        result.case_id: result
        for result, _ in reference_rows
        if result.status == "completed" and result.decision
    }
    semantic_fixed = semantic_broke = recovered = failure_regressed = both_failed = 0
    for (result, gold), prediction in zip(rows, predictions):
        reference = refs.get(result.case_id)
        if reference is None:
            continue
        candidate_completed = result.status == "completed" and result.decision is not None
        candidate_correct = candidate_completed and prediction == gold
        reference_correct = reference.decision.answer == gold
        if candidate_completed:
            semantic_fixed += not reference_correct and candidate_correct
            semantic_broke += reference_correct and not candidate_correct
        else:
            failure_regressed += reference_correct
            recovered += not reference_correct and prediction == gold
            both_failed += not reference_correct
    fixed = semantic_fixed + recovered
    broke = semantic_broke + failure_regressed
    return {
        "fixed": fixed,
        "broke": broke,
        "net": fixed - broke,
        "semantic_fixed": semantic_fixed,
        "semantic_broke": semantic_broke,
        "failure_recovered": recovered,
        "failure_regressed": failure_regressed,
        "both_failed": both_failed,
    }


def paired_predictions(rows, predictions, reference_rows):
    return paired_breakdown(rows, predictions, reference_rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-arm", default="b0_common_single")
    parser.add_argument("--generalist-arm", default="g_k")
    parser.add_argument("--professional-arm", default="p_k_specialists")
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--v3-run", type=Path)
    args = parser.parse_args()

    cases = {
        case.id: case
        for case in (
            CaseInput.model_validate(row)
            for row in read_jsonl(args.dataset / "inputs.jsonl")
        )
    }
    gold_rows = [
        GoldRecord.model_validate(row)
        for row in read_jsonl(args.dataset / "_gold" / "labels.jsonl")
    ]
    gold = {row.case_id: row.label for row in gold_rows}
    task = next(iter(cases.values())).task
    labels = (
        list(next(iter(cases.values())).verification_labels)
        if task == "verification"
        else sorted({key for case in cases.values() for key in case.options})
    )
    arms = {
        args.reference_arm: args.reference_arm,
        args.generalist_arm: next(
            (path.name for path in args.run.iterdir()
             if path.is_dir() and path.name.startswith("g_k")),
            args.generalist_arm,
        ),
        args.professional_arm: args.professional_arm,
    }
    rows = {label: read_arm(args.run, arm, gold) for label, arm in arms.items()}
    result = {
        "task": task,
        "arms": {},
        "rules": {},
        "arm_names": arms,
    }
    for label, arm_rows in rows.items():
        result["arms"][label] = summarize(arm_rows, labels)
        result["arms"][label]["disagreement"] = disagreement_metrics(
            arm_rows, labels)
        if arm_rows:
            predictions = [
                item.decision.answer
                if item.status == "completed" and item.decision is not None
                else "__FAILED__"
                for item, _ in arm_rows
            ]
            result["arms"][label]["paired_vs_reference"] = paired_breakdown(
                arm_rows, predictions, rows[args.reference_arm])
    result["provider_audit"] = provider_audit(args.run, rows)
    study_path = args.run / "study.json"
    study = (
        json.loads(study_path.read_text(encoding="utf-8"))
        if study_path.exists() else None
    )
    if study is not None:
        study_rows = {row["treatment"]: row for row in study.get("table", [])}
        for label, arm_name in arms.items():
            source = study_rows.get(arm_name)
            if source is not None:
                result["arms"][label]["study_table"] = source
    professional = rows[args.professional_arm]
    v3_summary = None
    if args.v3_run is not None:
        v3_rows = read_arm(
            args.v3_run, args.professional_arm, gold)
        v3_by_case = {result.case_id: result for result, _ in v3_rows}
        professional = [
            (v3_by_case.get(result.case_id, result), gold_label)
            for result, gold_label in professional
        ]
        arbitration_file = args.v3_run / "arbitration.json"
        if arbitration_file.exists():
            v3_summary = json.loads(
                arbitration_file.read_text(encoding="utf-8"))
    result["v3"] = v3_summary
    weights = None
    calibration = None
    if args.weights:
        payload = json.loads(args.weights.read_text())
        weights = payload.get("role_weights", payload)
    if args.calibration:
        payload = json.loads(args.calibration.read_text())
        if payload.get("usable") is False:
            raise ValueError(
                "calibration is not usable: "
                + payload.get("reason", "unknown"))
        calibration = VoteCalibration.model_validate(
            payload.get("calibration", payload))
    rules = ["v0", "c_raw"]
    if weights:
        rules.append("v1")
    if calibration:
        rules.append("v2")
    if args.v3_run is not None:
        rules.append("v3")
    for rule in rules:
        result["rules"][rule] = aggregate_saved(
            professional,
            labels,
            rule,
            weights,
            calibration,
            use_saved_arbitration=(rule == "v3"),
        )
    args.out.mkdir(parents=True, exist_ok=True)
    ballot_path = args.out / "ballots.jsonl"
    with ballot_path.open("w", encoding="utf-8") as handle:
        for result_row, gold_label in professional:
            for ballot in result_row.ballots:
                handle.write(json.dumps({
                    **ballot.model_dump(mode="json"),
                    "gold": gold_label,
                }, ensure_ascii=False) + "\n")
    aggregation_path = args.out / "aggregation.jsonl"
    with aggregation_path.open("w", encoding="utf-8") as handle:
        for rule in rules:
            for row in result["rules"][rule]["per_case"]:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "run": str(args.run),
        "dataset": str(args.dataset),
        "professional_arm": args.professional_arm,
        "cases": len(professional),
        "rules": rules,
        "ballot_file": str(ballot_path),
        "aggregation_file": str(aggregation_path),
        "v3_run": str(args.v3_run) if args.v3_run else None,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.out / "report.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    lines = [
        "# vote-v1 development report",
        "",
        f"- task: {task}",
        "",
        "| arm | completed | full | degraded | failed | Accuracy | ΔAccuracy [95% CI] | Macro-F1 | calls | input tokens | output tokens | p50 s | p95 s |",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, item in result["arms"].items():
        metrics = item["metrics"]
        delta = (item.get("study_table") or {}).get("delta_vs_reference")
        delta_text = (
            f"{delta['mean_delta']:+.4f} "
            f"[{delta['ci95'][0]:+.4f}, {delta['ci95'][1]:+.4f}]"
            if delta else "—"
        )
        lines.append(
            f"| {label} | {item['completed']}/{item['cases']} | "
            f"{item['full_completion']} | {item['degraded_completion']} | "
            f"{item['vote_failed']} | "
            f"{metrics['accuracy']:.4f} | {delta_text} | "
            f"{metrics['macro_f1']:.4f} | "
            f"{item['calls']} | {item['input_tokens']} | {item['output_tokens']} | "
            f"{item['p50_seconds']:.2f} | {item['p95_seconds']:.2f} |")
    lines += [
        "",
        "## Per-class performance",
        "",
        "| arm | class | precision | recall | F1 | support |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for label, item in result["arms"].items():
        for class_label, class_metrics in item["metrics"]["per_class"].items():
            lines.append(
                f"| {label} | {class_label} | "
                f"{class_metrics['precision']:.4f} | "
                f"{class_metrics['recall']:.4f} | "
                f"{class_metrics['f1']:.4f} | "
                f"{class_metrics['support']} |")
    lines += [
        "",
        "## Ballot aggregation",
        "",
        "| ballot rule | Accuracy | Macro-F1 | full | degraded | failed | ties | fixed vs B0 | broke vs B0 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    reference = rows[args.reference_arm]
    for rule, item in result["rules"].items():
        pair = paired_predictions(professional, item["predictions"], reference)
        item["paired_vs_reference"] = pair
        metrics = item["metrics"]
        lines.append(
            f"| {rule} | {metrics['accuracy']:.4f} | {metrics['macro_f1']:.4f} | "
            f"{item['full_completion']} | {item['degraded_completion']} | "
            f"{item['failed']} | {item['ties']} | {pair['fixed']} | {pair['broke']} |")
    lines += [
        "",
        "## Paired outcome audit versus B0",
        "",
        "| system | semantic fixed | semantic broke | failure recovered | failure regressed | both failed |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, item in result["arms"].items():
        pair = item.get("paired_vs_reference", {})
        lines.append(
            f"| {label} | {pair.get('semantic_fixed', 0)} | "
            f"{pair.get('semantic_broke', 0)} | "
            f"{pair.get('failure_recovered', 0)} | "
            f"{pair.get('failure_regressed', 0)} | "
            f"{pair.get('both_failed', 0)} |")
    for rule, item in result["rules"].items():
        pair = item["paired_vs_reference"]
        lines.append(
            f"| {rule} | {pair['semantic_fixed']} | "
            f"{pair['semantic_broke']} | {pair['failure_recovered']} | "
            f"{pair['failure_regressed']} | {pair['both_failed']} |")
    lines += [
        "",
        "## Member diagnostics",
        "",
        "| arm | member | valid | correct | accuracy | oracle-union cases |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for label, item in result["arms"].items():
        for role, member in item["disagreement"]["members"].items():
            member_accuracy = (
                f"{member['accuracy']:.4f}"
                if member["accuracy"] is not None else "n/a")
            lines.append(
                f"| {label} | {role} | {member['valid']} | "
                f"{member['correct']} | {member_accuracy} | "
                f"{item['disagreement']['oracle_union_cases']} |")
    audit = result["provider_audit"]
    lines += [
        "",
        "## Accounting",
        "",
        f"- usage calls: {audit['usage_calls']}",
        f"- provider log lines: {audit['provider_log_lines']}",
        f"- provider log minus usage: {audit['provider_log_minus_usage']}",
        f"- concurrency: {json.dumps(audit['concurrency'], sort_keys=True)}",
        f"- V3: {json.dumps(v3_summary, sort_keys=True)}",
        "",
        "V0/V1/V2/C-raw share the same generated ballots. "
        "A missing calibration file omits V1/V2.",
    ]
    (args.out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(args.out / "report.json"), "markdown": str(args.out / "REPORT.md")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
