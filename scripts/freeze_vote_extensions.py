from __future__ import annotations
import argparse, copy, hashlib, json, re
from collections import defaultdict
from pathlib import Path

CASE = re.compile(r"(mtb-P-[0-9]{7}-q[0-9]+)(?:\.failed)?\.json$")

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", type=Path, required=True)
    ap.add_argument("--history", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    test_plan = json.loads((args.worktree / "experiments/v1_compare_mtb_test140.json").read_text())
    template = json.loads((args.worktree / "experiments/vote_v1_mtb_dev43_20261109.json").read_text())
    test_ids = list(test_plan["case_ids"])
    test_set = set(test_ids)
    group_for = lambda cid: cid.split("-q", 1)[0]
    result_cases: dict[str, set[str]] = defaultdict(set)
    roots: dict[str, set[str]] = defaultdict(set)
    for path in (args.history / "results/v1").rglob("*"):
        if not path.is_file():
            continue
        match = CASE.fullmatch(path.name)
        if not match or match.group(1) not in test_set:
            continue
        case_id = match.group(1)
        group = group_for(case_id)
        result_cases[group].add(case_id)
        roots[group].add(path.relative_to(args.history / "results/v1").parts[0])
    all_groups = sorted({group_for(cid) for cid in test_ids})
    excluded_groups = sorted(result_cases)
    eligible_ids = [cid for cid in test_ids if group_for(cid) not in result_cases]
    eligible_groups = sorted({group_for(cid) for cid in eligible_ids})
    if len(test_ids) != 140 or len(all_groups) != 32:
        raise ValueError(f"test frame changed: {len(test_ids)} cases/{len(all_groups)} groups")
    if "mtb-P-0004727" not in result_cases:
        raise ValueError("known debug patient P-0004727 was not found in historical result files")
    if len(excluded_groups) != 13:
        raise ValueError(f"historical source audit changed: expected 13 executed groups, found {len(excluded_groups)}")
    plan = copy.deepcopy(template)
    plan["name"] = "vote_extensions_mtb_source_isolated_holdout_20261125"
    plan["split"] = "test"
    plan["case_ids"] = eligible_ids
    plan["treatments"] = [t for t in plan["treatments"] if t["name"] in {"b0_common_single", "p_k_specialists"}]
    if [t["name"] for t in plan["treatments"]] != ["b0_common_single", "p_k_specialists"]:
        raise ValueError("unexpected fixed treatment list")
    plan["reference"] = "b0_common_single"
    plan["bootstrap_repeats"] = 2000
    plan_path = args.worktree / "experiments/vote_extensions_20261125/mtb_holdout.json"
    write_json(plan_path, plan)
    input_hash = sha256(args.data / "inputs.jsonl")
    gold_hash = sha256(args.data / "_gold/labels.jsonl")
    register = {
        "cohort": "MTBBench nominal test split; source-isolated confirmation",
        "selection_rule": "Exclude an entire test patient group if any case-level result file exists in historical results/v1. Static test-list mentions without case result files are not treated as model execution.",
        "test_frame_cases": len(test_ids),
        "test_frame_groups": len(all_groups),
        "historically_executed_groups": excluded_groups,
        "historically_executed_case_counts_by_group": {g: len(result_cases[g]) for g in excluded_groups},
        "historical_result_roots_by_group": {g: sorted(roots[g]) for g in excluded_groups},
        "eligible_groups": eligible_groups,
        "eligible_case_ids": eligible_ids,
        "eligible_cases": len(eligible_ids),
        "eligible_groups_count": len(eligible_groups),
        "data_input_sha256": input_hash,
        "data_gold_sha256_evaluation_only": gold_hash,
        "test_frame_plan_sha256": sha256(args.worktree / "experiments/v1_compare_mtb_test140.json"),
        "frozen_run_plan_sha256": sha256(plan_path),
        "known_debug_patient_group": "mtb-P-0004727",
        "created_utc_source": "server timestamp recorded in RUN_MANIFEST.json"
    }
    write_json(args.out / "mtb_holdout_source_register_private.json", register)
    public_register = {k: v for k, v in register.items() if k not in {"historically_executed_groups", "historically_executed_case_counts_by_group", "historical_result_roots_by_group", "eligible_groups", "eligible_case_ids"}}
    public_register["excluded_group_list_sha256"] = hashlib.sha256("\n".join(excluded_groups).encode()).hexdigest()
    public_register["eligible_group_list_sha256"] = hashlib.sha256("\n".join(eligible_groups).encode()).hexdigest()
    public_register["eligible_case_list_sha256"] = hashlib.sha256("\n".join(eligible_ids).encode()).hexdigest()
    write_json(args.worktree / "artifacts/vote_extensions_20261125/mtb_holdout_source_register.json", public_register)
    print(json.dumps({"test_cases":len(test_ids),"test_groups":len(all_groups),"excluded_groups":len(excluded_groups),"excluded_cases":sum(len(v) for v in result_cases.values()),"eligible_cases":len(eligible_ids),"eligible_groups":len(eligible_groups),"plan_sha256":register["frozen_run_plan_sha256"],"input_sha256":input_hash,"gold_sha256":gold_hash},ensure_ascii=False))

if __name__ == "__main__":
    main()
