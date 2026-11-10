"""Build the frozen MTB/CIViC development-screen delivery bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from report_multi_route import (
    arm_metrics,
    dataset_labels,
    paired_rows,
    provider_log_count,
    read_rows,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl_index(path: Path, key: str) -> dict:
    return {
        row[key]: row
        for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def trace_path(arm_directory: Path, case_id: str) -> Path:
    result = arm_directory / (case_id + ".json")
    failure = arm_directory / (case_id + ".failed.json")
    if result.exists():
        return result
    if failure.exists():
        return failure
    raise ValueError(f"missing raw trace for {case_id}: {arm_directory}")


def load_arm_rows(run: Path, plan: dict) -> dict[str, dict[str, dict]]:
    rows, _ = read_rows(run, plan)
    by_arm: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_arm.setdefault(row["treatment"], {})[row["case_id"]] = row
    return by_arm


def provider_metadata(run: Path, plan: dict) -> dict:
    arm = plan["treatments"][0]["name"]
    summary = json.loads((run / arm / str(plan["seeds"][0]) / "summary.json").read_text())
    identity = json.loads((run / "identity.json").read_text())
    concurrency_path = run / "concurrency.json"
    return {
        "provider": summary["provider"],
        "model": summary["model"],
        "simulated": summary["simulated"],
        "study_identity": identity["identity"],
        "concurrency": (
            json.loads(concurrency_path.read_text())
            if concurrency_path.exists() else None
        ),
    }


def case_evidence(run: Path, dataset: Path, case_id: str, baseline: str,
                  candidate: str, seed: int) -> dict:
    inputs = jsonl_index(dataset / "inputs.jsonl", "id")
    gold = jsonl_index(dataset / "_gold" / "labels.jsonl", "case_id")
    output = {
        "case_id": case_id,
        "group_id": gold[case_id]["group_id"],
        "gold": gold[case_id]["label"],
        "question": inputs[case_id]["question"],
        "options": inputs[case_id].get("options"),
        "baseline_arm": baseline,
        "candidate_arm": candidate,
        "arms": {},
    }
    for arm in (baseline, candidate):
        arm_dir = run / arm / str(seed)
        raw = json.loads(trace_path(arm_dir, case_id).read_text())
        decision = raw.get("decision") or {}
        reports = raw.get("reports", [])
        verdicts = []
        for event in raw.get("trace", []):
            if event.get("kind") in {"route_verification", "verification_ledger"}:
                details = event.get("details", {})
                entries = details.get("verifier") or details.get("entries") or []
                if entries:
                    verdicts = entries
        output["arms"][arm] = {
            "status": raw.get("status"),
            "answer": decision.get("answer"),
            "explanation": decision.get("explanation"),
            "unresolved": decision.get("unresolved", []),
            "adopted_claim_ids": decision.get("adopted_claim_ids", []),
            "rejected_claim_ids": decision.get("rejected_claim_ids", []),
            "calls": sum(
                event.get("kind") in {"agent_started", "route_node_started"}
                for event in raw.get("trace", [])),
            "usage": raw.get("usage", {}),
            "duration_seconds": raw.get("duration_seconds"),
            "reports": [
                {
                    "role": report.get("role"),
                    "findings": [
                        {
                            "claim_id": finding.get("claim_id"),
                            "relation": finding.get("relation"),
                            "scope": finding.get("scope"),
                            "statement": finding.get("statement"),
                            "citations": finding.get("citations", []),
                        }
                        for finding in report.get("output", {}).get("findings", [])
                    ],
                    "unresolved": report.get("output", {}).get("unresolved", []),
                }
                for report in reports
            ],
            "verdicts": verdicts,
        }
    return output


def group_metrics(rows: dict[str, dict], group_ids: set[str], labels: list[str]) -> dict:
    selected = [
        row for row in rows.values() if row["group_id"] in group_ids
    ]
    if not selected:
        return {"cases": 0, "groups": 0}
    metrics = arm_metrics(selected, labels)
    metrics["groups"] = len({row["group_id"] for row in selected})
    return metrics


def build_task(name: str, run: Path, plan_path: Path, dataset: Path,
               prior_test_plan: Path | None = None,
               exposure_file: Path | None = None) -> dict:
    plan = json.loads(plan_path.read_text())
    rows, trace_diagnostics = read_rows(run, plan)
    by_arm: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_arm.setdefault(row["treatment"], {})[row["case_id"]] = row
    labels = dataset_labels(dataset)
    metrics = {
        arm: arm_metrics(list(cases.values()), labels)
        for arm, cases in by_arm.items()
    }
    paired = paired_rows(by_arm, plan["reference"])
    provider_log = run.parent / "provider_calls.jsonl"
    provider_calls = provider_log_count(provider_log)
    trace_calls = sum(item["calls"] for item in metrics.values())
    if provider_calls is not None and provider_calls != trace_calls:
        raise ValueError(
            f"{name} provider log has {provider_calls} calls but traces have {trace_calls}")
    task = {
        "name": name,
        "task": plan["task"],
        "case_count": len(plan["case_ids"]),
        "plan": {
            "path": str(plan_path),
            "sha256": sha256(plan_path),
            "case_ids": plan["case_ids"],
            "seeds": plan["seeds"],
            "reference": plan["reference"],
            "bootstrap_repeats": plan["bootstrap_repeats"],
        },
        "dataset": {
            "path": str(dataset),
            "sha256": {
                item: sha256(dataset / item)
                for item in ("inputs.jsonl", "_gold/labels.jsonl", "manifest.json")
            },
        },
        "provider": provider_metadata(run, plan),
        "labels": labels,
        "metrics": metrics,
        "paired_vs_reference": paired,
        "trace_diagnostics": trace_diagnostics,
        "provider_log": {
            "path": str(provider_log),
            "calls": provider_calls,
            "trace_calls": trace_calls,
            "matches": provider_calls is None or provider_calls == trace_calls,
        },
        "failures": [
            {
                key: row.get(key)
                for key in (
                    "case_id", "group_id", "treatment", "status", "error",
                    "trace_calls", "model_usage_events", "repair_requests",
                    "invalid_outputs")
            }
            for row in rows if row["status"] != "completed"
        ],
        "source": "raw result/failure traces with failures retained in every denominator",
    }
    if plan["task"] == "verification":
        all_groups = {row["group_id"] for row in rows}
        debug_ids = set()
        exposure_studies = {}
        if exposure_file is not None:
            exposure = json.loads(exposure_file.read_text())
            verification_plan = next(
                item for item in exposure if item["task"] == "verification")
            debug_ids = set(verification_plan["debug_group_ids"])
            exposure_studies = verification_plan["debug_group_studies"]
        unused_ids = all_groups - debug_ids
        prior_groups = set()
        if prior_test_plan is not None:
            labels_by_id = jsonl_index(dataset / "_gold" / "labels.jsonl", "case_id")
            prior_plan = json.loads(prior_test_plan.read_text())
            prior_groups = {
                labels_by_id[case_id].get("group_id")
                for case_id in prior_plan["case_ids"]
            }
        overlap = sorted(all_groups & prior_groups)
        if overlap:
            raise ValueError(
                "CIViC development groups overlap the prior 150-case diagnostic set: "
                + ", ".join(overlap))
        task["source_history"] = {
            "prior_150_overlap": overlap,
            "subsets": {
                "previously_exposed_debug": {
                    "groups": sorted(debug_ids),
                    "studies": exposure_studies,
                },
                "previously_unused": {
                    "groups": sorted(unused_ids),
                    "count": len(unused_ids),
                },
            },
            "metrics": {
                "previously_exposed_debug": {
                    arm: group_metrics(cases, debug_ids, labels)
                    for arm, cases in by_arm.items()
                },
                "previously_unused": {
                    arm: group_metrics(cases, unused_ids, labels)
                    for arm, cases in by_arm.items()
                },
            },
        }
    return task


def write_tables(bundle: dict, out: Path) -> None:
    lines = [
        "# Multi-route development tables",
        "",
        "Generated from raw result and failure traces. Every failure remains in the denominator.",
        "",
    ]
    for task_name in ("MTB", "CIViC"):
        task = bundle["tasks"][task_name]
        lines += [
            f"## {task_name}",
            "",
            "| arm | completed | Accuracy | Macro-F1 | calls | input tokens | output tokens | p50 s | p95 s |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for treatment in bundle["plans"][task_name]["treatments"]:
            arm = treatment["name"]
            item = task["metrics"][arm]
            lines.append(
                f"| {arm} | {item['completed']}/{item['cases']} "
                f"({item['completion_rate']:.1%}) | {item['accuracy']:.4f} | "
                f"{item['macro_f1']:.4f} | {item['calls']} | "
                f"{item['input_tokens']} | {item['output_tokens']} | "
                f"{item['p50_seconds']:.2f} | {item['p95_seconds']:.2f} |")
        if task_name == "CIViC":
            lines += [
                "",
                "| arm | class | precision | recall | F1 | support |",
                "|---|---|---:|---:|---:|---:|",
            ]
            for treatment in bundle["plans"][task_name]["treatments"]:
                arm = treatment["name"]
                for label in task["labels"]:
                    item = task["metrics"][arm]["per_class"][label]
                    lines.append(
                        f"| {arm} | {label} | {item['precision']:.4f} | "
                        f"{item['recall']:.4f} | {item['f1']:.4f} | "
                        f"{item['support']} |")
        lines += [
            "",
            "| arm | fixed | broke | candidate-only correct | reference-only correct | both correct | both wrong |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for arm, item in task["paired_vs_reference"].items():
            lines.append(
                f"| {arm} | {item['fixed']} | {item['broke']} | "
                f"{item['candidate_only_correct']} | "
                f"{item['reference_only_correct']} | {item['both_correct']} | "
                f"{item['both_wrong']} |")
        lines += [
            "",
            "| arm | trace calls | usage events | calls without usage | invalid outputs | repair requests |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for treatment in bundle["plans"][task_name]["treatments"]:
            arm = treatment["name"]
            item = task["metrics"][arm]
            lines.append(
                f"| {arm} | {item['calls']} | {item['model_usage_events']} | "
                f"{item['calls_without_usage_event']} | {item['invalid_outputs']} | "
                f"{item['repair_requests']} |")
        lines += [
            "",
            "| arm | completed Verifier cases | assigned claims | final verdicts | missing verdicts | "
            "adopted rejected | adopted insufficient | invalid verifier citations |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for treatment in bundle["plans"][task_name]["treatments"]:
            arm = treatment["name"]
            item = task["metrics"][arm]["completed_protocol_audit"]
            lines.append(
                f"| {arm} | {item['verifier_cases']} | {item['assigned_claims']} | "
                f"{item['verdicts']} | {item['missing_verdicts']} | "
                f"{item['adopted_rejected']} | {item['adopted_insufficient']} | "
                f"{item['invalid_verifier_citations']} |")
        failures = Counter(
            (row["treatment"], row["status"], row.get("error"))
            for row in task["failures"])
        if failures:
            lines += [
                "",
                "| arm | status | reason | count |",
                "|---|---|---|---:|",
            ]
            for (arm, status, error), count in sorted(
                    failures.items(), key=lambda item: (item[0][0], item[0][1], str(item[0][2]))):
                lines.append(
                    f"| {arm} | {status} | {error or 'budget exhausted'} | {count} |")
        if "source_history" in task:
            lines += [
                "",
                "### Source-history strata",
                "",
                "The 19/41 split is the exposure state frozen before the formal screen. "
                "All 60 cases are development data after this run.",
                "",
                "| stratum | arm | cases | completed | Accuracy | Macro-F1 | calls |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
            for stratum, arms in task["source_history"]["metrics"].items():
                for treatment in bundle["plans"][task_name]["treatments"]:
                    arm = treatment["name"]
                    item = arms[arm]
                    lines.append(
                        f"| {stratum} | {arm} | {item['cases']} | {item['completed']} | "
                        f"{item['accuracy']:.4f} | {item['macro_f1']:.4f} | {item['calls']} |")
        lines.append("")
    (out / "TABLES.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mtb-run", type=Path, required=True)
    parser.add_argument("--mtb-plan", type=Path, required=True)
    parser.add_argument("--mtb-dataset", type=Path, required=True)
    parser.add_argument("--civic-run", type=Path, required=True)
    parser.add_argument("--civic-plan", type=Path, required=True)
    parser.add_argument("--civic-dataset", type=Path, required=True)
    parser.add_argument("--civic-prior-test-plan", type=Path)
    parser.add_argument("--civic-exposure", type=Path)
    parser.add_argument("--mtb-case", required=True)
    parser.add_argument("--mtb-case-arm", default="a6_medagentpro")
    parser.add_argument("--civic-case", required=True)
    parser.add_argument("--civic-case-arm", default="a1_medagents")
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--implementation-digest", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    tasks = {
        "MTB": build_task(
            "MTB", args.mtb_run, args.mtb_plan, args.mtb_dataset),
        "CIViC": build_task(
            "CIViC", args.civic_run, args.civic_plan, args.civic_dataset,
            args.civic_prior_test_plan, args.civic_exposure),
    }
    plans = {
        "MTB": json.loads(args.mtb_plan.read_text()),
        "CIViC": json.loads(args.civic_plan.read_text()),
    }
    runs = {"MTB": args.mtb_run, "CIViC": args.civic_run}
    project_root = Path(__file__).resolve().parent.parent
    bundle = {
        "code_commit": args.code_commit,
        "implementation_digest": args.implementation_digest,
        "analysis_sources": {
            str(relative): sha256(project_root / relative)
            for relative in (
                "oncofusion/evaluation.py",
                "scripts/report_multi_route.py",
                "scripts/build_multi_route_delivery.py",
            )
        },
        "runs": {name: str(path) for name, path in runs.items()},
        "plans": plans,
        "tasks": tasks,
        "cases": {
            "MTB": case_evidence(
                args.mtb_run, args.mtb_dataset, args.mtb_case,
                plans["MTB"]["reference"], args.mtb_case_arm,
                plans["MTB"]["seeds"][0]),
            "CIViC": case_evidence(
                args.civic_run, args.civic_dataset, args.civic_case,
                plans["CIViC"]["reference"], args.civic_case_arm,
                plans["CIViC"]["seeds"][0]),
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "bundle.json").write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    protocol = {
        name: {
            "metrics": task["metrics"],
            "incomplete": task["failures"],
            "trace_diagnostics": task["trace_diagnostics"],
        }
        for name, task in tasks.items()
    }
    (args.out / "PROTOCOL_AUDIT.json").write_text(
        json.dumps(protocol, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (args.out / "CASE_EVIDENCE.json").write_text(
        json.dumps(bundle["cases"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    write_tables(bundle, args.out)
    print(json.dumps({
        "bundle": str(args.out / "bundle.json"),
        "tables": str(args.out / "TABLES.md"),
        "protocol_audit": str(args.out / "PROTOCOL_AUDIT.json"),
        "case_evidence": str(args.out / "CASE_EVIDENCE.json"),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
