import itertools
import pytest
from pydantic import ValidationError
from oncofusion.evidence import (AMINO, canonical_variant, check_citations, deduplicate_documents,
                                 deduplicate_findings, entity_compatibility, normalized, polarity,
                                 quote_document, retrieve, visible_case)
from oncofusion.schemas import (Ablations, CaseInput, Citation, Document, Entities, Finding,
                                RunConfig, RunRequest)


@pytest.mark.parametrize("key", ["answer", "gold_label_name", "label", "reviews", "source_path"])
def test_input_rejects_labels_and_arbitrary_paths(case, key):
    value = case.model_dump()
    value[key] = "GOLD_CANARY"
    with pytest.raises(ValidationError):
        CaseInput.model_validate(value)


@pytest.mark.parametrize("name", ["../escape", "/tmp/file", "a/b", "", "x" * 121])
def test_ids_reject_paths(case, name):
    with pytest.raises(ValidationError):
        CaseInput.model_validate({**case.model_dump(), "id": name})


def test_nested_extra_fields(case):
    value = case.model_dump()
    value["documents"][0]["answer"] = "secret"
    with pytest.raises(ValidationError):
        CaseInput.model_validate(value)


def test_duplicate_documents(case):
    with pytest.raises(ValidationError):
        CaseInput.model_validate({**case.model_dump(), "documents": [case.documents[0], case.documents[0]]})


@pytest.mark.parametrize("task,options", [("mcq", {}), ("mcq", {"A": "one"}), ("verification", {"A": "one"}),
                                         ("mcq", {"A": "", "B": "two"})])
def test_task_options(case, task, options):
    with pytest.raises(ValidationError):
        CaseInput.model_validate({**case.model_dump(), "task": task, "options": options})


@pytest.mark.parametrize("value", [{}, {"case_id": "a", "example_id": "b"}, {"case_id": "a", "case": {}},
                                   {"max_calls": 10}, {"example_id": "a", "api_key": "secret"}])
def test_run_request_boundary(value):
    with pytest.raises(ValidationError):
        RunRequest.model_validate(value)


@pytest.mark.parametrize("field,value", [("max_calls", 0), ("max_tool_calls", 0), ("temperature", float("nan")),
                                        ("max_output_tokens", 99999), ("candidate_k", 1), ("delegated_roles", ["drug", "drug"])])
def test_config_constraints(field, value):
    with pytest.raises(ValidationError):
        RunConfig(**{field: value})


@pytest.mark.parametrize("long,short", list(AMINO.items()))
def test_protein_normalization(long, short):
    assert canonical_variant(f"p.{long}42Glu") == f"{short}42E"


@pytest.mark.parametrize("value", ["EGFR::RAD51", "c.1799T>A", "p.Glu746_Ala750del", "unknown", "p.(Val600Glu)"])
def test_unsupported_variants_preserved(value):
    assert canonical_variant(value) == value


def test_short_variant_and_casefold():
    assert canonical_variant(" p.V600E ") == "V600E"
    assert normalized("Tumor-A  ") == "tumor a"
    assert canonical_variant("p.Xxx42Glu") == "p.Xxx42Glu"


@pytest.mark.parametrize("stage,day", itertools.product(range(3), [None, -1, 0, 30, 90]))
def test_visibility_combined_boundaries(case, stage, day):
    extra = Document(id="dated", origin_id="dated", kind="clinical", text="known", event_day=20)
    case.documents.append(extra)
    case.stage, case.as_of_day = stage, day
    view = visible_case(case)
    expected = [d.id for d in case.documents if d.available_stage <= stage and (day is None or d.event_day is None or d.event_day <= day)]
    assert [d.id for d in view.documents] == expected
    assert len(case.documents) == 5


def test_citation_unicode():
    doc = Document(id="d", origin_id="o", kind="clinical", text="基因🧬 evidence")
    citation = Citation(document_id="d", start=2, end=3, quote="🧬")
    check_citations([citation], [doc])
    assert quote_document(doc).quote == doc.text


@pytest.mark.parametrize("overrides", [dict(document_id="secret"), dict(start=1), dict(end=999), dict(quote="fabricated")])
def test_invalid_source_reference(case, overrides):
    citation = quote_document(case.documents[0]).model_copy(update=overrides)
    with pytest.raises(ValueError):
        check_citations([citation], case.documents)


@pytest.mark.parametrize("start,end", [(1, 1), (2, 1), (-1, 2), (0, 0)])
def test_invalid_citation_ranges(start, end):
    with pytest.raises(ValidationError):
        Citation(document_id="d", start=start, end=end, quote="x")


