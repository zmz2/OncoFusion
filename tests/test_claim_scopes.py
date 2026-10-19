"""Regressions for the claims-v1 role-scope contract, the findings cap and the decoupling."""
import json

import pytest

from oncofusion.engine import Engine, build_analysis_output
from oncofusion.examples import examples
from oncofusion.providers import MockProvider
from oncofusion.schemas import (Ablations, ClaimAnalysisOutput, ClaimFinding, FragmentCitation,
                               RunConfig, CaseInput, Document, Entities)
from oncofusion.profiles import v1_class_config, v1_fast_config

CASE = next(c for c in examples().values() if c.task == "verification")


def index_for(case):
    from oncofusion.evidence import fragment_documents
    listed, index, coverage = fragment_documents(case.documents, 400, 8, case.question, 4000)
    assert listed and coverage["candidates"] > 0
    return listed, index


def finding_case():
    case = CASE
    listed, index = index_for(case)
    return case, listed, index


def test_out_of_scope_claim_is_rejected():
    case, listed, index = finding_case()
    first = listed[0]["evidence_id"]
    wire = ClaimAnalysisOutput(findings=[ClaimFinding(statement="The gene is amplified.", relation="NEI",
                                                     citations=[FragmentCitation(evidence_id=first)],
                                                     scope="outcome_prediction", evidence_level="measured",
                                                     material_status="present")])
    with pytest.raises(ValueError, match="outside this role"):
        build_analysis_output(wire, index, "genomics", True, {}, 3, {"molecular"})


def test_missing_material_claim_cannot_cite_or_assert():
    case, listed, index = finding_case()
    first = listed[0]["evidence_id"]
    wire = ClaimAnalysisOutput(findings=[ClaimFinding(statement="not_applicable: no specimen data",
                                                     relation="SUPPORTS",
                                                     citations=[FragmentCitation(evidence_id=first)],
                                                     scope="pathologic", evidence_level="absent",
                                                     material_status="not_applicable")])
    with pytest.raises(ValueError, match="missing-material claim"):
        build_analysis_output(wire, index, "pathology", True, {}, 3, {"pathologic"})


def test_unknown_material_without_citations_is_a_valid_claim():
    known = {}
    wire = ClaimAnalysisOutput(findings=[ClaimFinding(statement="unknown: no molecular assay is recorded",
                                                     relation="NEI", scope="molecular",
                                                     evidence_level="absent", material_status="unknown")])
    output = build_analysis_output(wire, {}, "genomics", True, known, 3, {"molecular"})
    assert output.findings[0].material_status == "unknown"
    assert output.findings[0].claim_id == "genomics-01"
    assert known["genomics-01"] == "genomics"


def test_findings_are_capped_and_the_drop_is_recorded():
    events = []
    wire = ClaimAnalysisOutput(findings=[ClaimFinding(statement="observation %d" % i, relation="NEI",
                                                     scope="temporal", evidence_level="measured",
                                                     material_status="present") for i in range(9)])
    output = build_analysis_output(wire, {}, "timeline", True, {}, 3, {"temporal"},
                                   emit=lambda kind, role="", **d: events.append((kind, d)))
    assert len(output.findings) == 3
    assert ("findings_capped", {"reported": 9, "kept": 3, "dropped": 6}) in events


def test_claims_v1_does_not_need_the_semantic_verifier_switch():
    config = v1_class_config("native").model_copy(
        update={"ablations": Ablations(targeted_requery=False, external_verification=False)})
    assert config.citation_mode == "fragment" and config.interaction_protocol == "claims-v1"
    result = Engine(MockProvider()).run(CASE, config)
    assert result.status == "completed"
    assert result.reports and result.decision
    # the reflection verifier gets no source view at all, so it may legitimately return no
    # findings; every role that did receive material must still produce claims.
    assert all(r.output.findings for r in result.reports if r.role != "verifier")
    assert all(f.claim_id and f.scope for r in result.reports for f in r.output.findings)
    legacy = v1_fast_config("native").model_copy(
        update={"ablations": Ablations(targeted_requery=False, external_verification=False)})
    with pytest.raises(ValueError, match="requires external_verification"):
        Engine(MockProvider()).run(CASE, legacy)


def test_classroom_budget_is_smaller_per_stage_and_wider_in_total():
    config = v1_class_config("native")
    assert config.fragment_budget == 12_000 and config.max_total_tokens == 260_000
    assert v1_fast_config("native").fragment_budget == 24_000


def test_mock_run_records_scopes_levels_and_verdicts():
    result = Engine(MockProvider()).run(CASE, v1_class_config("native"))
    scopes = {f.scope for r in result.reports for f in r.output.findings}
    assert scopes and "outcome_prediction" not in scopes
    assert all(f.evidence_level and f.material_status for r in result.reports for f in r.output.findings)
    verifier = next(r for r in result.reports if r.role == "verifier")
    assert verifier.output.verdicts
    assert result.decision.adopted_claim_ids
