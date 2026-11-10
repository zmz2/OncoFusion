"""Independent specialist ballots and deterministic vote-v1 aggregation."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter

from .evidence import visible_case
from .schemas import (
    Ballot,
    CaseInput,
    ROUTE_SPECIALIST_ROLES,
    VoteArbitration,
    VoteCalibration,
    VoteResult,
)


def vote_role_applicability(
        case: CaseInput,
        max_members: int = 5,
) -> dict[str, dict[str, bool | str]]:
    """Record why each professional role is included before any model call."""
    visible = visible_case(case)
    docs = visible.documents
    if not docs:
        return {
            role: {
                "applicable": False,
                "reason": "no visible evidence documents",
            }
            for role in ROUTE_SPECIALIST_ROLES
        }
    kinds = {doc.kind for doc in docs}
    entities = visible.entities
    supporting_entities = [entities] + [doc.entities for doc in docs]
    has_gene = any(entity.gene.strip() or entity.variant.strip()
                   for entity in supporting_entities)
    has_disease = any(entity.disease.strip() for entity in supporting_entities)
    has_drug = any(entity.drug.strip() for entity in supporting_entities)
    claim_fields = {}
    if visible.task == "verification":
        try:
            claim_fields = json.loads(visible.question)
        except (TypeError, ValueError):
            claim_fields = {}
        if not isinstance(claim_fields, dict):
            claim_fields = {}
        has_gene = has_gene or bool(claim_fields.get("molecularProfile"))
        has_disease = True
        therapies = claim_fields.get("therapies")
        has_drug = has_drug or bool(therapies)

    applicability = {
        "literature": {
            "applicable": True,
            "reason": "visible source documents are available",
        },
        "timeline": {
            "applicable": (
                "clinical" in kinds
                or any(doc.event_day is not None for doc in docs)),
            "reason": (
                "visible clinical or dated events"
                if "clinical" in kinds
                or any(doc.event_day is not None for doc in docs)
                else "no visible patient timeline"),
        },
        "genomics": {
            "applicable": has_gene or "genomics" in kinds,
            "reason": (
                "visible molecular entity or genomics material"
                if has_gene or "genomics" in kinds
                else "no visible molecular entity or genomics material"),
        },
        "pathology": {
            "applicable": has_disease or "pathology" in kinds,
            "reason": (
                "visible disease context or pathology material"
                if has_disease or "pathology" in kinds
                else "no visible disease context or pathology material"),
        },
        "drug": {
            "applicable": has_drug or "therapy" in kinds,
            "reason": (
                "visible therapy relationship or drug material"
                if has_drug or "therapy" in kinds
                else "no visible therapy relationship or drug material"),
        },
    }
    included = 0
    for role in ROUTE_SPECIALIST_ROLES:
        if applicability[role]["applicable"] and included < max_members:
            applicability[role]["selected"] = True
            included += 1
        else:
            applicability[role]["selected"] = False
            if applicability[role]["applicable"]:
                applicability[role]["reason"] += "; excluded by member limit"
    return applicability


def eligible_vote_roles(case: CaseInput, max_members: int = 5) -> list[str]:
    """Choose professional voters from visible task content, before any model call."""
    applicability = vote_role_applicability(case, max_members)
    return [
        role for role in ROUTE_SPECIALIST_ROLES
        if applicability[role]["selected"]
    ]


def _tie_key(case_id: str, tie_seed: int, label: str) -> tuple[bytes, str]:
    digest = hashlib.sha256(
        f"{tie_seed}\0{case_id}\0{label}".encode("utf-8")).digest()
    return digest, label


def _winner(scores: dict[str, float], case_id: str, tie_seed: int) -> tuple[str | None, bool, bool]:
    if not scores:
        return None, False, False
    high = max(scores.values())
    tied_labels = sorted(label for label, score in scores.items() if score == high)
    if len(tied_labels) == 1:
        return tied_labels[0], False, False
    winner = sorted(tied_labels, key=lambda label: _tie_key(case_id, tie_seed, label))[0]
    return winner, True, True


def _valid_ballots(ballots: list[Ballot], labels: tuple[str, ...] | list[str]) -> list[Ballot]:
    allowed = set(labels)
    return [
        ballot for ballot in ballots
        if ballot.status == "vote" and ballot.label in allowed
    ]


def _score_ballots(ballots: list[Ballot], labels: list[str], value) -> dict[str, float]:
    scores = {label: 0.0 for label in labels}
    for ballot in ballots:
        scores[ballot.label] += value(ballot)
    return scores


def calibrated_confidence(confidence: float, calibration: VoteCalibration) -> float:
    clipped = min(max(confidence, calibration.epsilon), 1 - calibration.epsilon)
    logit = math.log(clipped / (1 - clipped))
    value = calibration.platt_a * logit + calibration.platt_b
    if value >= 0:
        exp_negative = math.exp(-value)
        return 1 / (1 + exp_negative)
    exp_value = math.exp(value)
    return exp_value / (1 + exp_value)


def aggregate_ballots(
    *,
    case_id: str,
    ballots: list[Ballot],
    labels: list[str],
    planned_roles: list[str],
    pool: str,
    rule: str,
    role_weights: dict[str, float] | None = None,
    calibration: VoteCalibration | None = None,
    tie_seed: int = 0,
    arbitration: VoteArbitration | None = None,
    min_share: float = .75,
    min_margin: float = .25,
) -> VoteResult:
    if pool not in ("specialist", "generalist"):
        raise ValueError("unknown vote pool")
    if rule not in ("v0", "v1", "v2", "v3", "c_raw"):
        raise ValueError("unknown vote rule")
    if not labels or len(labels) != len(set(labels)):
        raise ValueError("vote labels must be unique and nonempty")
    valid = _valid_ballots(ballots, labels)
    counts = Counter(ballot.label for ballot in valid)
    count_scores = {label: float(counts.get(label, 0)) for label in labels}
    raw_scores = _score_ballots(
        valid, labels, lambda ballot: float(ballot.confidence or 0.0))
    calibrated_scores = None
    if calibration is not None:
        calibrated_scores = _score_ballots(
            valid, labels,
            lambda ballot: calibrated_confidence(float(ballot.confidence or 0.0), calibration))
    if rule in ("v0", "v3"):
        scores = count_scores
    elif rule == "c_raw":
        scores = raw_scores
    elif rule == "v1":
        if not role_weights:
            raise ValueError("v1 aggregation requires role weights")
        missing = [ballot.role for ballot in valid if ballot.role not in role_weights]
        if missing:
            raise ValueError("missing role weights for: " + ", ".join(sorted(set(missing))))
        scores = _score_ballots(valid, labels, lambda ballot: role_weights[ballot.role])
    else:
        if calibration is None:
            raise ValueError("v2 aggregation requires a confidence calibrator")
        scores = calibrated_scores

    initial_label, count_tied, count_tie_broken = _winner(
        count_scores, case_id, tie_seed)
    selected_label, selected_tied, selected_tie_broken = _winner(
        scores, case_id, tie_seed)
    ordered_counts = sorted(counts.values(), reverse=True)
    top_share = (
        ordered_counts[0] / len(valid)
        if valid and ordered_counts else None
    )
    runner_up_label = None
    ranked_labels = [
        label for label, score in sorted(
            count_scores.items(), key=lambda item: (-item[1], item[0]))
        if score > 0
    ]
    if len(ranked_labels) > 1:
        runner_up_label = ranked_labels[1]
    margin = None
    if len(ordered_counts) > 1 and valid:
        margin = (ordered_counts[0] - ordered_counts[1]) / len(valid)
    elif valid:
        margin = ordered_counts[0] / len(valid)

    if rule == "v3":
        tied, tie_broken = count_tied, count_tie_broken
        if initial_label is None:
            arbitration = arbitration or VoteArbitration(
                triggered=False, status="not_triggered",
                initial_label=None, final_label=None,
                error="no valid ballots")
        elif top_share is not None and margin is not None and (
                top_share < min_share or margin < min_margin):
            arbitration = arbitration or VoteArbitration(
                triggered=True, status="failed", initial_label=initial_label,
                final_label=initial_label, error="arbitration was not completed")
        else:
            arbitration = arbitration or VoteArbitration(
                triggered=False, status="not_triggered",
                initial_label=initial_label, final_label=initial_label)
        if arbitration.status == "completed" and arbitration.final_label in labels:
            selected_label = arbitration.final_label
        elif arbitration.final_label in labels:
            selected_label = arbitration.final_label
        else:
            selected_label = initial_label
    elif arbitration is None:
        tied, tie_broken = selected_tied, selected_tie_broken
        arbitration = VoteArbitration(
            triggered=False, status="not_triggered",
            initial_label=initial_label, final_label=selected_label)
    else:
        tied, tie_broken = selected_tied, selected_tie_broken

    planned = len(planned_roles)
    response_votes = sum(ballot.status != "failed" for ballot in ballots)
    abstain_votes = sum(ballot.status == "abstain" for ballot in ballots)
    failed_votes = sum(ballot.status == "failed" for ballot in ballots)
    threshold = math.ceil(planned / 2) if planned else 0
    if planned and response_votes == planned and len(valid) == planned:
        completion = "full"
    elif len(valid) >= threshold and threshold > 0:
        completion = "degraded"
    else:
        completion = "failed"
    failure_reason = ""
    if completion == "failed":
        if not valid:
            failure_reason = "no valid ballots"
        else:
            failure_reason = (
                f"only {len(valid)} valid ballots for {planned} planned votes; "
                f"at least {threshold} required")

    return VoteResult(
        pool=pool,
        rule=rule,
        planned_roles=planned_roles,
        planned_votes=planned,
        response_votes=response_votes,
        valid_votes=len(valid),
        abstain_votes=abstain_votes,
        failed_votes=failed_votes,
        completion_status=completion,
        label=selected_label,
        counts={label: counts.get(label, 0) for label in labels},
        scores=scores,
        raw_confidence_scores=raw_scores,
        calibrated_confidence_scores=calibrated_scores,
        runner_up_label=runner_up_label,
        top_share=top_share,
        margin=margin,
        tied=tied,
        tie_broken=tie_broken,
        arbitration=arbitration,
        failure_reason=failure_reason,
    )


def arbitration_required(vote: VoteResult, min_share: float, min_margin: float) -> bool:
    if vote.label is None or vote.top_share is None or vote.margin is None:
        return True
    return vote.top_share < min_share or vote.margin < min_margin
