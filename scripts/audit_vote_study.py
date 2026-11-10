"""Audit a completed vote-v1 study against its frozen plan and raw files."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

from oncofusion.datasets import GoldRecord, read_jsonl
from oncofusion.engine import implementation_digest
from oncofusion.experiments import StudyPlan
from oncofusion.schemas import RunResult


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    plan = StudyPlan.model_validate_json(
        args.plan.read_text(encoding="utf-8"))
    gold = {
        row.case_id: row
        for row in (
            GoldRecord.model_validate(item)
            for item in read_jsonl(
                args.dataset / "_gold" / "labels.jsonl")
        )
    }
    expected_ids = set(plan.case_ids)
    errors = []
    warnings = []
    providers = set()
    models = set()
    cases = 0
    failed_files = 0
    usage_calls = 0
    trace_started = 0
    trace_usage = 0
    ballots = 0
    max_observed_ballots = 0
    seed_shapes = set()
    role_applicability_cases = 0
    planned_by_case = defaultdict(dict)

    for treatment in plan.treatments:
        for seed in plan.seeds:
            folder = args.run / treatment.name / str(seed)
            present = {
                path.stem
                for path in folder.glob("*.json")
                if not path.name.endswith(".failed.json")
                and path.name != "summary.json"
            }
            missing = sorted(expected_ids - present)
            unexpected = sorted(present - expected_ids)
            failed_files += len(list(folder.glob("*.failed.json")))
            if missing:
                errors.append(
                    f"{treatment.name}/{seed}: missing {len(missing)} cases")
            if unexpected:
                errors.append(
                    f"{treatment.name}/{seed}: unexpected "
                    f"{len(unexpected)} cases")
            for case_id in sorted(expected_ids & present):
                path = folder / (case_id + ".json")
                result = RunResult.model_validate_json(
                    path.read_text(encoding="utf-8"))
                cases += 1
                providers.add(result.provider)
                models.add(result.model)
                expected_config = treatment.config(seed).model_dump(mode="json")
                if result.config.model_dump(mode="json") != expected_config:
                    errors.append(
                        f"{treatment.name}/{case_id}: config differs from plan")
                if result.case_id != case_id:
                    errors.append(
                        f"{path}: result case_id does not match filename")
                if result.vote_result is None:
                    errors.append(f"{path}: missing vote_result")
                    continue
                if result.status == "completed" and result.decision is None:
                    errors.append(f"{path}: completed result has no decision")
                if (
                    result.decision is not None
                    and result.decision.answer != result.vote_result.label
                ):
                    errors.append(f"{path}: decision changed the vote label")
                planned_roles = result.vote_result.planned_roles
                if len(result.ballots) != len(planned_roles):
                    errors.append(f"{path}: ballot count differs from planned roles")
                expected_ballot_roles = (
                    planned_roles
                    if result.vote_result.pool == "specialist"
                    else ["generalist"] * len(planned_roles)
                )
                if [ballot.role for ballot in result.ballots] != expected_ballot_roles:
                    errors.append(f"{path}: ballot roles differ from planned roles")
                ballots += len(result.ballots)
                max_observed_ballots = max(
                    max_observed_ballots, len(result.ballots))
                seed_shapes.add(tuple(
                    ballot.seed - result.config.seed
                    for ballot in result.ballots))
                if any(not ballot.input_fingerprint for ballot in result.ballots):
                    errors.append(f"{path}: ballot input fingerprint missing")
                started = [
                    event for event in result.trace
                    if event.kind == "agent_started"
                ]
                usage_events = [
                    event for event in result.trace
                    if event.kind == "model_usage"
                ]
                trace_started += len(started)
                trace_usage += len(usage_events)
                usage_calls += result.usage.calls
                if len(started) != result.usage.calls:
                    errors.append(
                        f"{path}: agent_started count differs from usage calls")
                run_started = next(
                    (event for event in result.trace
                     if event.kind == "run_started"),
                    None,
                )
                if (
                    run_started is None
                    or "role_applicability" not in run_started.details
                ):
                    errors.append(f"{path}: role applicability was not recorded")
                else:
                    role_applicability_cases += 1
                planned_by_case[case_id][treatment.name] = (
                    result.vote_result.planned_votes)

    generalist_arm = next(
        (name for name in {
            treatment.name for treatment in plan.treatments
        } if name.startswith("g_k")),
        None,
    )
    professional_arm = next(
        (name for name in {
            treatment.name for treatment in plan.treatments
        } if name.startswith("p_k")),
        None,
    )
    if generalist_arm and professional_arm:
        mismatched_k = [
            case_id for case_id, values in planned_by_case.items()
            if values.get(generalist_arm) != values.get(professional_arm)
        ]
        if mismatched_k:
            errors.append(
                f"{len(mismatched_k)} cases use different K for "
                f"{generalist_arm} and {professional_arm}")

    provider_logs = sorted(args.run.glob("provider_calls*.jsonl"))
    provider_counts = {
        path.name: sum(1 for _ in path.open(encoding="utf-8"))
        for path in provider_logs
    }
    provider_lines = (
        sum(provider_counts.values()) if provider_counts else None)
    concurrency_path = args.run / "concurrency.json"
    concurrency = (
        json.loads(concurrency_path.read_text(encoding="utf-8"))
        if concurrency_path.exists() else None
    )
    if provider_lines != usage_calls:
        message = (
            f"provider log lines {provider_lines} != usage calls {usage_calls}")
        if (args.run / "RESUME_SCHEDULING.json").exists():
            warnings.append(
                message + "; retained interrupted-attempt calls are documented")
        else:
            errors.append(message)
    if concurrency is not None and concurrency.get("peak_in_flight", 0) > 20:
        errors.append("scheduler peak exceeds 20")
    identity_path = args.run / "identity.json"
    study_identity = (
        json.loads(identity_path.read_text(encoding="utf-8")).get("identity")
        if identity_path.exists() else None
    )
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        commit = None
        status = []
    payload = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "run": str(args.run),
        "plan": str(args.plan),
        "plan_sha256": sha256(args.plan),
        "dataset": str(args.dataset),
        "dataset_fingerprints": {
            "inputs_sha256": sha256(args.dataset / "inputs.jsonl"),
            "labels_sha256": sha256(
                args.dataset / "_gold" / "labels.jsonl"),
        },
        "git_commit": commit,
        "git_dirty_files": status,
        "expected_cases_per_execution": len(plan.case_ids),
        "executions": len(plan.treatments) * len(plan.seeds),
        "result_files_checked": cases,
        "expected_result_files": (
            len(plan.case_ids) * len(plan.treatments) * len(plan.seeds)),
        "failed_files": failed_files,
        "providers": sorted(providers),
        "models": sorted(models),
        "implementation_digest": implementation_digest(),
        "study_identity": study_identity,
        "usage_calls": usage_calls,
        "provider_log_lines": provider_lines,
        "provider_log_files": provider_counts,
        "trace_agent_started": trace_started,
        "trace_model_usage": trace_usage,
        "ballots": ballots,
        "max_ballots_per_case": max_observed_ballots,
        "seed_offsets": sorted(seed_shapes),
        "role_applicability_cases": role_applicability_cases,
        "concurrency": concurrency,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "ok": payload["ok"],
        "errors": len(errors),
        "warnings": len(warnings),
        "out": str(args.out),
    }))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
