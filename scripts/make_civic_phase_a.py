"""Freeze the 60-case CIViC development set and three phase-A treatments."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from oncofusion.evaluation import load_evaluation
from oncofusion.experiments import StudyPlan, Treatment, stratified_case_ids
from oncofusion.profiles import available_backend, v1_class_config


def treatment_configs() -> tuple[dict, dict, dict]:
    backend = "langgraph" if available_backend() == "langgraph" else None
    profile = v1_class_config(backend)
    current = json.loads(profile.model_dump_json())

    improved = json.loads(profile.model_dump_json())
    improved["claim_revision_gate"] = True

    single = json.loads(profile.model_dump_json())
    single.update({
        "mode": "single_tools",
        "interaction_protocol": "legacy",
        "specialist_contracts": False,
        "latest_role_board": False,
    })
    # The baseline gets the same task-label contract. The gate affects the Decision
    # instruction and validation, not access to upstream claims, so it can be shared.
    single["claim_revision_gate"] = True
    return current, improved, single


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path,
                        default=Path("data/civicfact-pmidids"))
    parser.add_argument("--sampling-seed", type=int, default=20261109)
    parser.add_argument("--output", type=Path,
                        default=Path("experiments/civic_phase_a_dev60.json"))
    args = parser.parse_args()
    cases, gold = load_evaluation(
        args.dataset / "inputs.jsonl", args.dataset / "_gold" / "labels.jsonl")
    ids = stratified_case_ids(
        cases, gold, task="verification", split="dev", per_label=20,
        max_per_group=1, sampling_seed=args.sampling_seed)
    current, improved, single = treatment_configs()
    plan = StudyPlan(
        name="civic_phase_a_dev60",
        task="verification",
        split="dev",
        seeds=[0],
        case_ids=ids,
        treatments=[
            Treatment(name="current_multi", preset="full", overrides=current),
            Treatment(name="revision_gate_multi", preset="full", overrides=improved),
            Treatment(name="single_tools_shared_evidence", preset="single_tools",
                      overrides=single),
        ],
        reference="current_multi",
        bootstrap_repeats=2000,
    )
    by_id = {record.case_id: record for record in gold}
    labels = Counter(by_id[case_id].label for case_id in ids)
    groups = Counter(by_id[case_id].group_id for case_id in ids)
    assert len(ids) == 60
    assert labels == {"SUPPORTS": 20, "REVISIONS": 20, "NEI": 20}
    assert max(groups.values()) == 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "case_ids": ids,
        "cases": len(ids),
        "labels": dict(sorted(labels.items())),
        "articles": len(groups),
        "executions": len(ids) * 3,
        "max_model_calls": sum(t.config(0).max_calls for t in plan.treatments) * len(ids),
        "sampling_seed": args.sampling_seed,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
