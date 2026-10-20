"""Key treatment events survive selection, and a missing modality says why it is missing."""
import pytest

from oncofusion.engine import build_analysis_output
from oncofusion.evidence import (fragment_documents, fragment_spans, material_basis_of, visible_case)
from oncofusion.schemas import (CaseInput, ClaimAnalysisOutput, ClaimFinding, Document, Entities)

# One long clinical timeline: the record that names the agent sits in the middle, exactly where
# mtb-P-0022916-q6 keeps its "AGENT: FLOXURIDINE" line (offset 3623 of a 5,985-character document).
TIMELINE = "".join("AGE: %.1f, diagnosis > note --> text for record %02d %s\n"
                   % (50 + i * .1, i, "x" * 48) for i in range(40))
DRUG_AT = TIMELINE.index("AGE: 52.0")
TIMELINE = (TIMELINE[:DRUG_AT] + "AGE: 52.0, treatment > treatment --> STOP_REASON: completed, "
            "SUBTYPE: Chemo, AGENT: FLOXURIDINE, RX_INVESTIGATIVE: N, \n" + TIMELINE[DRUG_AT:])
CHARS = 300
QUESTION = "Given that the patient is 60 years old, will the patient be still alive in 12 months?"


def q6_like(stage=0, future=None):
    docs = [Document(id="clin", origin_id="clin", kind="clinical", text=TIMELINE)]
    if future:
        docs.append(Document(id="late", origin_id="late", kind="clinical", text=future,
                             available_stage=2))
    return CaseInput(schema_version="1.0", id="synth-q6", patient_id="P1", task="mcq",
                     question=QUESTION, options={"A": "alive", "B": "not alive"},
                     entities=Entities(), stage=stage, documents=docs,
                     data_class="synthetic")


def span_holding(text, offset, chars=CHARS):
    return next((s, e) for s, e in fragment_spans(text, chars) if s <= offset < e)


def test_the_record_naming_the_agent_is_sent_even_when_the_budget_is_tight():
    case = visible_case(q6_like())
    start, end = span_holding(TIMELINE, DRUG_AT)
    assert "FLOXURIDINE" in case.documents[0].text[start:end]
    tight = (end - start) + 60           # room for one span only, and the drug record is not first
    listed, index, coverage = fragment_documents(case.documents, CHARS, 8, QUESTION, tight, role="drug")
    sent = [f for f in listed if f["record_span"] == [start, end]]
    assert sent, "the treatment record must be handed to the drug role by its original offset"
    assert sent[0]["required"] == ["treatment"]
    assert coverage["required"]["treatment"]["sent"] == 1
    assert coverage["chars_sent"] <= tight
    # Without the role requirement the same plan spends its first span on a structural record.
    plain, _, plain_coverage = fragment_documents(case.documents, CHARS, 8, QUESTION, tight)
    assert [f["evidence_id"] for f in plain] != [f["evidence_id"] for f in listed]
    assert plain_coverage["required"] == {}
    assert sent[0]["evidence_id"] not in {f["evidence_id"] for f in plain}
    # Citations still resolve only through the ids this stage actually sent.
    assert sent[0]["evidence_id"] in index


def test_a_future_stage_record_is_neither_a_candidate_nor_sent():
    future_text = "AGE: 61.0, treatment > treatment --> SUBTYPE: Chemo, AGENT: FLOXURIDINE, \n" * 3
    case = visible_case(q6_like(stage=0, future=future_text))
    assert [d.id for d in case.documents] == ["clin"]
    listed, index, coverage = fragment_documents(case.documents, CHARS, 8, QUESTION, 12000, role="drug")
    assert all(f["document_id"] != "late" for f in listed)
    assert "late" not in coverage["documents"]
    assert all(not eid.startswith("late:") for eid in index)


def test_a_guaranteed_span_that_cannot_fit_is_recorded_not_silently_dropped():
    case = visible_case(q6_like())
    start, end = span_holding(TIMELINE, DRUG_AT)
    tiny = (end - start) // 2           # smaller than the treatment record itself
    listed, _, coverage = fragment_documents(case.documents, CHARS, 8, QUESTION, tiny, role="drug")
    assert coverage["chars_sent"] <= tiny, "never go quietly over the stage budget"
    unsent = [entry for entry in coverage["guaranteed_unsent"] if entry["record_span"] == [start, end]]
    assert unsent and unsent[0]["guarantee"] == "modality"
    assert unsent[0]["modalities"] == ["treatment"]
    assert unsent[0]["reason"] == "character budget"
    assert unsent[0]["evidence_id"] not in {f["evidence_id"] for f in listed}


def test_material_basis_separates_not_recorded_from_not_selected():
    def coverage_for(role, budget):
        listed, _, coverage = fragment_documents(visible_case(q6_like()).documents, CHARS, 8,
                                                 QUESTION, budget, role=role)
        return coverage
    assert material_basis_of(coverage_for("drug", 12000)) == "supplied"
    assert material_basis_of(coverage_for("drug", 200)) == "selection_not_covered"
    molecular = coverage_for("genomics", 12000)   # this synthetic timeline has no molecular record
    assert molecular["required"]["molecular"]["candidates"] == 0
    assert material_basis_of(molecular) == "not_recorded"
    assert material_basis_of({}) == ""


def test_missing_material_claims_carry_the_server_side_basis():
    wire = ClaimAnalysisOutput(findings=[ClaimFinding(
        statement="unknown: no drug exposure is recorded for this patient.",
        relation="NEI", scope="exposure", evidence_level="absent", material_status="unknown")])
    output = build_analysis_output(wire, {}, "drug", True, {}, 3, {"exposure"},
                                   material_basis="selection_not_covered")
    assert output.findings[0].material_basis == "selection_not_covered"
    present = ClaimAnalysisOutput(findings=[ClaimFinding(
        statement="FLOXURIDINE exposure is recorded.", relation="NEI", scope="exposure",
        evidence_level="measured", material_status="present")])
    output = build_analysis_output(present, {}, "drug", True, {}, 3, {"exposure"},
                                   material_basis="supplied")
    assert output.findings[0].material_basis == "", "the basis only annotates missing material"
