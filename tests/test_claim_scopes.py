"""Regressions for the claims-v1 role-scope contract, the findings cap and the decoupling."""
import json

import pytest

from oncofusion.engine import Engine, build_analysis_output
from oncofusion.examples import examples
from oncofusion.providers import MockProvider, ProviderError
from oncofusion.schemas import (Ablations, ClaimAnalysisOutput, ClaimFinding, FragmentCitation,
                               RevisionAssessment, RunConfig, CaseInput, Document, Entities)
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
    with pytest.raises(ValueError, match="finding 1 has material_status=not_applicable"):
        build_analysis_output(wire, index, "pathology", True, {}, 3, {"pathologic"})


def test_unknown_material_without_citations_is_a_valid_claim():
    known = {}
    wire = ClaimAnalysisOutput(findings=[ClaimFinding(statement="unknown: no molecular assay is recorded",
                                                     relation="NEI", scope="molecular",
                                                     evidence_level="absent", material_status="unknown")])
    output = build_analysis_output(wire, {}, "genomics", True, known, 3, {"molecular"})
    assert output.findings[0].material_status == "unknown"
    assert output.findings[0].claim_id == "genomics-01"
    # Registration is the caller's job, after the whole response validated, so building alone
    # must not make the id referable.
    assert known == {}


def test_failed_response_leaves_no_claim_ids_behind():
    known = {"timeline-01": "timeline"}
    wire = ClaimAnalysisOutput(findings=[
        ClaimFinding(statement="First claim.", relation="NEI", scope="molecular",
                     evidence_level="measured", material_status="present"),
        ClaimFinding(statement="Second claim speaks out of scope.", relation="NEI", scope="temporal",
                     evidence_level="measured", material_status="present")])
    with pytest.raises(ValueError, match="outside this role"):
        build_analysis_output(wire, {}, "genomics", True, known, 3, {"molecular"})
    assert known == {"timeline-01": "timeline"}, "a rejected response must not register claim ids"


def test_output_validation_error_names_the_finding_position():
    wire = ClaimAnalysisOutput(findings=[
        ClaimFinding(statement="Valid first claim.", relation="NEI", scope="molecular",
                     evidence_level="measured", material_status="present"),
        ClaimFinding(statement="Invalid missing claim.", relation="SUPPORTS", scope="molecular",
                     evidence_level="curated", material_status="not_applicable")])
    with pytest.raises(ValueError, match=r"finding 2 has material_status=not_applicable"):
        build_analysis_output(wire, {}, "genomics", True, {}, 3, {"molecular"})


def test_first_claim_role_has_no_verdict_channel(recorder):
    result = Engine(recorder).run(CASE, v1_class_config("native"))
    roles = [payload["role"] for payload in recorder.payloads]
    first = recorder.systems[roles.index("literature")]
    later = recorder.systems[roles.index("genomics")]
    verifier = recorder.systems[roles.index("verifier")]
    assert '"verdicts"' not in first
    assert "If that list is empty, do not emit verdicts." in first
    assert "previously committed claim ids: literature-" in later
    assert '"findings"' not in verifier and '"verdicts"' in verifier
    assert result.status == "completed"


def test_missing_specialist_input_is_registered_as_not_applicable(recorder):
    result = Engine(recorder).run(CASE, v1_class_config("native"))
    timeline = next(report for report in result.reports if report.role == "timeline")
    finding = timeline.output.findings[0]
    assert finding.claim_id == "timeline-01"
    assert finding.author_role == "timeline"
    assert finding.scope == "temporal"
    assert finding.material_status == "not_applicable"
    assert finding.material_basis == "not_recorded"
    assert finding.relation == "NEI" and not finding.citations
    assert "timeline" not in [payload["role"] for payload in recorder.payloads]


def test_decision_prompt_separates_claim_ids_from_evidence_ids(recorder):
    Engine(recorder).run(CASE, v1_class_config("native"))
    decision = recorder.systems[[payload["role"] for payload in recorder.payloads].index("decision")]
    assert "A roster claim id (for example literature-01) identifies an argument, not a source span." in decision


def test_mcq_decision_prompt_excludes_verification_labels(recorder):
    case = examples()["synthetic-timeline"]
    Engine(recorder).run(case, v1_class_config("native"))
    decision = recorder.systems[[payload["role"] for payload in recorder.payloads].index("decision")]
    assert "A, B, C" in decision
    assert "never use SUPPORTS, REFUTES, REVISIONS, or NEI" in decision
    schema = json.JSONDecoder().raw_decode(decision.split("conforming to this schema: ", 1)[1])[0]
    assert schema["properties"]["answer"]["enum"] == ["A", "B", "C"]


def test_revision_gate_adds_global_assessment_schema(recorder):
    config = v1_class_config("native")
    config.claim_revision_gate = True
    case = CASE.model_copy(update={"verification_scheme": "revisions"})
    Engine(recorder).run(case, config)
    decision = recorder.systems[[payload["role"] for payload in recorder.payloads].index("decision")]
    schema = json.JSONDecoder().raw_decode(
        decision.split("conforming to this schema: ", 1)[1]
    )[0]
    assert schema["properties"]["assessment"]["$ref"].split("/")[-1] == "RevisionAssessment"
    assert "evidence_relevance" in schema["$defs"]["RevisionAssessment"]["properties"]
    assert "classify requires_revision rather than no_supported_revision" in decision


