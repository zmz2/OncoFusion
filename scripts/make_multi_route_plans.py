"""Freeze the ten-treatment screening plans and report exact execution budgets."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from oncofusion.datasets import GoldRecord
from oncofusion.evaluation import load_evaluation
from oncofusion.experiments import StudyPlan, Treatment, stratified_case_ids


ROUTES = (
    "b0_single",
    "b1_iterative",
    "a1_medagents",
    "a2_mac",
    "a3_mdagents",
    "a4_mdteamgpt",
    "a5_medla",
    "a6_medagentpro",
    "a7_medea",
)


def experiment_config(route: str) -> dict:
    return {
        "mode": "single_tools",
        "execution_model": "route",
        "route": route,
        "route_rounds": 2 if route == "b1_iterative" else 1,
        "route_workers": 13,
        "ablations": {
            "variant_normalization": True,
            "disease_matching": True,
            "drug_polarity": True,
            "retrieval_reranking": True,
            "timeline_structure": True,
            "external_verification": True,
            "source_deduplication": True,
            "structured_board": True,
            "targeted_requery": False,
        },
        "delegated_roles": [],
        "routing": "fixed",
        "workflow_backend": "langgraph",
        "evidence_first": True,
        "specialist_contracts": False,
        "latest_role_board": False,
        "max_calls": 15,
        "max_tool_calls": 12,
        "max_total_tokens": 260000,
        "max_output_tokens": 5000,
        "route_node_output_tokens": 1500,
        "citation_mode": "fragment",
        "fragment_chars": 600,
        "max_fragments_per_document": 8,
        "fragment_budget": 12000,
        "findings_limit": 3,
        "interaction_protocol": "legacy" if route == "b0_single" else "claims-v1",
        "schema_retries": 2,
        "top_k": 6,
        "candidate_k": 20,
        "seed": 0,
        "temperature": 0.0,
        "claim_revision_gate": False,
    }


def b2_config() -> dict:
    return {
        "mode": "multi",
        "execution_model": "engine",
        "route": "",
        "ablations": {
            "variant_normalization": True,
            "disease_matching": True,
            "drug_polarity": True,
            "retrieval_reranking": True,
            "timeline_structure": True,
            "external_verification": True,
            "source_deduplication": True,
            "structured_board": True,
            "targeted_requery": False,
        },
        "delegated_roles": [],
        "routing": "fixed",
        "workflow_backend": "langgraph",
        "evidence_first": True,
        "specialist_contracts": True,
        "latest_role_board": True,
        "max_calls": 15,
        "max_tool_calls": 12,
        "max_total_tokens": 260000,
        "max_output_tokens": 5000,
        "route_node_output_tokens": 1500,
        "citation_mode": "fragment",
        "fragment_chars": 600,
        "max_fragments_per_document": 8,
        "fragment_budget": 12000,
        "findings_limit": 3,
        "interaction_protocol": "claims-v1",
        "schema_retries": 2,
        "top_k": 6,
        "candidate_k": 20,
        "seed": 0,
        "temperature": 0.0,
        "claim_revision_gate": True,
    }


def b0_config(task: str) -> dict:
    """The current strong single-agent baseline, kept as an Engine treatment."""
    config = experiment_config("b0_single")
    config.update({
        "execution_model": "engine",
        "route": "",
        "max_calls": 12,
        "interaction_protocol": "legacy",
        "claim_revision_gate": task == "verification",
    })
    return config


def treatments(task: str) -> list[Treatment]:
    rows = [Treatment(name="b0_single", preset="single_tools",
                      overrides=b0_config(task))]
    for route in ROUTES[1:]:
        rows.append(Treatment(
            name=route, preset="single_tools" if route == "b1_iterative" else "full",
            overrides=experiment_config(route)))
    config = b2_config()
    config["claim_revision_gate"] = task == "verification"
    rows.append(Treatment(name="b2_revision_gate", preset="full",
                          overrides=config))
    return rows


def prior_debug_groups(civic_groups: set[str]) -> dict[str, list[str]]:
    """List CIViC dev articles already run in earlier development/debug studies."""
    _, gold = load_evaluation(
        Path("data/civicfact-pmidids/inputs.jsonl"),
        Path("data/civicfact-pmidids/_gold/labels.jsonl"))
    by_id = {row.case_id: row for row in gold}
    uses: dict[str, list[str]] = defaultdict(list)
    for identity_file in sorted(Path("results/v1").glob("civic_*/run/identity.json")):
        study = identity_file.parent.parent.name
        payload = json.loads(identity_file.read_text())
        case_ids = payload.get("case_ids") or (payload.get("plan") or {}).get("case_ids") or []
        for case_id in case_ids:
            group = by_id[case_id].group_id
            if group in civic_groups and study not in uses[group]:
                uses[group].append(study)
    return dict(uses)


def assert_disjoint_from_prior_debug(civic_groups: set[str]) -> dict[str, list[str]]:
    prior_plan = json.loads((Path("experiments") / "civic_test150_gate_v2_20261109.json").read_text())
    cases, gold = load_evaluation(
        Path("data/civicfact-pmidids/inputs.jsonl"),
        Path("data/civicfact-pmidids/_gold/labels.jsonl"))
    by_id: dict[str, GoldRecord] = {row.case_id: row for row in gold}
    prior_groups = {by_id[case_id].group_id for case_id in prior_plan["case_ids"]}
    overlap = civic_groups & prior_groups
    if overlap:
        raise ValueError("CIViC dev articles overlap the prior 150-case debug/test set: "
                         + ", ".join(sorted(overlap)))
    return prior_debug_groups(civic_groups)


def civic_ids(dataset: Path) -> list[str]:
    cases, gold = load_evaluation(dataset / "inputs.jsonl",
                                  dataset / "_gold" / "labels.jsonl")
    return stratified_case_ids(
        cases, gold, task="verification", split="dev",
        per_label=20, max_per_group=1, sampling_seed=20261109)


def mtb_ids(dataset: Path) -> tuple[list[str], dict[str, str]]:
    cases, gold = load_evaluation(dataset / "inputs.jsonl",
                                  dataset / "_gold" / "labels.jsonl")
    labels = {row.case_id: row for row in gold}
    ids = sorted(c.id for c in cases
                 if c.task == "mcq" and labels[c.id].split == "dev")
    return ids, {row.case_id: row.group_id for row in gold}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mtb", type=Path, default=Path("data/mtbbench"))
    parser.add_argument("--civic", type=Path, default=Path("data/civicfact-pmidids"))
    parser.add_argument("--out-dir", type=Path, default=Path("experiments"))
    args = parser.parse_args()
    outputs = []
    for task, dataset in (("mcq", args.mtb), ("verification", args.civic)):
        if task == "mcq":
            ids, groups = mtb_ids(dataset)
        else:
            ids = civic_ids(dataset)
            _, civic_gold = load_evaluation(
                dataset / "inputs.jsonl", dataset / "_gold" / "labels.jsonl")
            groups = {row.case_id: row.group_id for row in civic_gold}
            civic_groups = {groups[case_id] for case_id in ids}
            debug_uses = assert_disjoint_from_prior_debug(civic_groups)
        plan = StudyPlan(
            name=f"civic_multi_route_{task}" if task == "verification"
            else "mtb_multi_route_mcq",
            task=task, split="dev", seeds=[0],
            case_ids=ids, treatments=treatments(task),
            reference="b0_single", bootstrap_repeats=2000)
        path = args.out_dir / (
            "civic_multi_route_dev60_20261109.json" if task == "verification"
            else "mtb_multi_route_dev43_20261109.json")
        path.write_text(plan.model_dump_json(indent=2) + "\n")
        smoke = plan.model_copy(update={
            "name": plan.name + "_smoke",
            "case_ids": ids[:2],
        })
        smoke_path = args.out_dir / (
            "civic_multi_route_smoke2_20261109.json" if task == "verification"
            else "mtb_multi_route_smoke2_20261109.json")
        smoke_path.write_text(smoke.model_dump_json(indent=2) + "\n")
        summary = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "smoke_path": str(smoke_path),
            "smoke_sha256": hashlib.sha256(smoke_path.read_bytes()).hexdigest(),
            "task": task,
            "cases": len(ids),
            "groups": len({groups[cid] for cid in ids}),
            "treatments": len(plan.treatments),
            "executions": len(ids) * len(plan.treatments),
            "max_model_calls": len(ids) * sum(
                t.config(0).max_calls for t in plan.treatments),
        }
        if task == "verification":
            prior_debug = {
                group: studies for group, studies in debug_uses.items()
                if any(not study.startswith("civic_multi_route_smoke") for study in studies)}
            smoke_only = {
                group: studies for group, studies in debug_uses.items()
                if all(study.startswith("civic_multi_route_smoke") for study in studies)}
            summary["debug_group_ids"] = sorted(prior_debug)
            summary["debug_group_studies"] = {
                group: studies for group, studies in sorted(prior_debug.items())}
            summary["smoke_only_group_studies"] = {
                group: studies for group, studies in sorted(smoke_only.items())}
            summary["unused_group_count"] = len(civic_groups) - len(prior_debug)
        outputs.append(summary)
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
