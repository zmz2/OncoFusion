"""Fit source-weighted role reliability and pooled Platt calibration from stored ballots."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from oncofusion.datasets import GoldRecord, read_jsonl
from oncofusion.schemas import Ballot, CaseInput, RunResult, VoteCalibration
from oncofusion.voting import calibrated_confidence


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1 + exp_value)


def fit_platt(
        samples: list[tuple[float, int, float]],
        regularization: float = 1.0,
) -> VoteCalibration:
    """Fit a stable source-weighted Platt curve in standardized logit space."""
    if not samples:
        raise ValueError("no calibration samples")
    if not math.isfinite(regularization) or regularization <= 0:
        raise ValueError("calibration regularization must be positive and finite")
    eps = 1e-6
    raw_rows = [
        (
            math.log(
                min(max(confidence, eps), 1 - eps)
                / (1 - min(max(confidence, eps), 1 - eps))),
            outcome,
            weight,
        )
        for confidence, outcome, weight in samples
    ]
    total_weight = sum(weight for _, _, weight in raw_rows)
    if total_weight <= 0:
        raise ValueError("calibration samples must have positive total weight")
    mean = sum(x * weight for x, _, weight in raw_rows) / total_weight
    variance = (
        sum(weight * (x - mean) ** 2 for x, _, weight in raw_rows)
        / total_weight
    )
    if variance <= 1e-12:
        raise ValueError("confidence has no usable variation")
    scale = math.sqrt(variance)
    rows = [((x - mean) / scale, outcome, weight)
            for x, outcome, weight in raw_rows]

    def objective(a_value: float, b_value: float) -> float:
        total = .5 * regularization * (a_value ** 2 + b_value ** 2)
        for x, outcome, weight in rows:
            value = a_value * x + b_value
            total += weight * (
                max(value, 0) + math.log1p(math.exp(-abs(value)))
                - outcome * value
            )
        return total

    standardized_a, standardized_b = 0.0, 0.0
    current = objective(standardized_a, standardized_b)
    for _ in range(100):
        gradient_a = regularization * standardized_a
        gradient_b = regularization * standardized_b
        h_aa = regularization
        h_ab = 0.0
        h_bb = regularization
        for x, outcome, weight in rows:
            value = standardized_a * x + standardized_b
            probability = _sigmoid(value)
            error = (probability - outcome) * weight
            gradient_a += error * x
            gradient_b += error
            variance = weight * probability * (1 - probability)
            h_aa += variance * x * x
            h_ab += variance * x
            h_bb += variance
        determinant = h_aa * h_bb - h_ab * h_ab
        if determinant <= 1e-12:
            break
        step_a = (h_bb * gradient_a - h_ab * gradient_b) / determinant
        step_b = (-h_ab * gradient_a + h_aa * gradient_b) / determinant
        fraction = 1.0
        while fraction > 1e-8:
            next_a = standardized_a - fraction * step_a
            next_b = standardized_b - fraction * step_b
            candidate = objective(next_a, next_b)
            if candidate <= current:
                break
            fraction *= .5
        if fraction <= 1e-8:
            break
        improvement = current - candidate
        standardized_a, standardized_b = next_a, next_b
        current = candidate
        if improvement < 1e-10:
            break
    return VoteCalibration(
        platt_a=standardized_a / scale,
        platt_b=standardized_b - standardized_a * mean / scale,
        epsilon=eps,
    )


def fit_role_weights(
        ballots: list[Ballot],
        labels: dict[str, str],
        group_by_case: dict[str, str],
        prior: float,
) -> tuple[dict[str, float], float]:
    """Estimate role reliability with one unit of mass per source group."""
    if not ballots:
        raise ValueError("no valid ballots for role weighting")
    group_sizes: dict[str, int] = {}
    for ballot in ballots:
        group = group_by_case[ballot.case_id]
        group_sizes[group] = group_sizes.get(group, 0) + 1
    role_counts: dict[str, dict[str, float]] = defaultdict(
        lambda: {"n": 0.0, "correct": 0.0})
    total_weight = 0.0
    total_correct = 0.0
    for ballot in ballots:
        group = group_by_case[ballot.case_id]
        weight = 1 / group_sizes[group]
        correct = float(ballot.label == labels[ballot.case_id])
        row = role_counts[ballot.role]
        row["n"] += weight
        row["correct"] += weight * correct
        total_weight += weight
        total_correct += weight * correct
    pooled_accuracy = total_correct / total_weight
    weights = {
        role: (row["correct"] + prior * pooled_accuracy)
        / (row["n"] + prior)
        for role, row in sorted(role_counts.items())
    }
    return weights, pooled_accuracy


def calibration_scores(samples, calibration: VoteCalibration) -> dict:
    outcomes = [outcome for _, outcome, _ in samples]
    raw = [confidence for confidence, _, _ in samples]
    calibrated = [calibrated_confidence(confidence, calibration)
                  for confidence, _, _ in samples]
    weights = [weight for _, _, weight in samples]

    def weighted_loss(values, fn):
        return sum(
            weight * fn(probability, outcome)
            for probability, outcome, weight in zip(values, outcomes, weights)
        ) / sum(weights)

    return {
        "raw_brier": weighted_loss(raw, lambda p, y: (p - y) ** 2),
        "calibrated_brier": weighted_loss(calibrated, lambda p, y: (p - y) ** 2),
        "raw_nll": weighted_loss(raw, lambda p, y: -(
            y * math.log(min(max(p, 1e-12), 1 - 1e-12))
            + (1 - y) * math.log(min(max(1 - p, 1e-12), 1 - 1e-12)))),
        "calibrated_nll": weighted_loss(calibrated, lambda p, y: -(
            y * math.log(min(max(p, 1e-12), 1 - 1e-12))
            + (1 - y) * math.log(min(max(1 - p, 1e-12), 1 - 1e-12)))),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--arm", default="p_k_specialists")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prior", type=float, default=20.0)
    parser.add_argument("--regularization", type=float, default=1.0)
    parser.add_argument("--min-groups", type=int, default=10)
    parser.add_argument("--min-ballots", type=int, default=40)
    args = parser.parse_args()
    if args.prior < 0:
        raise ValueError("prior must be nonnegative")

    labels = {
        row.case_id: row
        for row in (
            GoldRecord.model_validate(item)
            for item in read_jsonl(args.dataset / "_gold" / "labels.jsonl")
        )
    }
    cases = {
        case.id: case
        for case in (
            CaseInput.model_validate(row)
            for row in read_jsonl(args.dataset / "inputs.jsonl")
        )
    }
    ballots: list[Ballot] = []
    folder = args.run / args.arm / "0"
    for path in sorted(folder.glob("*.json")):
        if path.name == "summary.json" or path.name.endswith(".failed.json"):
            continue
        result = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        legal_labels = (
            set(cases[result.case_id].verification_labels)
            if cases[result.case_id].task == "verification"
            else set(cases[result.case_id].options)
        )
        ballots.extend(
            ballot for ballot in result.ballots
            if ballot.status == "vote"
            and ballot.confidence is not None
            and ballot.label in legal_labels
        )

    group_members = defaultdict(list)
    for ballot in ballots:
        group_members[labels[ballot.case_id].group_id].append(ballot)
    group_count = len(group_members)
    if group_count < args.min_groups or len(ballots) < args.min_ballots:
        payload = {
            "usable": False,
            "reason": "insufficient independent groups or ballots",
            "groups": group_count,
            "ballots": len(ballots),
        }
    else:
        group_by_case = {
            case_id: row.group_id
            for case_id, row in labels.items()
        }
        weights, pooled_accuracy = fit_role_weights(
            ballots,
            {case_id: row.label for case_id, row in labels.items()},
            group_by_case,
            args.prior,
        )
        samples = []
        for ballot in ballots:
            group_size = len(group_members[labels[ballot.case_id].group_id])
            samples.append((
                float(ballot.confidence),
                int(ballot.label == labels[ballot.case_id].label),
                1 / group_size,
            ))
        outcomes = Counter(outcome for _, outcome, _ in samples)
        if not outcomes.get(0) or not outcomes.get(1):
            payload = {
                "usable": False,
                "reason": "calibration needs both correct and incorrect ballots",
                "groups": group_count,
                "ballots": len(ballots),
            }
        else:
            calibration = fit_platt(samples, args.regularization)
            payload = {
                "usable": True,
                "groups": group_count,
                "ballots": len(ballots),
                "pooled_accuracy": pooled_accuracy,
                "role_weights": weights,
                "calibration": calibration.model_dump(),
                "regularization": args.regularization,
                "scores": calibration_scores(samples, calibration),
                "source": "source-group weighted ballot correctness; gold used only for fitting",
            }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({"output": str(args.out), "usable": payload["usable"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