def test_entity_compatibility():
    q = Entities(gene="BRAF", variant="p.Val600Glu", disease="tumor-a")
    d = Entities(gene="BRAF", variant="V600E", disease="Tumor-B")
    assert entity_compatibility(q, d) == {"gene": "match", "variant": "match", "disease": "mismatch", "drug": "unknown"}
    assert entity_compatibility(q, d, False)["variant"] == "mismatch"


@pytest.mark.parametrize("text,result", [("sensitive", "sensitivity"), ("resistance", "resistance"),
                                       ("not sensitive", "resistance"), ("no response", "resistance"),
                                       ("morphology", "unknown"), ("responded", "sensitivity")])
def test_direction_feature(text, result):
    assert polarity(text) == result


def test_bm25_and_rerank():
    relevant = Document(id="a", origin_id="o1", kind="literature", text="rare event",
                        entities=Entities(disease="A"))
    noisy = Document(id="b", origin_id="o2", kind="literature", text="gene drug gene drug gene drug",
                     entities=Entities(disease="B"))
    q = Entities(disease="A")
    assert retrieve("gene drug", [relevant, noisy], 1, 2, q, False)[0].id == "b"
    assert retrieve("gene drug", [relevant, noisy], 1, 2, q, True)[0].id == "a"
    assert retrieve("gene drug", [], 1, 2, q) == []
    assert retrieve("", [relevant, noisy], 1, 2, Entities(), False)[0].id == "a"
    assert retrieve("gene drug", [relevant, noisy], 1, 1, q, True)[0].id == "b"


def test_document_and_finding_dedup(case):
    doc = case.documents[0]
    clone = doc.model_copy(update={"id": "clone"})
    other_source = doc.model_copy(update={"id": "independent", "origin_id": "independent"})
    different_text = doc.model_copy(update={"id": "different", "text": "contradiction"})
    docs = [doc, clone, other_source, different_text]
    assert [d.id for d in deduplicate_documents(docs)] == [doc.id, "independent", "different"]
    f1 = Finding(statement="Claim", relation="SUPPORTS", citations=[quote_document(doc)])
    f2 = Finding(statement="claim", relation="SUPPORTS", citations=[quote_document(clone)])
    f3 = Finding(statement="claim", relation="REFUTES", citations=[quote_document(clone)])
    assert len(deduplicate_findings([f1, f2, f3], docs)) == 2


def test_quote_only_citations_are_located():
    doc = Document(id="d", origin_id="o", kind="clinical", text="Here is a unique Chinese phrase: 肿瘤证据。")
    citation = Citation(document_id="d", quote="肿瘤证据")
    check_citations([citation], [doc])
    assert doc.text[citation.start:citation.end] == "肿瘤证据"
    with pytest.raises(ValidationError):
        Citation(document_id="d", start=1, quote="word")


@pytest.mark.parametrize("quote", ["missing", "repeat"])
def test_quote_only_ambiguous_or_missing_rejected(quote):
    doc = Document(id="d", origin_id="o", kind="clinical", text="repeat and repeat")
    with pytest.raises(ValueError):
        check_citations([Citation(document_id="d", quote=quote)], [doc])


def test_raw_variant_normalization_with_exact_spans():
    from oncofusion.evidence import variant_mentions
    doc = Document(id="g", origin_id="g", kind="genomics", text='Hugo_Symbol\tProtein_Change\nBRAF\tp.Val600Glu\nEGFR\tL858R\nc.1799T>A\n')
    rows = variant_mentions([doc])
    assert [r["canonical"] for r in rows] == ["V600E", "L858R"]
    assert all(doc.text[r["start"]:r["end"]] == r["raw"] for r in rows)
    assert len(variant_mentions([doc.model_copy(update={"text": "p.Val600Glu " * 250})])) == 200


def test_explicit_raw_pathology_fields():
    from oncofusion.evidence import pathology_fields
    doc = Document(id="p", origin_id="p", kind="pathology", text='{"CANCER_TYPE": "Lung Cancer", "HISTOLOGY": "Adenocarcinoma"}\nPRIMARY_SITE: lung')
    rows = pathology_fields([doc])
    assert [r["value"] for r in rows] == ["Lung Cancer", "Adenocarcinoma", "lung"]
    assert pathology_fields([doc.model_copy(update={"kind": "clinical"})]) == []
    assert len(pathology_fields([doc.model_copy(update={"text": "HISTOLOGY: Adenocarcinoma\n" * 120})])) == 100


def test_mixed_direction_is_preserved():
    assert polarity("Some tumors show sensitivity; others develop resistance.") == "mixed"
