"""Export the fixed CIViC vote-v1 confirmation run without discarding failures."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


LABELS = ["SUPPORTS", "REVISIONS", "NEI"]
FAILED = "FAILED"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_arm(directory: Path) -> dict[str, dict]:
    rows = {}
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        if path.name == "summary.json" or path.name.endswith(".failed.json"):
            continue
        result = read_json(path)
        rows[result["case_id"]] = {"result": result, "failure": None, "path": str(path)}
    for path in sorted(directory.glob("*.failed.json")):
        case_id = path.name.removesuffix(".failed.json")
        rows.setdefault(case_id, {"result": None, "failure": read_json(path), "path": str(path)})
    return rows


def usage_and_duration(item: dict | None) -> dict:
    if item is None:
        return {"calls": 0, "http_attempts": 0, "input_tokens": 0,
                "output_tokens": 0, "estimated_tokens": False,
                "duration_seconds": None, "usage_incomplete": True}
    result = item["result"]
    trace = result.get("trace", []) if result else item["failure"].get("trace", [])
    usage = result.get("usage") if result else (
        item["failure"].get("observed_usage") or item["failure"].get("usage"))
    model_events = [event for event in trace if event.get("kind") == "model_usage"]
    agent_events = [event for event in trace if event.get("kind") == "agent_started"]
    if usage:
        calls = int(usage.get("calls", len(agent_events)))
        attempts = int(usage.get("http_attempts", sum(
            event.get("details", {}).get("attempts", 0) for event in model_events)))
        in_tokens = int(usage.get("input_tokens", 0))
        out_tokens = int(usage.get("output_tokens", 0))
        estimated = bool(usage.get("estimated_tokens", False))
        incomplete = False
    else:
        calls = len(agent_events)
        attempts = sum(event.get("details", {}).get("attempts", 0) for event in model_events)
        in_tokens = sum(event.get("details", {}).get("input_tokens", 0) for event in model_events)
        out_tokens = sum(event.get("details", {}).get("output_tokens", 0) for event in model_events)
        estimated = any(event.get("details", {}).get("estimated", False) for event in model_events)
        incomplete = any(event.get("kind") == "agent_started" for event in trace) and not model_events
    duration = result.get("duration_seconds") if result else None
    if duration is None and model_events:
        duration = sum(float(event.get("details", {}).get("seconds", 0)) for event in model_events)
    return {"calls": calls, "http_attempts": attempts, "input_tokens": in_tokens,
            "output_tokens": out_tokens, "estimated_tokens": estimated,
            "duration_seconds": duration, "usage_incomplete": incomplete}


def prediction(item: dict | None) -> str | None:
    if item is None or item["result"] is None:
        return None
    result = item["result"]
    answer = (result.get("decision") or {}).get("answer")
    if answer in LABELS:
        return answer
    return None


def status(item: dict | None) -> str:
    if item is None:
        return "missing"
    if item["result"] is None:
        return "failed"
    return item["result"].get("status", "failed")


def vote_status(item: dict | None) -> str:
    if item is None or item["result"] is None:
        return "failed"
    vote = item["result"].get("vote_result") or {}
    return vote.get("completion_status", "failed")


def class_metrics(rows: list[dict], predicted_key: str) -> dict:
    matrix = {gold: {pred: 0 for pred in LABELS + [FAILED]} for gold in LABELS}
    correct = 0
    per_class = {}
    for row in rows:
        gold = row["gold_label"]
        pred = row.get(predicted_key)
        pred = pred if pred in LABELS else FAILED
        matrix[gold][pred] += 1
        correct += pred == gold
    for label in LABELS:
        tp = matrix[label][label]
        fp = sum(matrix[other][label] for other in LABELS if other != label)
        fn = sum(matrix[label][other] for other in LABELS if other != label) + matrix[label][FAILED]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1,
                            "support": sum(matrix[label].values())}
    n = len(rows)
    return {"n": n, "correct": correct, "accuracy": correct / n if n else None,
            "macro_f1": sum(v["f1"] for v in per_class.values()) / len(LABELS) if n else None,
            "valid_answers": sum(row.get(predicted_key) in LABELS for row in rows),
            "completion_rate": sum(row.get(predicted_key) in LABELS for row in rows) / n if n else None,
            "completion_status_counts": dict(Counter(row.get({
                "b0_prediction": "b0_completion",
                "no_arb_prediction": "no_arb_completion",
                "oncofusion_prediction": "oncofusion_completion",
            }[predicted_key], "failed") for row in rows)),
            "per_class": per_class, "confusion_matrix": matrix}


def cluster_bootstrap(rows: list[dict], candidate: str, reference: str,
                      repeats: int = 2000, seed: int = 0) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        group = row["source_group_id"]
        grouped[group].append((int(row.get(candidate) == row["gold_label"]),
                               int(row.get(reference) == row["gold_label"])))
    groups = sorted(grouped)
    observed = sum(a - b for group in groups for a, b in grouped[group]) / len(rows)
    rng = random.Random(seed)
    sampled = []
    for _ in range(repeats):
        draw = [rng.choice(groups) for _ in groups]
        pairs = [pair for group in draw for pair in grouped[group]]
        sampled.append(sum(a - b for a, b in pairs) / len(pairs))
    sampled.sort()
    return {"mean_accuracy_difference": observed,
            "ci95": [sampled[math.floor(.025 * repeats)], sampled[min(repeats - 1, math.ceil(.975 * repeats) - 1)]],
            "source_groups": len(groups), "repeats": repeats, "seed": seed}


def paired_counts(rows: list[dict], candidate: str, reference: str) -> dict:
    both_valid = fixed = broke = recovery = 0
    for row in rows:
        new, old, gold = row.get(candidate), row.get(reference), row["gold_label"]
        if old in LABELS and new in LABELS:
            both_valid += 1
            fixed += old != gold and new == gold
            broke += old == gold and new != gold
        if old not in LABELS and new in LABELS and new == gold:
            recovery += 1
    return {"both_valid": both_valid, "changed_wrong_to_right": fixed,
            "changed_right_to_wrong": broke, "net_corrections": fixed - broke,
            "single_agent_failure_recovered_by_oncofusion": recovery}


def plain_answer(item: dict | None) -> dict:
    if item is None or item["result"] is None:
        return {}
    return item["result"].get("decision") or {}


def raw_arbitration(item: dict | None) -> dict:
    if item is None or item["result"] is None:
        return {}
    return ((item["result"].get("vote_result") or {}).get("arbitration") or {})


def quote_for(case: dict, row: dict) -> dict | None:
    result = row.get("_full_result")
    candidates = []
    if result:
        candidates.extend((result.get("decision") or {}).get("citations", []))
    if not candidates:
        result = row.get("_pool_result")
        for ballot in (result or {}).get("ballots", []):
            candidates.extend(ballot.get("citations", []))
            for finding in ballot.get("findings", []):
                candidates.extend(finding.get("citations", []))
    docs = {doc.get("id"): doc for doc in case.get("documents", [])}
    for citation in candidates:
        doc = docs.get(citation.get("document_id"))
        if not doc:
            continue
        start, end = citation.get("start"), citation.get("end")
        text = doc.get("text", "")
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
            continue
        exact = text[start:end]
        if citation.get("quote") and exact != citation["quote"]:
            continue
        words = exact.split()
        excerpt = " ".join(words[:22])
        if len(words) > 22:
            excerpt = excerpt.rstrip(".,;:") + " …"
        return {"document_id": doc.get("id"), "pmid": str(doc.get("id", "")).removeprefix("pmid-"),
                "start": start, "end": end, "excerpt": excerpt, "word_count": min(len(words), 22)}
    return None


def case_note(case_id: str, row: dict, case: dict, cohort: str) -> str:
    votes = row.get("ballots", [])
    roles = ", ".join(dict.fromkeys(ballot.get("role", "") for ballot in votes)) or "无有效选票"
    tally = Counter(ballot.get("label") for ballot in votes
                    if ballot.get("status") == "vote" and ballot.get("label") in LABELS)
    arb = row.get("arbitration", {})
    citation = quote_for(case, row)
    lines = [f"### {case_id}", "", f"- 队列：{cohort}；来源 PMID：{row['pmid']}。",
             f"- 待核验主张（原文）：{case.get('question', '').strip()}",
             f"- 专业角色：{roles}；选票分布：" + (", ".join(f"{k} {v}" for k, v in sorted(tally.items())) or "无") + ".",
             f"- 初始等权标签：{row.get('initial_label') or '无有效标签'}；仲裁触发：{'是' if arb.get('triggered') else '否'}；仲裁状态：{arb.get('status', '未执行')}。",
             f"- 仲裁前/后：{arb.get('initial_label') or row.get('initial_label') or '无'} → {arb.get('final_label') or row.get('initial_label') or '无'}；最终标签：{row.get('oncofusion_prediction') or '失败'}；参考标签：{row['gold_label']}。"]
    if citation:
        lines += [f"- 原文摘录（PMID {citation['pmid']}，{citation['word_count']}词，偏移 {citation['start']}–{citation['end']}）：“{citation['excerpt']}”",
                  "- 中文释义：待根据以上短摘录填写忠实译文；这不是模型输出。"]
    else:
        lines += ["- 原文摘录：该运行没有可公开核对的精确引用；不从其他段落补造。",
                  "- 中文释义：无。"]
    reason_rows = []
    for ballot in votes:
        reason = re.sub(r"\s+", " ", ballot.get("brief_reason", "")).strip()
        short_reason = " ".join(reason.split()[:5])
        if len(reason.split()) > 5:
            short_reason += " …"
        reason_rows.append(f"  - {ballot.get('role')}: {ballot.get('label') or ballot.get('status')}；依据：{short_reason or '无保存的简短依据'}")
    if reason_rows:
        lines += ["- 角色简短依据（模型原始短输出，公开版截短）：", *reason_rows]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-register", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--ended-at", required=True)
    parser.add_argument("--provider-settings", type=Path, required=True)
    parser.add_argument("--arbitration-workers", type=int, default=20)
    args = parser.parse_args()

    plan = read_json(args.plan)
    register = read_json(args.source_register)
    input_path = args.dataset / "inputs.jsonl"
    gold_path = args.dataset / "_gold" / "labels.jsonl"
    inputs = {row["id"]: row for row in read_jsonl(input_path)}
    gold = {row["case_id"]: row for row in read_jsonl(gold_path)}
    case_ids = plan["case_ids"]
    assert len(case_ids) == 117 and len(set(case_ids)) == 117
    assert all(case_id in inputs and case_id in gold for case_id in case_ids)
    assert set(plan["treatments"][i]["name"] for i in range(2)) == {"b0_common_single", "p_k_specialists"}
    b0_rows = load_arm(args.run / "b0_common_single" / "0")
    pool_rows = load_arm(args.run / "p_k_specialists" / "0")
    v3_rows = load_arm(args.run / "v3" / "p_k_specialists" / "0")
    expected_pool = {case_id for case_id, item in pool_rows.items()
                     if item["result"] and (item["result"].get("ballots") or [])}
    if expected_pool != set(v3_rows):
        raise ValueError(f"V3 result coverage differs from generated vote pools: expected={len(expected_pool)} actual={len(v3_rows)}")
    for name, rows in (("b0_common_single", b0_rows), ("p_k_specialists", pool_rows)):
        extra = set(rows) - set(case_ids)
        if extra:
            raise ValueError(f"unexpected case records in {name}: {len(extra)}")

    used_groups = {item["group_id"] for item in register["historically_used_source_groups"]}
    rows = []
    for case_id in case_ids:
        b0, pool, full = b0_rows.get(case_id), pool_rows.get(case_id), v3_rows.get(case_id)
        case = inputs[case_id]
        g = gold[case_id]
        base_result = pool["result"] if pool and pool["result"] else None
        full_result = full["result"] if full and full["result"] else None
        ballots = (base_result or {}).get("ballots", [])
        arb = raw_arbitration(full)
        no_arb_prediction = prediction(pool)
        full_prediction = prediction(full) if full else no_arb_prediction if base_result and not ballots else None
        if full_result:
            initial = arb.get("initial_label") or no_arb_prediction
        else:
            initial = no_arb_prediction
        if base_result and full_result:
            if initial != no_arb_prediction:
                raise ValueError(f"initial vote differs from saved pool for {case_id}")
        source_group = g["group_id"]
        docs = case.get("documents", [])
        pmid = str(docs[0].get("id", "")).removeprefix("pmid-") if docs else source_group.removeprefix("article-")
        row = {
            "case_id": case_id, "source_group_id": source_group, "pmid": pmid,
            "gold_label": g["label"], "history_use": "previously_used" if source_group in used_groups else "previously_unused",
            "b0_prediction": prediction(b0), "b0_status": status(b0),
            "b0_completion": vote_status(b0), "b0_usage": usage_and_duration(b0),
            "no_arb_prediction": no_arb_prediction, "no_arb_status": status(pool),
            "no_arb_completion": vote_status(pool), "no_arb_usage": usage_and_duration(pool),
            "oncofusion_prediction": full_prediction,
            "oncofusion_status": status(full) if full else ("failed" if base_result is None or ballots else "failed"),
            "oncofusion_completion": vote_status(full) if full else "failed",
            "oncofusion_usage": usage_and_duration(full) if full else usage_and_duration(pool),
            "ballots": ballots, "roles": (base_result or {}).get("vote_result", {}).get("planned_roles", []),
            "valid_votes": (base_result or {}).get("vote_result", {}).get("valid_votes", 0),
            "vote_counts": (base_result or {}).get("vote_result", {}).get("counts", {}),
            "initial_label": initial, "arbitration": arb,
            "visible_document_ids": (base_result or {}).get("visible_document_ids", []),
            "base_trace_ref": pool["path"] if pool else "",
            "full_trace_ref": full["path"] if full else "",
            "b0_trace_ref": b0["path"] if b0 else "",
            "_case": case, "_pool_result": base_result, "_full_result": full_result,
        }
        if row["b0_prediction"] not in LABELS:
            row["b0_prediction"] = None
        if row["no_arb_prediction"] not in LABELS:
            row["no_arb_prediction"] = None
        if row["oncofusion_prediction"] not in LABELS:
            row["oncofusion_prediction"] = None
        row["gold_label"] = g["label"]
        row["b0_completion"] = row["b0_completion"] if row["b0_prediction"] else "failed"
        row["no_arb_completion"] = row["no_arb_completion"] if row["no_arb_prediction"] else "failed"
        row["oncofusion_completion"] = row["oncofusion_completion"] if row["oncofusion_prediction"] else "failed"
        rows.append(row)

    cohorts = {
        "all_117_fixed": rows,
        "previously_unused_114": [row for row in rows if row["history_use"] == "previously_unused"],
        "previously_used_3": [row for row in rows if row["history_use"] == "previously_used"],
    }
    if (len(cohorts["previously_unused_114"]) != 114 or len(cohorts["previously_used_3"]) != 3):
        raise ValueError("source-use partition changed from frozen 114/3 registration")

    result_systems = {
        "single_agent_b0_common_single": "b0_prediction",
        "oncofusion_v3_arbitrated": "oncofusion_prediction",
        "oncofusion_v0_no_arbitration": "no_arb_prediction",
    }
    metrics = {cohort: {name: class_metrics(part, key) for name, key in result_systems.items()}
               for cohort, part in cohorts.items()}
    paired = {}
    for cohort, part in cohorts.items():
        paired[cohort] = {
            "oncofusion_vs_b0": {
                "accuracy_delta_cluster_bootstrap": cluster_bootstrap(part, "oncofusion_prediction", "b0_prediction"),
                **paired_counts(part, "oncofusion_prediction", "b0_prediction"),
            },
            "full_vs_no_arbitration": {
                "accuracy_delta": metrics[cohort]["oncofusion_v3_arbitrated"]["accuracy"] - metrics[cohort]["oncofusion_v0_no_arbitration"]["accuracy"],
                "macro_f1_delta": metrics[cohort]["oncofusion_v3_arbitrated"]["macro_f1"] - metrics[cohort]["oncofusion_v0_no_arbitration"]["macro_f1"],
                **paired_counts(part, "oncofusion_prediction", "no_arb_prediction"),
            },
        }

    trigger_rows = [row for row in rows if row["arbitration"].get("triggered")]
    arb = Counter()
    for row in trigger_rows:
        arbitration = row["arbitration"]
        initial, final, gold_label = arbitration.get("initial_label"), arbitration.get("final_label"), row["gold_label"]
        arb["triggered"] += 1
        arb["completed" if arbitration.get("status") == "completed" else "failed"] += 1
        if initial in LABELS and final in LABELS:
            if initial != gold_label and final == gold_label:
                arb["wrong_to_right"] += 1
            if initial == gold_label and final != gold_label:
                arb["right_to_wrong"] += 1
            if initial == final == gold_label:
                arb["retained_initial_correct"] += 1
            if initial == final and initial != gold_label:
                arb["retained_initial_wrong"] += 1
    arb["not_triggered"] = sum(not row["arbitration"].get("triggered", False) for row in rows)

    args.out.mkdir(parents=True, exist_ok=True)
    main_rows = []
    for cohort, part in cohorts.items():
        for name in ("single_agent_b0_common_single", "oncofusion_v3_arbitrated"):
            main_rows.append({"cohort": cohort, "system": name, **metrics[cohort][name]})
    ablation_rows = []
    for cohort, part in cohorts.items():
        for name in ("oncofusion_v0_no_arbitration", "oncofusion_v3_arbitrated"):
            ablation_rows.append({"cohort": cohort, "system": name, **metrics[cohort][name]})
    for name, data in (("main_table.csv", main_rows), ("ablation_table.csv", ablation_rows)):
        keys = ["cohort", "system", "n", "correct", "accuracy", "macro_f1", "valid_answers", "completion_rate", "completion_status_counts", "per_class", "confusion_matrix"]
        with (args.out / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys)
            writer.writeheader()
            for row in data:
                writer.writerow({key: json.dumps(row[key], ensure_ascii=False, sort_keys=True) if isinstance(row[key], (dict, list)) else row[key] for key in keys})

    csv_rows = []
    for row in rows:
        record = {key: row[key] for key in ("case_id", "source_group_id", "pmid", "gold_label", "history_use", "b0_status", "b0_prediction", "no_arb_status", "no_arb_prediction", "oncofusion_status", "oncofusion_prediction", "initial_label")}
        record.update({
            "roles": ";".join(row["roles"]),
            "ballots": json.dumps([{k: ballot.get(k) for k in ("role", "status", "label", "confidence")} for ballot in row["ballots"]], ensure_ascii=False, sort_keys=True),
            "valid_votes": row["valid_votes"], "vote_counts": json.dumps(row["vote_counts"], ensure_ascii=False, sort_keys=True),
            "arbitration_triggered": row["arbitration"].get("triggered", False),
            "arbitration_status": row["arbitration"].get("status", "unavailable"),
            "arbitration_initial_label": row["arbitration"].get("initial_label"),
            "arbitration_final_label": row["arbitration"].get("final_label"),
        })
        for prefix in ("b0", "no_arb", "oncofusion"):
            cost = row[prefix + "_usage"]
            record.update({
                prefix + "_calls": cost["calls"], prefix + "_http_attempts": cost["http_attempts"],
                prefix + "_input_tokens": cost["input_tokens"], prefix + "_output_tokens": cost["output_tokens"],
                prefix + "_duration_seconds": cost["duration_seconds"], prefix + "_usage_incomplete": cost["usage_incomplete"],
            })
        record["raw_pool_record"] = row["base_trace_ref"]
        record["raw_arbitration_record"] = row["full_trace_ref"]
        record["raw_b0_record"] = row["b0_trace_ref"]
        csv_rows.append(record)
    with (args.out / "paired_cases.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)

    provider_settings = read_json(args.provider_settings)
    source_files = ["oncofusion/vote_runner.py", "oncofusion/voting.py", "oncofusion/evidence.py",
                    "oncofusion/agent_design.py", "oncofusion/profiles.py", "oncofusion/schemas.py",
                    "oncofusion/providers.py", "oncofusion/experiments.py", "scripts/run_study.py",
                    "scripts/run_vote_arbitration.py"]
    source_hashes = {path: sha256(args.source_root / path) for path in source_files}
    frozen = {
        "benchmark": "CIViC-Fact source-isolated confirmation supplement",
        "label_version": "2026.06.09 native labels: SUPPORTS / REVISIONS / NEI",
        "split": "dev; source-isolated confirmation set, not official complete test set",
        "case_ids": case_ids,
        "source_groups": [{"case_id": cid, "group_id": gold[cid]["group_id"],
                           "pmid": next((str(doc.get("id", "")).removeprefix("pmid-") for doc in inputs[cid].get("documents", [])), "")}
                          for cid in case_ids],
        "label_counts": dict(Counter(gold[cid]["label"] for cid in case_ids)),
        "prior_use_partition": register,
        "input_sha256": sha256(input_path), "gold_sha256": sha256(gold_path),
        "fixed_plan_sha256": sha256(args.plan),
        "source_register_sha256": sha256(args.source_register),
        "model_display_name": "千问 3.6 35B-A3B",
        "provider_settings": provider_settings,
        "study_plan": plan,
        "method": {
            "b0": "b0_common_single; one generalist; temperature 0; one shared evidence package",
            "oncofusion": "p_k_specialists ballots at temperature 0.4, equal count aggregation, then one V3 semantic arbitration only when triggered",
            "no_arbitration_ablation": "the same saved p_k_specialists ballots and V0 equal-count initial label; no second ballot generation",
            "roles": "eligible_vote_roles / vote_role_applicability; up to four; all selected roles see the same eligible evidence package; non-applicable roles are skipped",
            "voting": "equal-weight votes; self-reported confidence is recorded only",
            "arbitration_trigger": "strict top vote share < 0.75 OR strict top-minus-runner-up margin share < 0.25",
            "tie_seed": 0,
            "schema_retries": 2,
            "max_output_tokens": 5000,
            "arbitration_failure": "retain initial vote label; no new specialist ballots",
        },
        "inference_source_sha256": source_hashes,
        "source_commit_used_for_run": args.source_commit,
        "started_at": args.started_at, "ended_at": args.ended_at,
        "result_paths_server_only": {
            "base_run": str(args.run), "arbitration_run": str(args.run / "v3"),
            "raw_case_traces": "<base_run>/<arm>/0/<case_id>.json or .failed.json",
        },
        "accounting": {
            "expected_cases_per_system": 117, "expected_configuration_records": 351,
            "api_call_concurrency_cap": 20, "arbitration_workers": args.arbitration_workers,
            "maximum_model_calls": {
                "B0": 117 * 3, "shared_professional_pool": 117 * 12,
                "additional_arbitration": 117 * 3,
                "total": 117 * (3 + 12 + 3),
            },
            "bootstrap": {"unit": "article source group", "repeats": 2000, "seed": 0},
            "usage_note": "Dollar cost is not estimated because provider prices were not supplied.",
        },
    }
    (args.out / "frozen_protocol.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metrics_payload = {
        "cohorts": {name: {"cases": len(part), "source_groups": len({row['source_group_id'] for row in part}),
                           "prior_use_counts": dict(Counter(row["history_use"] for row in part))}
                    for name, part in cohorts.items()},
        "metrics": metrics, "paired": paired,
        "arbitration": dict(arb),
        "usage_totals": {system: {
            "calls": sum(row[system + "_usage"]["calls"] for row in rows),
            "http_attempts": sum(row[system + "_usage"]["http_attempts"] for row in rows),
            "input_tokens": sum(row[system + "_usage"]["input_tokens"] for row in rows),
            "output_tokens": sum(row[system + "_usage"]["output_tokens"] for row in rows),
            "duration_seconds_sum": sum(row[system + "_usage"]["duration_seconds"] or 0 for row in rows),
            "usage_incomplete_cases": sum(row[system + "_usage"]["usage_incomplete"] for row in rows),
            "estimated_token_cases": sum(row[system + "_usage"]["estimated_tokens"] for row in rows),
        } for system in ("b0", "no_arb", "oncofusion")},
        "actual_unique_execution_usage": {
            "calls": sum(row["b0_usage"]["calls"] + row["no_arb_usage"]["calls"]
                         + max(0, row["oncofusion_usage"]["calls"] - row["no_arb_usage"]["calls"])
                         for row in rows),
            "input_tokens": sum(row["b0_usage"]["input_tokens"] + row["no_arb_usage"]["input_tokens"]
                                + max(0, row["oncofusion_usage"]["input_tokens"] - row["no_arb_usage"]["input_tokens"])
                                for row in rows),
            "output_tokens": sum(row["b0_usage"]["output_tokens"] + row["no_arb_usage"]["output_tokens"]
                                 + max(0, row["oncofusion_usage"]["output_tokens"] - row["no_arb_usage"]["output_tokens"])
                                 for row in rows),
            "definition": "B0 calls + one shared specialist pool + actual additional arbitration calls; the two specialist-derived result rows are not added twice.",
        },
        "concurrency": {
            "base_run": read_json(args.run / "concurrency.json") if (args.run / "concurrency.json").exists() else None,
            "arbitration": (read_json(args.run / "v3" / "arbitration.json").get("concurrency")
                            if (args.run / "v3" / "arbitration.json").exists() else None),
        },
        "configuration_records": len(rows) * 3,
        "api_call_count_is_not_configuration_record_count": True,
    }
    (args.out / "metrics.json").write_text(json.dumps(metrics_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Deterministic case selection: first qualifying fixed case for each process illustration.
    vote_case = next((row for row in rows if not row["arbitration"].get("triggered")
                      and sum(b.get("status") == "vote" and b.get("label") in LABELS for b in row["ballots"]) >= 3
                      and len({b.get("label") for b in row["ballots"] if b.get("label") in LABELS}) > 1), None)
    if vote_case is None:
        vote_case = next((row for row in rows if sum(
            b.get("status") == "vote" and b.get("label") in LABELS for b in row["ballots"]) >= 3
            and not row["arbitration"].get("triggered")), None)
    arb_case = next((row for row in rows if row["arbitration"].get("triggered")
                     and (vote_case is None or row["pmid"] != vote_case["pmid"])), None)
    case_notes = ["# 课堂案例（脱敏公开版）", "",
                  "按预先固定的顺序规则选取：先取固定名单中第一个未触发仲裁且至少三张有效专业票的案例，再取第一个不同的实际仲裁案例。以下是过程示例，不用于替代总体统计。", ""]
    for row, tag in ((vote_case, "专业投票示例"), (arb_case, "实际触发仲裁示例")):
        if row is not None:
            case_notes += [f"## {tag}", "", case_note(row["case_id"], row, row["_case"], row["history_use"]), ""]
    if arb_case is None:
        case_notes += ["## 仲裁示例", "", "117条中未发现可展示的实际触发仲裁记录；未构造虚假案例。", ""]
    (args.out / "cases_redacted.md").write_text("\n".join(case_notes), encoding="utf-8")

    lines = ["# CIViC-Fact vote-v1 补充评测", "",
             "本报告展示一项同一方法设计下的CIViC来源隔离补充评测。它不声称逐字复现MTB历史运行的提示，也不是官方完整测试集。", "",
             f"- 代码提交：`{args.source_commit}`；模型：千问 3.6 35B-A3B（接口标识 `{provider_settings.get('model', 'hc-qwen38-27b-fp8')}`）。",
             f"- 固定名单：117条、117个来源组；标签 SUPPORTS 42、REVISIONS 15、NEI 60。",
             "- 已登记此前进入调试/开发的来源组3个；整批结果同时给出117条全名单、114条未用组和3条已用组。各配置沿用完全相同的名单。",
             "- 单Agent只调用一次通用角色；完整OncoFusion和去除仲裁共享同一批专业选票，只有仲裁步骤不同。", "",
             "## 主比较：单Agent与完整OncoFusion", "",
             "见`main_table.csv`。主解释口径为此前未用来源组114条；全117条和已用3条也保留。技术失败保留在Accuracy分母，不映射为NEI。", "",
             "| 队列 | 系统 | 正确/样本 | Accuracy | Macro-F1 | 有效答案完成率 |",
             "|---|---|---:|---:|---:|---:|"]
    for cohort in ("previously_unused_114", "all_117_fixed", "previously_used_3"):
        for name in ("single_agent_b0_common_single", "oncofusion_v3_arbitrated"):
            m = metrics[cohort][name]
            lines.append(f"| {cohort} | {name} | {m['correct']}/{m['n']} | {m['accuracy']:.4f} | {m['macro_f1']:.4f} | {m['valid_answers']}/{m['n']} ({m['completion_rate']:.4f}) |")
    lines += ["", "## 仲裁消融", "", "完整方法与去除仲裁使用相同专业选票；去除仲裁只输出初始等权标签。见`ablation_table.csv`。", "",
              f"- 实际仲裁触发：{arb['triggered']}；完成：{arb['completed']}；失败：{arb['failed']}；未触发：{arb['not_triggered']}。",
              f"- 错误改对：{arb['wrong_to_right']}；正确改错：{arb['right_to_wrong']}；原本正确且保持：{arb['retained_initial_correct']}；原本错误且保持：{arb['retained_initial_wrong']}。", "",
              "## 配对结果", "", "来源组配对bootstrap 2000次，统计seed=0。点估计和95%区间见`metrics.json`。", "",
              f"- 114条未用来源组上，OncoFusion相对B0准确率差：{paired['previously_unused_114']['oncofusion_vs_b0']['accuracy_delta_cluster_bootstrap']['mean_accuracy_difference']:+.4f}，95% CI {paired['previously_unused_114']['oncofusion_vs_b0']['accuracy_delta_cluster_bootstrap']['ci95']}。",
              f"- 双方均有有效答案：{paired['previously_unused_114']['oncofusion_vs_b0']['both_valid']}；改错为对：{paired['previously_unused_114']['oncofusion_vs_b0']['changed_wrong_to_right']}；改对为错：{paired['previously_unused_114']['oncofusion_vs_b0']['changed_right_to_wrong']}；B0失败而OncoFusion答对：{paired['previously_unused_114']['oncofusion_vs_b0']['single_agent_failure_recovered_by_oncofusion']}。", "",
              "## 运行成本与审计", "",
              "逐例调用、token、耗时、引用来源和服务器原始轨迹路径见`paired_cases.csv`。`metrics.json`列出汇总用量；模型价格未提供，未估算USD。", "",
              "病例级原始JSON、失败轨迹、API请求哈希和私有证据仍保存在server21结果目录。", ""]
    (args.out / "FINAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    manifest_lines = []
    for path in sorted(args.out.iterdir()):
        if path.is_file() and path.name != "MANIFEST.sha256":
            manifest_lines.append(f"{sha256(path)}  {path.name}")
    (args.out / "MANIFEST.sha256").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(rows), "configuration_records": len(rows) * 3,
                      "arbitration": dict(arb), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
