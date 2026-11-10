"""Analyze stored vote-v1 ballots under V0, V1, V2 and raw-confidence aggregation."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from oncofusion.datasets import GoldRecord, read_jsonl
from oncofusion.evaluation import classification_metrics
from oncofusion.schemas import Ballot, CaseInput, RunResult, VoteCalibration
from oncofusion.voting import aggregate_ballots, calibrated_confidence

try:
    from scripts.fit_vote_calibration import fit_platt, fit_role_weights
except ModuleNotFoundError:
    from fit_vote_calibration import fit_platt, fit_role_weights


def read_rows(run: Path, arm: str, labels: dict[str, str]):
    folder = run / arm / "0"
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.glob("*.json")):
        if path.name == "summary.json" or path.name.endswith(".failed.json"):
            continue
        result = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        if result.case_id not in labels:
            continue
        rows.append({
            "case_id": result.case_id,
            "gold": labels[result.case_id],
            "result": result,
        })
    return rows


def score_rule(rows, labels, rule, weights, calibration):
    predictions = []
    vote_results = []
    for row in rows:
        result = row["result"]
        vote = aggregate_ballots(
            case_id=result.case_id,
            ballots=result.ballots,
            labels=labels,
            planned_roles=result.vote_result.planned_roles if result.vote_result else [],
            pool=result.vote_result.pool if result.vote_result else result.config.vote_pool,
            rule=rule,
            role_weights=weights,
            calibration=calibration,
        )
        predictions.append(
            vote.label if vote.completion_status != "failed" and vote.label else "__FAILED__")
        vote_results.append(vote)
    metrics = classification_metrics(
        [row["gold"] for row in rows], predictions, labels)
    metrics.update({
        "full_completion": sum(vote.completion_status == "full" for vote in vote_results),
        "degraded_completion": sum(
            vote.completion_status == "degraded" for vote in vote_results),
        "failed": sum(vote.completion_status == "failed" for vote in vote_results),
        "ties": sum(vote.tied for vote in vote_results),
        "mean_valid_votes": statistics.mean(
            vote.valid_votes for vote in vote_results) if vote_results else None,
    })
    return {
        "metrics": metrics,
        "predictions": predictions,
        "votes": [vote.model_dump(mode="json") for vote in vote_results],
    }


def score_crossfit(
        rows,
        labels,
        rule,
        group_by_case,
        prior,
        regularization,
):
    """Fit V1/V2 on all source groups except the group being scored."""
    all_roles = sorted({
        ballot.role
        for row in rows
        for ballot in row["result"].ballots
        if ballot.status == "vote" and ballot.label in labels
    })
    groups = sorted({group_by_case[row["case_id"]] for row in rows})
    if len(groups) < 2:
        raise ValueError("cross-fitting requires at least two source groups")
    predictions = []
    vote_results = []
    folds = {}
    for fold in groups:
        training_rows = [
            row for row in rows if group_by_case[row["case_id"]] != fold
        ]
        testing_rows = [
            row for row in rows if group_by_case[row["case_id"]] == fold
        ]
        training_ballots = [
            ballot
            for row in training_rows
            for ballot in row["result"].ballots
            if ballot.status == "vote" and ballot.label in labels
        ]
        role_weights, pooled_accuracy = fit_role_weights(
            training_ballots,
            {row["case_id"]: row["gold"] for row in training_rows},
            group_by_case,
            prior,
        )
        role_weights = {
            role: role_weights.get(role, pooled_accuracy)
            for role in all_roles
        }
        group_sizes = Counter(
            group_by_case[ballot.case_id] for ballot in training_ballots)
        labels_by_case = {
            row["case_id"]: row["gold"] for row in training_rows
        }
        samples = [
            (
                float(ballot.confidence),
                int(ballot.label == labels_by_case[ballot.case_id]),
                1 / group_sizes[group_by_case[ballot.case_id]],
            )
            for ballot in training_ballots
            if ballot.confidence is not None
        ]
        calibration = None
        if {outcome for _, outcome, _ in samples} == {0, 1}:
            calibration = fit_platt(samples, regularization)
        if rule == "v2" and calibration is None:
            raise ValueError(
                f"cross-fit calibration unavailable for held-out group {fold}")
        for row in testing_rows:
            result = row["result"]
            vote = aggregate_ballots(
                case_id=result.case_id,
                ballots=result.ballots,
                labels=labels,
                planned_roles=(
                    result.vote_result.planned_roles
                    if result.vote_result else []),
                pool=(
                    result.vote_result.pool
                    if result.vote_result else result.config.vote_pool),
                rule=rule,
                role_weights=role_weights,
                calibration=calibration,
            )
            predictions.append(
                vote.label
                if vote.completion_status != "failed" and vote.label
                else "__FAILED__")
            vote_results.append(vote)
        folds[fold] = {
            "test_cases": len(testing_rows),
            "training_ballots": len(training_ballots),
            "pooled_accuracy": pooled_accuracy,
            "role_weights": role_weights,
            "calibration": (
                calibration.model_dump(mode="json")
                if calibration is not None else None),
        }
    metrics = classification_metrics(
        [row["gold"] for row in rows], predictions, labels)
    metrics.update({
        "full_completion": sum(
            vote.completion_status == "full" for vote in vote_results),
        "degraded_completion": sum(
            vote.completion_status == "degraded" for vote in vote_results),
        "failed": sum(
            vote.completion_status == "failed" for vote in vote_results),
        "ties": sum(vote.tied for vote in vote_results),
        "mean_valid_votes": statistics.mean(
            vote.valid_votes for vote in vote_results) if vote_results else None,
    })
    return {
        "metrics": metrics,
        "predictions": predictions,
        "votes": [vote.model_dump(mode="json") for vote in vote_results],
        "folds": folds,
    }


def calibration_metrics(ballots: list[Ballot], labels: dict[str, str],
                        calibration: VoteCalibration | None) -> dict:
    raw_rows = []
    for ballot in ballots:
        case_id = ballot.case_id
        if case_id not in labels or ballot.status != "vote" or ballot.confidence is None:
            continue
        raw_rows.append((float(ballot.confidence), int(ballot.label == labels[case_id])))
    if not raw_rows:
        return {
            "n": 0,
            "raw_confidence": None,
            "calibrated_confidence": None,
        }

    def summarize(values):
        eps = 1e-6
        probs = [min(max(value, eps), 1 - eps) for value, _ in values]
        outcomes = [outcome for _, outcome in values]
        brier = statistics.mean(
            (probability - outcome) ** 2
            for probability, outcome in zip(probs, outcomes))
        nll = -statistics.mean(
            outcome * math.log(probability)
            + (1 - outcome) * math.log(1 - probability)
            for probability, outcome in zip(probs, outcomes))
        positives = [p for p, y in values if y]
        negatives = [p for p, y in values if not y]
        if positives and negatives:
            wins = sum(
                1 if positive > negative else .5 if positive == negative else 0
                for positive in positives for negative in negatives)
            auroc = wins / (len(positives) * len(negatives))
        else:
            auroc = None
        ordered = sorted(zip(probs, outcomes))
        bins = []
        size = max(1, math.ceil(len(ordered) / 5))
        for start in range(0, len(ordered), size):
            group = ordered[start:start + size]
            bins.append({
                "n": len(group),
                "mean_confidence": statistics.mean(p for p, _ in group),
                "accuracy": statistics.mean(y for _, y in group),
            })
        return {
            "n": len(values),
            "brier": brier,
            "nll": nll,
            "auroc": auroc,
            "bins": bins,
        }

    result = {
        "n": len(raw_rows),
        "raw_confidence": summarize(raw_rows),
        "calibrated_confidence": None,
    }
    if calibration is not None:
        result["calibrated_confidence"] = summarize([
            (calibrated_confidence(confidence, calibration), outcome)
            for confidence, outcome in raw_rows
        ])
    return result


def disagreement_metrics(rows, labels: list[str]) -> dict:
    pairs = defaultdict(lambda: {"both_valid": 0, "both_wrong": 0, "disagree": 0})
    per_role = defaultdict(lambda: {"valid": 0, "correct": 0})
    distinct_label_counts = Counter()
    unanimous = 0
    oracle_union = 0
    for row in rows:
        ballots = [
            ballot for ballot in row["result"].ballots
            if ballot.status == "vote" and ballot.label in labels
        ]
        distinct_label_counts[len({ballot.label for ballot in ballots})] += 1
        unanimous += len({ballot.label for ballot in ballots}) == 1
        oracle_union += any(ballot.label == row["gold"] for ballot in ballots)
        for ballot in ballots:
            member = per_role[ballot.role]
            member["valid"] += 1
            member["correct"] += ballot.label == row["gold"]
        for left_index, left in enumerate(ballots):
            for right in ballots[left_index + 1:]:
                if left.role == right.role:
                    continue
                pair = "|".join(sorted((left.role, right.role)))
                item = pairs[pair]
                item["both_valid"] += 1
                item["disagree"] += left.label != right.label
                item["both_wrong"] += (
                    left.label != row["gold"] and right.label != row["gold"])
    return {
        "cases": len(rows),
        "distinct_label_counts": dict(sorted(distinct_label_counts.items())),
        "unanimous_cases": unanimous,
        "oracle_union_cases": oracle_union,
        "member_accuracy": {
            role: {
                **item,
                "accuracy": item["correct"] / item["valid"]
                if item["valid"] else None,
            }
            for role, item in sorted(per_role.items())
        },
        "pairwise": dict(sorted(pairs.items())),
    }


def paired_vs_reference(rows, reference_rows, predictions):
    reference = {row["case_id"]: row["result"].decision.answer
                 for row in reference_rows
                 if row["result"].decision is not None}
    gold = {row["case_id"]: row["gold"] for row in rows}
    fixed = broke = 0
    for row, prediction in zip(rows, predictions):
        case_id = row["case_id"]
        if case_id not in reference:
            continue
        reference_correct = reference[case_id] == gold[case_id]
        candidate_correct = prediction == gold[case_id]
        fixed += not reference_correct and candidate_correct
        broke += reference_correct and not candidate_correct
    return {"fixed": fixed, "broke": broke, "net": fixed - broke}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--arm", default="p_k_specialists")
    parser.add_argument("--reference-arm", default="b0_common_single")
    parser.add_argument("--weights", type=Path,
                        help="JSON containing a role_weights object")
    parser.add_argument("--calibration", type=Path,
                        help="JSON containing platt_a and platt_b")
    parser.add_argument("--crossfit-groups", action="store_true",
                        help="Fit V1/V2 separately for every held-out source group")
    parser.add_argument("--prior", type=float, default=20.0)
    parser.add_argument("--regularization", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.crossfit_groups and (args.weights or args.calibration):
        raise ValueError("crossfit-groups cannot be combined with global weights")
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
    rows = read_rows(args.run, args.arm, gold)
    if not rows:
        raise ValueError("no saved vote results found for arm " + args.arm)
    reference_rows = read_rows(args.run, args.reference_arm, gold)
    weights = None
    if args.weights is not None:
        payload = json.loads(args.weights.read_text())
        weights = payload.get("role_weights", payload)
    calibration = None
    if args.calibration is not None:
        payload = json.loads(args.calibration.read_text())
        if payload.get("usable") is False:
            raise ValueError("calibration is not usable: " + payload.get("reason", "unknown"))
        calibration = VoteCalibration.model_validate(
            payload.get("calibration", payload))

    rules = ["v0", "c_raw"]
    analyzed = {}
    if args.crossfit_groups:
        analyzed = {
            rule: score_rule(rows, labels, rule, None, None)
            for rule in rules
        }
        group_by_case = {
            row.case_id: row.group_id for row in gold_rows
        }
        analyzed["v1"] = score_crossfit(
            rows,
            labels,
            "v1",
            group_by_case,
            args.prior,
            args.regularization,
        )
        try:
            analyzed["v2"] = score_crossfit(
                rows,
                labels,
                "v2",
                group_by_case,
                args.prior,
                args.regularization,
            )
        except ValueError as exc:
            calibration_error = str(exc)
        else:
            calibration_error = None
        rules.extend(analyzed)
    else:
        if weights:
            rules.append("v1")
        if calibration:
            rules.append("v2")
        analyzed = {
            rule: score_rule(rows, labels, rule, weights, calibration)
            for rule in rules
        }
        calibration_error = None
    for rule, result in analyzed.items():
        if reference_rows:
            result["paired_vs_reference"] = paired_vs_reference(
                rows, reference_rows, result["predictions"])
    all_ballots = [
        ballot for row in rows for ballot in row["result"].ballots
    ]
    output = {
        "task": task,
        "arm": args.arm,
        "reference_arm": args.reference_arm,
        "cases": len(rows),
        "labels": labels,
        "analysis_mode": (
            "leave-one-source-group-out" if args.crossfit_groups else "fixed"),
        "crossfit_prior": args.prior if args.crossfit_groups else None,
        "crossfit_regularization": (
            args.regularization if args.crossfit_groups else None),
        "calibration_error": calibration_error,
        "rules": {
            rule: {
                key: value
                for key, value in result.items()
                if key not in ("votes",)
            }
            for rule, result in analyzed.items()
        },
        "disagreement": disagreement_metrics(rows, labels),
        "calibration": calibration_metrics(all_ballots, gold, calibration),
        "source": "stored ballots only; V0/V1/V2/C-raw reuse the same generation calls",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "vote_analysis.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    lines = [
        "# vote-v1 analysis",
        "",
        f"- task: {task}",
        f"- arm: {args.arm}",
        f"- cases: {len(rows)}",
        f"- analysis mode: {output['analysis_mode']}",
        "",
        "| rule | Accuracy | Macro-F1 | full | degraded | failed | ties | fixed vs B0 | broke vs B0 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rule, result in analyzed.items():
        metrics = result["metrics"]
        paired = result.get("paired_vs_reference", {})
        lines.append(
            f"| {rule} | {metrics['accuracy']:.4f} | {metrics['macro_f1']:.4f} | "
            f"{metrics['full_completion']} | {metrics['degraded_completion']} | "
            f"{metrics['failed']} | {metrics['ties']} | {paired.get('fixed', 0)} | "
            f"{paired.get('broke', 0)} |")
    lines += [
        "",
        "V1 and V2 are omitted when their required calibration was not supplied.",
        "With --crossfit-groups, each source group is scored with weights and "
        "calibration fitted without that group.",
        "C-raw is a diagnostic only and is not a primary rule.",
    ]
    (args.out / "VOTE_ANALYSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "json": str(args.out / "vote_analysis.json"),
        "markdown": str(args.out / "VOTE_ANALYSIS.md"),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
