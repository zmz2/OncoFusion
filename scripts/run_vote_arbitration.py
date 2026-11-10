"""Run one bounded V3 arbitration on saved low-consensus vote pools."""
from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from oncofusion.datasets import GoldRecord, read_jsonl
from oncofusion.evidence import fragment_documents, visible_case
from oncofusion.providers import provider_from_env
from oncofusion.schemas import CaseInput, RunResult, VoteArbitration
from oncofusion.vote_runner import VoteEngine, build_vote_decision
from oncofusion.voting import aggregate_ballots, arbitration_required


def labels_for(case: CaseInput) -> list[str]:
    return (
        list(case.verification_labels)
        if case.task == "verification"
        else sorted(case.options)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--arm", default="p_k_specialists")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--execution-cap", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-share", type=float, default=.75)
    parser.add_argument("--min-margin", type=float, default=.25)
    args = parser.parse_args()
    if args.execution_cap < 1:
        raise ValueError("execution-cap must be positive")

    cases = {
        case.id: case
        for case in (
            CaseInput.model_validate(row)
            for row in read_jsonl(args.dataset / "inputs.jsonl")
        )
    }
    gold = {
        row.case_id: row.label
        for row in (
            GoldRecord.model_validate(item)
            for item in read_jsonl(args.dataset / "_gold" / "labels.jsonl")
        )
    }
    source = args.run / args.arm / "0"
    all_results = []
    results = []
    for path in sorted(source.glob("*.json")):
        if path.name == "summary.json" or path.name.endswith(".failed.json"):
            continue
        result = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        if result.vote_result is None or not result.ballots:
            continue
        case = cases[result.case_id]
        labels = labels_for(case)
        initial = aggregate_ballots(
            case_id=case.id,
            ballots=result.ballots,
            labels=labels,
            planned_roles=result.vote_result.planned_roles,
            pool=result.vote_result.pool,
            rule="v0",
        )
        item = (path, case, result, initial)
        all_results.append(item)
        if initial.completion_status != "failed" and arbitration_required(
                initial, args.min_share, args.min_margin):
            results.append(item)
    if args.dry_run:
        print(json.dumps({
            "triggered": len(results),
            "max_extra_calls": len(results) * 3,
            "output": str(args.out),
        }))
        return 0
    if len(results) > args.execution_cap:
        raise ValueError(
            f"{len(results)} triggered cases exceed execution cap {args.execution_cap}")
    provider = provider_from_env()
    if not provider.simulated and not args.allow_remote:
        raise ValueError("real V3 arbitration requires --allow-remote")
    if any(result.model != provider.model for _, _, result, _ in results):
        raise ValueError("saved ballots and current provider use different models")

    engine = VoteEngine(provider)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for path, case, result, initial in results:
        config = result.config.model_copy(update={
            "vote_rule": "v3",
            "vote_arbitration_min_share": args.min_share,
            "vote_arbitration_margin": args.min_margin,
            "max_calls": result.config.max_calls + 3,
        })
        visible = visible_case(case)
        query = " ".join(filter(None, [
            visible.question,
            *[str(value) for value in visible.entities.model_dump().values() if value],
        ]))
        evidence, evidence_index, _ = fragment_documents(
            visible.documents,
            config.fragment_chars,
            config.max_fragments_per_document,
            query,
            config.fragment_budget,
            role="decision",
        )
        usage = result.usage.model_copy(deep=True)
        trace = list(result.trace)
        lock = threading.RLock()
        arbitration = engine._adjudicate(
            visible,
            labels_for(visible),
            result.ballots,
            evidence,
            evidence_index,
            config,
            initial.label,
            usage,
            trace,
            lock,
            None,
        )
        vote = aggregate_ballots(
            case_id=visible.id,
            ballots=result.ballots,
            labels=labels_for(visible),
            planned_roles=result.vote_result.planned_roles,
            pool=result.vote_result.pool,
            rule="v3",
            arbitration=arbitration,
            min_share=args.min_share,
            min_margin=args.min_margin,
        )
        decision = build_vote_decision(
            visible, config, vote, result.ballots, evidence_index)
        status = "failed" if decision is None else "completed"
        updated = result.model_copy(update={
            "config": config,
            "decision": decision,
            "usage": usage,
            "trace": trace,
            "status": status,
            "vote_result": vote,
            "duration_seconds": (
                result.duration_seconds
                + sum(
                    event.details.get("seconds", 0)
                    for event in trace[len(result.trace):]
                    if event.kind == "model_usage")
            ),
        })
        target = args.out / args.arm / "0" / (case.id + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        manifest.append({
            "case_id": case.id,
            "initial_label": initial.label,
            "final_label": vote.label,
            "arbitration_status": arbitration.status,
            "arbitration_changed": arbitration.final_label != arbitration.initial_label,
            "extra_calls": usage.calls - result.usage.calls,
            "extra_input_tokens": usage.input_tokens - result.usage.input_tokens,
            "extra_output_tokens": usage.output_tokens - result.usage.output_tokens,
            "extra_http_attempts": usage.http_attempts - result.usage.http_attempts,
            "initial_correct": initial.label == gold[case.id],
            "final_correct": vote.label == gold[case.id],
        })
    triggered_ids = {case.id for _, case, _, _ in results}
    copied_v0 = 0
    for path, case, result, initial in all_results:
        if case.id in triggered_ids:
            continue
        config = result.config.model_copy(update={
            "vote_rule": "v3",
            "vote_arbitration_min_share": args.min_share,
            "vote_arbitration_margin": args.min_margin,
        })
        visible = visible_case(case)
        query = " ".join(filter(None, [
            visible.question,
            *[str(value) for value in visible.entities.model_dump().values()
              if value],
        ]))
        evidence, evidence_index, _ = fragment_documents(
            visible.documents,
            config.fragment_chars,
            config.max_fragments_per_document,
            query,
            config.fragment_budget,
            role="decision",
        )
        arbitration = VoteArbitration(
            triggered=False,
            status="not_triggered",
            initial_label=initial.label,
            final_label=initial.label,
        )
        vote = aggregate_ballots(
            case_id=visible.id,
            ballots=result.ballots,
            labels=labels_for(visible),
            planned_roles=result.vote_result.planned_roles,
            pool=result.vote_result.pool,
            rule="v3",
            arbitration=arbitration,
            min_share=args.min_share,
            min_margin=args.min_margin,
        )
        decision = build_vote_decision(
            visible, config, vote, result.ballots, evidence_index)
        updated = result.model_copy(update={
            "config": config,
            "decision": decision,
            "status": "failed" if decision is None else "completed",
            "vote_result": vote,
        })
        target = args.out / args.arm / "0" / (case.id + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        copied_v0 += 1
    scheduler = getattr(provider, "scheduler", None)
    summary = {
            "source_run": str(args.run),
            "arm": args.arm,
            "total_cases": len(all_results),
            "triggered": len(results),
            "v0_cases_copied": copied_v0,
            "min_share": args.min_share,
            "min_margin": args.min_margin,
            "initial_correct": sum(item["initial_correct"] for item in manifest),
            "final_correct": sum(item["final_correct"] for item in manifest),
            "changed": sum(item["arbitration_changed"] for item in manifest),
            "extra_calls": sum(item["extra_calls"] for item in manifest),
            "extra_input_tokens": sum(
                item["extra_input_tokens"] for item in manifest),
            "extra_output_tokens": sum(
                item["extra_output_tokens"] for item in manifest),
            "concurrency": scheduler.snapshot() if scheduler is not None else None,
            "cases": manifest,
        }
    (args.out / "arbitration.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "triggered": len(results),
        "completed": sum(item["arbitration_status"] == "completed" for item in manifest),
        "changed": sum(item["arbitration_changed"] for item in manifest),
        "initial_correct": summary["initial_correct"],
        "final_correct": summary["final_correct"],
        "output": str(args.out),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
