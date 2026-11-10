import pytest

from oncofusion.examples import examples
from oncofusion.schemas import Ballot, CaseInput, Document, Entities, VoteCalibration
from oncofusion.voting import (
    aggregate_ballots,
    arbitration_required,
    calibrated_confidence,
    eligible_vote_roles,
    vote_role_applicability,
)


def ballot(role, label, confidence=.6):
    return Ballot(
        ballot_id=role,
        role=role,
        status="vote",
        label=label,
        confidence=confidence,
        brief_reason="synthetic test ballot",
    )


def aggregate(ballots, rule="v0", **kwargs):
    return aggregate_ballots(
        case_id="case-1",
        ballots=ballots,
        labels=["A", "B", "NEI"],
        planned_roles=[item.ballot_id for item in ballots],
        pool="specialist",
        rule=rule,
        **kwargs,
    )


def test_civic_eligible_roles_exclude_timeline_and_keep_four_professions():
    roles = eligible_vote_roles(examples()["synthetic-support"])
    assert roles == ["literature", "genomics", "pathology", "drug"]
    applicability = vote_role_applicability(
        examples()["synthetic-support"])
    assert applicability["timeline"] == {
        "applicable": False,
        "reason": "no visible patient timeline",
        "selected": False,
    }
    assert applicability["pathology"]["applicable"]


def test_timeline_is_eligible_only_when_visible_timeline_exists():
    assert eligible_vote_roles(examples()["synthetic-timeline"]) == [
        "literature", "timeline"]


def test_v0_counts_votes_and_breaks_a_multiclass_tie_deterministically():
    rows = [
        ballot("literature", "A"),
        ballot("genomics", "A"),
        ballot("pathology", "B"),
        ballot("drug", "B"),
        ballot("timeline", "NEI"),
    ]
    first = aggregate(rows)
    second = aggregate(rows)
    assert first.counts == {"A": 2, "B": 2, "NEI": 1}
    assert first.label == second.label
    assert first.tied and first.tie_broken
    assert first.label in {"A", "B"}


def test_reliability_weights_change_the_winner_without_extra_calls():
    rows = [
        ballot("literature", "A"),
        ballot("genomics", "B"),
        ballot("pathology", "B"),
    ]
    equal = aggregate(rows)
    weighted = aggregate(
        rows,
        rule="v1",
        role_weights={"literature": 3.0, "genomics": 1.0, "pathology": 1.0},
    )
    assert equal.label == "B"
    assert weighted.label == "A"
    assert weighted.scores["A"] == 3.0
    assert weighted.scores["B"] == 2.0
    tied_weighted = aggregate(
        rows,
        rule="v1",
        role_weights={"literature": 2.0, "genomics": 1.0, "pathology": 1.0},
    )
    assert tied_weighted.scores["A"] == tied_weighted.scores["B"] == 2.0
    assert tied_weighted.tied and tied_weighted.tie_broken


def test_calibrated_confidence_differs_from_raw_confidence_diagnostic():
    calibration = VoteCalibration(platt_a=-4.0, platt_b=1.0)
    rows = [
        ballot("literature", "A", .9),
        ballot("genomics", "B", .4),
        ballot("pathology", "B", .4),
    ]
    result = aggregate(rows, rule="v2", calibration=calibration)
    assert result.raw_confidence_scores["A"] > sum(
        result.raw_confidence_scores[label] for label in ("B",))
    assert result.calibrated_confidence_scores["A"] < sum(
        result.calibrated_confidence_scores[label] for label in ("B",))
    assert result.label == "B"
    assert calibrated_confidence(.4, calibration) > .4


def test_v3_trigger_uses_share_and_margin_thresholds():
    low_consistency = aggregate([
        ballot("literature", "A"),
        ballot("genomics", "B"),
        ballot("pathology", "NEI"),
        ballot("drug", "B"),
    ])
    consensus = aggregate([
        ballot("literature", "A"),
        ballot("genomics", "A"),
        ballot("pathology", "A"),
        ballot("drug", "B"),
    ])
    assert arbitration_required(low_consistency, .75, .25)
    assert not arbitration_required(consensus, .75, .25)


def test_abstain_and_failed_are_not_valid_votes():
    rows = [
        ballot("literature", "A"),
        Ballot(ballot_id="genomics", role="genomics", status="abstain",
               brief_reason="not applicable"),
        Ballot(ballot_id="pathology", role="pathology", status="failed",
               error="provider failure"),
    ]
    result = aggregate(rows)
    assert result.valid_votes == 1
    assert result.abstain_votes == 1
    assert result.failed_votes == 1
    assert result.completion_status == "failed"


def test_v1_requires_all_valid_voter_weights():
    with pytest.raises(ValueError, match="missing role weights"):
        aggregate(
            [ballot("literature", "A"), ballot("genomics", "B")],
            rule="v1",
            role_weights={"literature": 1.0},
        )
