"""Small specialist modules under a deterministic supervisor.

Applicability is derived from task and visible inputs, never answers or outcomes.
Modules share the same provider boundary; delegation changes expertise, not data access.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .evidence import visible_case
from .schemas import CaseInput, Document, Role, ROLES


@dataclass(frozen=True)
class SpecialistModule:
    role: Role
    source_kinds: frozenset[str]

    def sources(self, documents: list[Document]) -> list[Document]:
        return [d for d in documents if d.kind in self.source_kinds]

    def applicability(self, case: CaseInput) -> tuple[bool, str]:
        kinds = {d.kind for d in case.documents}
        claim = case.claim_fields
        structured = any(claim.model_dump().values())
        if self.role in ("decision", "verifier"):
            return True, "task synthesis or evidence verification"
        if self.role == "literature":
            return bool("literature" in kinds), "requires supplied literature, not a fabricated corpus"
        if self.role == "timeline":
            active = any(d.kind in ("clinical", "therapy") or d.event_day is not None for d in case.documents)
            return active, "requires patient events or dated evidence"
        if case.task == "verification":
            values = {"genomics": claim.molecular_profile, "pathology": claim.disease, "drug": claim.therapies}
            return bool(values[self.role]) if structured else True, "original claim dimension; free-text claims receive conservative inspection"
        active = {"genomics": "genomics" in kinds or bool(case.entities.gene or case.entities.variant),
                  "pathology": bool(kinds & {"clinical", "pathology"}) or bool(case.entities.disease),
                  # Clinical notes may contain therapy history. Never skip Drug merely because
                  # a native dataset placed treatment history in a clinical file.
                  "drug": bool(kinds & {"clinical", "therapy"}) or bool(case.entities.drug)}
        return active[self.role], "visible specialty data or shared patient context"


ALL_KINDS = frozenset({"clinical", "genomics", "pathology", "therapy", "literature"})
MODULES = {
    "timeline": SpecialistModule("timeline", ALL_KINDS - {"literature"}),
    "genomics": SpecialistModule("genomics", ALL_KINDS - {"therapy"}),
    "pathology": SpecialistModule("pathology", frozenset({"clinical", "pathology", "literature"})),
    "drug": SpecialistModule("drug", ALL_KINDS),
    "literature": SpecialistModule("literature", ALL_KINDS),
    "verifier": SpecialistModule("verifier", ALL_KINDS),
    "decision": SpecialistModule("decision", ALL_KINDS),
}


def scoped_signals(signals: dict, documents: list[Document]) -> dict:
    allowed = {d.id for d in documents}
    result = dict(signals)
    for key in ("matches", "directions"):
        if key in result:
            result[key] = {k: v for k, v in result[key].items() if k in allowed}
    for key in ("source_variant_mentions", "pathology_context", "clinical_assertions"):
        if key in result:
            result[key] = [r for r in result[key] if r["document_id"] in allowed]
    if "timeline" in result:
        result["timeline"] = [r for r in result["timeline"] if r["id"] in allowed]
    return result


def coverage(case: CaseInput) -> dict:
    case = visible_case(case)
    counts = dict(Counter(d.kind for d in case.documents))
    applicability = {role: {"applicable": MODULES[role].applicability(case)[0],
                            "basis": MODULES[role].applicability(case)[1]} for role in ROLES}
    task = {"verification": "claim_evidence_verification", "mcq": "patient_question_answering",
            "synthesis": "custom_research_synthesis"}[case.task]
    return {"task": task, "document_kinds": counts, "visible_documents": len(case.documents),
            "source_origins": len({d.origin_id for d in case.documents}),
            "heterogeneous_input": len(counts) >= 2, "roles": applicability,
            "measures_best_treatment": False,
            "scope": "Input availability audit; not semantic correctness or proof of role benefit."}