def test_revision_gate_rejects_label_assessment_conflict():
    case = CASE.model_copy(update={"verification_scheme": "revisions"})
    class Conflict(MockProvider):
        def complete(self, system, payload, max_tokens, temperature, seed):
            reply = super().complete(system, payload, max_tokens, temperature, seed)
            if payload.get("role") != "decision" or not payload.get("revision_gate"):
                return reply
            body = json.loads(reply.content)
            body["answer"] = "NEI"
            body["assessment"] = {
                "evidence_relevance": "relevant",
                "claim_conformance": "requires_revision",
                "revision_fields": ["significance"],
                "minimal_revision": "Change resistance to the supported direction.",
            }
            reply.content = json.dumps(body)
            return reply
    config = v1_class_config("native")
    config.claim_revision_gate = True
    with pytest.raises(ProviderError, match="schema or source-integrity"):
        Engine(Conflict()).run(case, config)


def test_revision_gate_maps_no_supported_revision_to_nei():
    case = CASE.model_copy(update={"verification_scheme": "revisions"})

    class NoRevision(MockProvider):
        def complete(self, system, payload, max_tokens, temperature, seed):
            reply = super().complete(system, payload, max_tokens, temperature, seed)
            if payload.get("role") != "decision" or not payload.get("revision_gate"):
                return reply
            body = json.loads(reply.content)
            body["answer"] = "NEI"
            body["assessment"] = {
                "evidence_relevance": "relevant",
                "claim_conformance": "no_supported_revision",
                "revision_fields": [],
                "minimal_revision": "",
            }
            reply.content = json.dumps(body)
            return reply

    config = v1_class_config("native")
    config.claim_revision_gate = True
    result = Engine(NoRevision()).run(case, config)
    assert result.decision.answer == "NEI"
    assert result.status == "completed"


def test_revision_assessment_rejects_illegal_revision_shape():
    with pytest.raises(ValueError, match="requires_revision must provide a minimal revision"):
        RevisionAssessment(evidence_relevance="relevant", claim_conformance="requires_revision",
                           revision_fields=["disease"])
    with pytest.raises(ValueError, match="Input should be"):
        RevisionAssessment(evidence_relevance="relevant", claim_conformance="requires_revision",
                           revision_fields=["patient age"], minimal_revision="Narrow the disease context.")


def test_revision_gate_is_verification_only():
    config = v1_class_config("native").model_copy(update={"claim_revision_gate": True})
    with pytest.raises(ValueError, match="requires a verification task"):
        Engine(MockProvider()).run(examples()["synthetic-timeline"], config)


def test_role_scope_is_encoded_in_the_response_schema(recorder):
    Engine(recorder).run(CASE, v1_class_config("native"))
    timeline = recorder.systems[[payload["role"] for payload in recorder.payloads].index("genomics")]
    schema_text = timeline.split("conforming to this schema: ", 1)[1]
    schema = json.JSONDecoder().raw_decode(schema_text)[0]
    assert schema["$defs"]["ClaimFinding"]["properties"]["scope"]["enum"] == ["molecular"]


def test_verdict_citations_are_resolved_then_capped():
    case, listed, index = finding_case()
    evidence_id = listed[0]["evidence_id"]
    wire = ClaimAnalysisOutput(verdicts=[{
        "target_claim_id": "timeline-01",
        "verdict": "confirmed",
        "citations": [{"evidence_id": evidence_id}] * 6,
    }])
    events = []
    output = build_analysis_output(
        wire, index, "verifier", True, {"timeline-01": "timeline"}, 3, {"verification"},
        emit=lambda kind, role="", **details: events.append((kind, details)),
    )
    assert len(output.verdicts[0].citations) == 4
    assert ("verdict_citations_capped",
            {"target_claim_id": "timeline-01", "reported": 6, "kept": 4}) in events


def test_claim_ids_continue_across_a_reported_role_round():
    known = {"literature-01": "literature", "literature-02": "literature"}
    wire = ClaimAnalysisOutput(findings=[ClaimFinding(statement="Requeried passage.", relation="NEI",
                                                      scope="source", evidence_level="literature",
                                                      material_status="present")])
    output = build_analysis_output(wire, {}, "literature", True, known, 3, {"source"})
    assert output.findings[0].claim_id == "literature-03"


def test_used_claim_ids_may_only_name_committed_or_earlier_same_response_ids():
    known = {"timeline-01": "timeline"}
    wire = ClaimAnalysisOutput(findings=[
        ClaimFinding(statement="Built on the timeline.", relation="NEI", scope="molecular",
                     evidence_level="measured", material_status="present", used_claim_ids=["timeline-01"]),
        ClaimFinding(statement="Built on my own first claim.", relation="NEI", scope="molecular",
                     evidence_level="measured", material_status="present", used_claim_ids=["genomics-01"])])
    output = build_analysis_output(wire, {}, "genomics", True, known, 3, {"molecular"})
    assert [f.used_claim_ids for f in output.findings] == [["timeline-01"], ["genomics-01"]]
    with pytest.raises(ValueError, match="no earlier role produced"):
        build_analysis_output(wire.model_copy(update={"findings": wire.findings[:1] + [
            wire.findings[1].model_copy(update={"used_claim_ids": ["genomics-02"]})]}),
            {}, "genomics", True, known, 3, {"molecular"})


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
