"""Read-only index of completed real-API runs for demo replay.

Only the allowlisted study directories under the results root are reachable; callers
supply an opaque item id, never a path, so nothing about the filesystem is exposed.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# name -> (dataset label, study directory name, treatment)
ARMS = (("real_fast2_mtb", "v1_fast", "MTBBench dev (3 patient groups, 21 questions)"),
        ("real_fast2_mtb_control", "single_tools", "MTBBench dev (single-tool control)"),
        ("real_fast2_civic", "v1_fast", "CIViC-Fact dev (3 article groups, 10 claims)"),
        ("real_fast2_civic_control", "single_tools", "CIViC-Fact dev (single-tool control)"))
DATASET_FILES = {"real_fast2_mtb": "data/mtbbench", "real_fast2_mtb_control": "data/mtbbench",
                 "real_fast2_civic": "data/civicfact-pmidids",
                 "real_fast2_civic_control": "data/civicfact-pmidids"}


def results_root(root: Path | None = None) -> Path:
    return Path(root or os.getenv("ONCOFUSION_RESULTS_DIR", "results/v1"))


def _case_dir(root: Path, study: str, treatment: str) -> Path:
    return root / study / treatment / "0"


def _inputs(root_project: Path, study: str) -> dict:
    folder = root_project / DATASET_FILES[study] / "inputs.jsonl"
    if not folder.is_file():
        return {}
    return {row["id"]: row for row in (json.loads(line) for line in folder.read_text().splitlines() if line.strip())}


def _labels(root_project: Path, study: str) -> dict:
    folder = root_project / DATASET_FILES[study] / "_gold" / "labels.jsonl"
    if not folder.is_file():
        return {}
    return {row["case_id"]: row for row in (json.loads(line) for line in folder.read_text().splitlines() if line.strip())}


def _summary(study: str, treatment: str, label: str, data: dict, root_project: Path) -> dict:
    usage = data.get("usage", {})
    decision = data.get("decision") or {}
    gold = _labels(root_project, study).get(data["case_id"], {})
    per_role = {}
    for event in data.get("trace", []):
        if event.get("kind") == "model_usage":
            details = event.get("details", {})
            per_role[event.get("role")] = {"seconds": details.get("seconds"),
                                           "input_tokens": details.get("input_tokens"),
                                           "output_tokens": details.get("output_tokens")}
    roles = [{"role": report["role"], "executor": report["executor"],
              "findings": len(report["output"]["findings"]),
              "citations": sum(len(f["citations"]) for f in report["output"]["findings"]),
              "unresolved": report["output"]["unresolved"],
              "seconds": per_role.get(report["role"], {}).get("seconds"),
              "input_tokens": per_role.get(report["role"], {}).get("input_tokens"),
              "output_tokens": per_role.get(report["role"], {}).get("output_tokens")}
             for report in data.get("reports", [])]
    decision_row = {"role": "decision", "executor": "decision",
                    "findings": 1 if decision.get("answer") else 0,
                    "citations": len(decision.get("citations") or []),
                    "unresolved": [],
                    "seconds": per_role.get("decision", {}).get("seconds"),
                    "input_tokens": per_role.get("decision", {}).get("input_tokens"),
                    "output_tokens": per_role.get("decision", {}).get("output_tokens")}
    roles = roles + [decision_row]
    return {"id": f"{study}:{treatment}:{data['case_id']}", "study": study, "arm": treatment,
            "dataset_label": label, "case_id": data["case_id"], "task": data.get("config", {}).get("mode"),
            "question": _inputs(root_project, study).get(data["case_id"], {}).get("question", ""),
            "status": data.get("status"), "answer": decision.get("answer"),
            "gold_label": gold.get("label"), "group_id": gold.get("group_id"),
            "calls": usage.get("calls"), "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "seconds": round(data.get("duration_seconds", 0), 1),
            "simulated": bool(data.get("simulated")), "model": data.get("model"),
            "citation_count": len(decision.get("citations") or []), "roles": roles,
            "failure": data.get("error")}


# Replay data is append-only and the demo polls it repeatedly, so a short TTL keeps
# the pages responsive without freezing what a reviewer can see.
_LIST_TTL_SECONDS = 30.0
_list_cache: tuple[float, list[dict]] | None = None


def list_items(root: Path | None = None, project: Path | None = None) -> list[dict]:
    global _list_cache
    now = time.monotonic()
    if root is None and _list_cache is not None and now - _list_cache[0] < _LIST_TTL_SECONDS:
        return _list_cache[1]
    base, project_root = results_root(root), Path(project or Path.cwd())
    items = []
    for study, treatment, label in ARMS:
        folder = _case_dir(base, study, treatment)
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name == "summary.json" or path.name.endswith(".failed.json"):
                continue
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            items.append(_summary(study, treatment, label, data, project_root))
    if root is None:
        _list_cache = (time.monotonic(), items)
    return items


def get_item(item_id: str, root: Path | None = None, project: Path | None = None) -> dict | None:
    base, project_root = results_root(root), Path(project or Path.cwd())
    parts = item_id.split(":")
    if len(parts) != 3 or parts[0] not in {arm[0] for arm in ARMS}:
        return None
    study, treatment, case_id = parts
    path = _case_dir(base, study, treatment) / (case_id + ".json")
    allowed = _case_dir(base, study, treatment).resolve()
    if not str(path.resolve()).startswith(str(allowed) + os.sep):
        return None
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    case = _inputs(project_root, study).get(case_id, {})
    label = next(arm[2] for arm in ARMS if arm[0] == study)
    detail = _summary(study, treatment, label, data, project_root)
    usage = data.get("usage", {})
    trace = []
    for event in data.get("trace", []):
        details = event.get("details", {})
        trace.append({"kind": event["kind"], "role": event.get("role"),
                      "seconds": details.get("seconds"), "input_tokens": details.get("input_tokens"),
                      "output_tokens": details.get("output_tokens"),
                      "attempts": details.get("attempts"), "fragments": details.get("evidence_fragments"),
                      "reservation": details.get("token_reservation"), "reason": details.get("reason")})
    detail.update({"case": case, "reports": data.get("reports", []), "decision": data.get("decision"),
                   "config": data.get("config", {}), "fingerprint": data.get("fingerprint"),
                   "usage_full": usage, "trace": trace})
    return detail


def dataset_summary(root: Path | None = None, project: Path | None = None) -> dict:
    rows = []
    for item in list_items(root, project):
        rows.append(item)
    table = {}
    for item in rows:
        key = (item["study"], item["arm"], item["dataset_label"])
        bucket = table.setdefault(key, {"cases": 0, "completed": 0, "correct": 0, "calls": [],
                                       "tokens": [], "seconds": [], "simulated": item["simulated"]})
        bucket["cases"] += 1
        bucket["completed"] += item["status"] == "completed"
        bucket["correct"] += bool(item["status"] == "completed" and item["answer"] and item["gold_label"]
                                 and item["answer"] == item["gold_label"])
        bucket["calls"].append(item["calls"] or 0)
        bucket["tokens"].append((item["input_tokens"] or 0) + (item["output_tokens"] or 0))
        bucket["seconds"].append(item["seconds"] or 0)
    out = []
    for (study, arm, label), bucket in sorted(table.items()):
        seconds = sorted(bucket["seconds"])
        out.append({"study": study, "arm": arm, "dataset_label": label, "cases": bucket["cases"],
                    "completed": bucket["completed"], "completion_rate": round(bucket["completed"] / bucket["cases"], 3),
                    "accuracy": round(bucket["correct"] / bucket["cases"], 4),
                    "calls_per_case": round(sum(bucket["calls"]) / bucket["cases"], 2),
                    "tokens_per_case": round(sum(bucket["tokens"]) / bucket["cases"]),
                    "seconds_p50": seconds[len(seconds) // 2], "seconds_max": seconds[-1],
                    "simulated": bucket["simulated"]})
    return {"note": "开发集验收规模的小批量真实运行，只用于说明流程能跑通，不构成显著性结论；"
                    "标签留在评测侧，仅在这个内部演示里展示。",
            "arms": out}
