import math

from oncofusion.schemas import Ballot
from scripts.fit_vote_calibration import (
    calibration_scores,
    fit_platt,
    fit_role_weights,
)


def test_platt_fit_is_finite_and_group_metrics_are_weighted():
    samples = [
        (.9, 1, .5),
        (.8, 0, .5),
        (.4, 1, .25),
        (.3, 0, .25),
        (.7, 1, .25),
    ]
    calibration = fit_platt(samples)
    assert math.isfinite(calibration.platt_a)
    assert math.isfinite(calibration.platt_b)
    scores = calibration_scores(samples, calibration)
    assert set(scores) == {
        "raw_brier", "calibrated_brier", "raw_nll", "calibrated_nll"}
    assert all(math.isfinite(value) for value in scores.values())


def test_platt_is_stable_when_high_confidence_separates_the_training_outcomes():
    samples = [
        (.8, 0, 1),
        (.85, 0, 1),
        (.9, 0, 1),
        (.95, 1, 1),
        (1.0, 1, 1),
    ]
    calibration = fit_platt(samples, regularization=1.0)
    assert math.isfinite(calibration.platt_a)
    assert math.isfinite(calibration.platt_b)
    assert abs(calibration.platt_a) < 100


def test_role_reliability_counts_each_source_group_once():
    ballots = [
        Ballot(
            ballot_id=f"a-{index}",
            case_id=f"a-{index}",
            role="literature",
            status="vote",
            label="SUPPORTS",
        )
        for index in range(4)
    ] + [
        Ballot(
            ballot_id="b",
            case_id="b",
            role="genomics",
            status="vote",
            label="REVISIONS",
        )
    ]
    labels = {f"a-{index}": "SUPPORTS" for index in range(4)}
    labels["b"] = "SUPPORTS"
    groups = {f"a-{index}": "patient-a" for index in range(4)}
    groups["b"] = "patient-b"
    _, pooled_accuracy = fit_role_weights(
        ballots, labels, groups, prior=0)
    assert pooled_accuracy == .5
