"""Read-only index of completed real-API runs for demo replay.

Only the allowlisted study directories under the results root are reachable; callers
supply an opaque item id, never a path, so nothing about the filesystem is exposed.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

# name -> (dataset label, study directory name, treatment)
ARMS = (("real_class6b_mtb", "v1_class", "MTBBench dev 课堂样例 · 角色分层版（4 问 · 3 位患者）"),
        ("real_class6b_civic", "v1_class", "CIViC-Fact dev 课堂样例 · 角色分层版（2 条主张 · 2 篇文献）"),
        ("real_class6_mtb", "v1_class", "MTBBench dev 课堂样例（4 问 · 3 位患者）"),
        ("real_class6_civic", "v1_class", "CIViC-Fact dev 课堂样例（2 条主张 · 2 篇文献）"),
        ("real_fast2_mtb", "v1_fast", "MTBBench dev (3 patient groups, 21 questions)"),
        ("real_fast2_mtb_control", "single_tools", "MTBBench dev (single-tool control)"),
        ("real_fast2_civic", "v1_fast", "CIViC-Fact dev (3 article groups, 10 claims)"),
        ("real_fast2_civic_control", "single_tools", "CIViC-Fact dev (single-tool control)"))
DATASET_FILES = {"real_class6b_mtb": "data/mtbbench", "real_class6b_civic": "data/civicfact-pmidids",
                 "real_class6_mtb": "data/mtbbench", "real_class6_civic": "data/civicfact-pmidids",
                 "real_fast2_mtb": "data/mtbbench", "real_fast2_mtb_control": "data/mtbbench",
                 "real_fast2_civic": "data/civicfact-pmidids",
                 "real_fast2_civic_control": "data/civicfact-pmidids"}


_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")


def graph_installed() -> bool:
    from importlib.util import find_spec
    return find_spec("langgraph") is not None


def results_root(root: Path | None = None) -> Path:
    return Path(root or os.getenv("ONCOFUSION_RESULTS_DIR", "results/v1"))


def _case_dir(root: Path, study: str, treatment: str) -> Path:
    return root / study / treatment / "0"


# Each dataset row is re-read once per file signature, not once per replayed result: the 62-item
# list used to re-parse the full CIViC inputs for every row.
_json_index: dict[tuple[str, int, int], dict] = {}


def _jsonl_by_id(folder: Path, key: str) -> dict:
    if not folder.is_file():
        return {}
    stat = folder.stat()
    stamp = (str(folder), stat.st_mtime_ns, stat.st_size)
    cached = _json_index.get(stamp)
    if cached is not None:
        return cached
    rows = {}
    for line in folder.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row[key]] = row
    _json_index.clear() if len(_json_index) > 8 else None
    _json_index[stamp] = rows
    return rows


def _inputs(root_project: Path, study: str) -> dict:
    return _jsonl_by_id(root_project / DATASET_FILES[study] / "inputs.jsonl", "id")


def _labels(root_project: Path, study: str) -> dict:
    return _jsonl_by_id(root_project / DATASET_FILES[study] / "_gold" / "labels.jsonl", "case_id")


def _summary(study: str, treatment: str, label: str, data: dict, root_project: Path) -> dict:
    usage = data.get("usage", {})
    decision = data.get("decision") or {}
    gold = _labels(root_project, study).get(data["case_id"], {})
    per_role = {}
    started = {}
    for event in data.get("trace", []):
        details = event.get("details", {})
        if event.get("kind") == "model_usage":
            earlier = per_role.get(event.get("role"))
            add = {"seconds": details.get("seconds") or 0,
                   "input_tokens": details.get("input_tokens") or 0,
                   "output_tokens": details.get("output_tokens") or 0,
                   "evidence_fragments": details.get("evidence_fragments"),
                   "attempts": details.get("attempts") or 0,
                   "calls": 1}
            if earlier:
                # A schema repair is a second real call: both must appear in the role total.
                add["seconds"] = earlier["seconds"] + add["seconds"]
                add["input_tokens"] = earlier["input_tokens"] + add["input_tokens"]
                add["output_tokens"] = earlier["output_tokens"] + add["output_tokens"]
                add["attempts"] = earlier["attempts"] + add["attempts"]
                add["calls"] = earlier["calls"] + 1
            per_role[event.get("role")] = add
        elif event.get("kind") == "agent_started":
            started[event.get("role")] = {
                "evidence_ids": details.get("evidence_ids"),
                "evidence_coverage": details.get("evidence_coverage"),
                "board_findings": details.get("board_findings"),
                "unresolved_items": details.get("unresolved_items"),
                "source_ids": details.get("source_ids")}
    roles = []
    for report in data.get("reports", []):
        role_usage = per_role.get(report["role"], {})
        hand = started.get(report["role"], {})
        roles.append({"role": report["role"], "executor": report["executor"],
                      "findings": len(report["output"]["findings"]),
                      "citations": sum(len(f["citations"]) for f in report["output"]["findings"]),
                      "unresolved": report["output"]["unresolved"],
                      "seconds": role_usage.get("seconds"),
                      "input_tokens": role_usage.get("input_tokens"),
                      "output_tokens": role_usage.get("output_tokens"),
                      "evidence_fragments": role_usage.get("evidence_fragments"),
                      "evidence_ids": hand.get("evidence_ids"),
                      "evidence_coverage": hand.get("evidence_coverage"),
                      "board_findings": hand.get("board_findings"),
                      "unresolved_items": hand.get("unresolved_items"),
                      "source_ids": hand.get("source_ids")})
    dec_usage = per_role.get("decision", {})
    hand = started.get("decision", {})
    decision_row = {"role": "decision", "executor": "decision",
                    "findings": 1 if decision.get("answer") else 0,
                    "citations": len(decision.get("citations") or []),
                    "unresolved": decision.get("unresolved") or [],
                    "seconds": dec_usage.get("seconds"),
                    "input_tokens": dec_usage.get("input_tokens"),
                    "output_tokens": dec_usage.get("output_tokens"),
                    "evidence_fragments": dec_usage.get("evidence_fragments"),
                    "evidence_ids": hand.get("evidence_ids"),
                    "evidence_coverage": hand.get("evidence_coverage"),
                    "board_findings": hand.get("board_findings"),
                    "unresolved_items": hand.get("unresolved_items"),
                    "source_ids": hand.get("source_ids")}
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
# Keyed by the results root as well: two studies can be served from one process, and a
# time-only cache would answer the wrong directory.
_list_cache: dict[str, tuple[float, list[dict]]] = {}


def _failure(study: str, treatment: str, label: str, path: Path) -> dict:
    """A run that never produced a result row still belongs in the denominator."""
    case_id = path.name[: -len(".failed.json")]
    detail = {}
    try:
        detail = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        detail = {}
    return {"id": "%s:%s:%s" % (study, treatment, case_id), "study": study, "arm": treatment,
            "dataset_label": label, "case_id": case_id, "task": detail.get("task", ""),
            "question": "", "status": "failed", "answer": None, "gold_label": None,
            "group_id": detail.get("group_id"), "calls": None, "input_tokens": None,
            "output_tokens": None, "seconds": None, "simulated": bool(detail.get("simulated", False)),
            "model": detail.get("model"), "citation_count": 0, "roles": [], "failure": detail.get("error")
            or "no result row; the run was recorded as failed", "case": None, "reports": [],
            "decision": None, "config": {}, "fingerprint": None, "usage_full": {}, "trace": []}


def list_items(root: Path | None = None, project: Path | None = None,
                include_failed: bool = True) -> list[dict]:
    global _list_cache
    now = time.monotonic()
    base, project_root = results_root(root), Path(project or Path.cwd())
    stamp = str(base.resolve())
    if include_failed:
        cached = _list_cache.get(stamp)
        if root is None and cached is not None and now - cached[0] < _LIST_TTL_SECONDS:
            return cached[1]
    items = []
    for study, treatment, label in ARMS:
        folder = _case_dir(base, study, treatment)
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name == "summary.json":
                continue
            if path.name.endswith(".failed.json"):
                if include_failed:
                    items.append(_failure(study, treatment, label, path))
                continue
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            items.append(_summary(study, treatment, label, data, project_root))
    if root is None and include_failed:
        if len(_list_cache) > 8:
            _list_cache.clear()
        _list_cache[stamp] = (time.monotonic(), items)
    return items


def get_item(item_id: str, root: Path | None = None, project: Path | None = None) -> dict | None:
    base, project_root = results_root(root), Path(project or Path.cwd())
    parts = item_id.split(":")
    if len(parts) != 3:
        return None
    study, treatment, case_id = parts
    # The whole (study, treatment) pair must be allowlisted: checking only the study let an
    # arbitrary treatment segment such as "../../unapproved" resolve outside the published set.
    if (study, treatment) not in {(arm[0], arm[1]) for arm in ARMS}:
        return None
    if not _CASE_ID.fullmatch(case_id):
        return None
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
                      "attempts": details.get("attempts"),
                      "evidence_fragments": details.get("evidence_fragments"),
                      "fragments": details.get("evidence_fragments"),
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
