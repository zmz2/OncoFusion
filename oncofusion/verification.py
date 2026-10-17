"""Auditable claim selection and coverage, inspired by GeneAgent verification.

No upstream LLM runtime is imported. Semantic verdicts remain model judgments.
"""
import hashlib
import json
from .schemas import AgentReport, Document, ClaimReview
from .evidence import check_citations


def claim_identifier(finding, origins: dict[str, str]) -> str:
    key = {"statement": finding.statement,
           "sources": sorted({origins[c.document_id] for c in finding.citations})}
    return "claim-" + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24]


def verification_targets(reports: list[AgentReport], documents: list[Document], limit: int):
    latest = {r.role: r for r in reports if r.role != "verifier"}
    origins = {d.id: d.origin_id for d in documents}
    targets = {}
    for report in latest.values():
        for finding in report.output.findings:
            cid = claim_identifier(finding, origins)
            if cid not in targets:
                targets[cid] = {"claim_id": cid, "role": report.role, **finding.model_dump(mode="json")}
    # Round robin prevents literature (executed first) from consuming every review slot.
    groups = {r: [v for v in targets.values() if v["role"] == r] for r in latest}
    ordered = []
    while any(groups.values()):
        for values in groups.values():
            if values:
                ordered.append(values.pop(0))
    return ordered[:limit], ordered[limit:]


def validate_reviews(reviews: list[ClaimReview], targets: list[dict], documents: list[Document],
                     allowed_spans: set | None = None):
    expected = {target["claim_id"] for target in targets}
    ids = [r.claim_id for r in reviews]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("verifier must review every selected claim exactly once")
    for review in reviews:
        check_citations(review.citations, documents)
        if review.verdict != "insufficient" and not review.citations:
            raise ValueError("substantive verification verdicts require original citations")
        if allowed_spans is not None and any((c.document_id, c.start, c.end, c.quote) not in allowed_spans
                                             for c in review.citations):
            raise ValueError("reflection may only cite previously supplied excerpts")
