import copy
import pytest
from oncofusion.retrieval_benchmark import import_retrieval, evaluate_retrieval, prepare_retrieval


def fixture():
    chunks = [{"chunk.start": 0, "chunk.end": 27, "chunk.text": "GENE1 response to Compound.", "chunk.id": "123:0-27", "document.pmid": "123", "partition": "dev",
               "selections": [{"secret_gold": "LEAK"}]},
              {"chunk.start": 27, "chunk.end": 48, "chunk.text": "Unrelated discussion.", "chunk.id": "123:27-48", "document.pmid": "123", "partition": "dev"}]
    queries = [{"document.pmid": "123", "claim.flat": "GENE1 response to Compound", "gold_label_name": "SUPPORTS", "civic.id": 99,
                "evidence": [{"content": "GENE1 response", "meta": {"start": 0, "end": 13}}]}]
    return queries, chunks


def test_import_and_rank_no_relevance_leak():
    queries, chunks = fixture()
    cases, gold, audit = import_retrieval(queries, chunks)
    assert audit["included"] == 1 and not audit["excluded"]
    assert "secret_gold" not in cases[0].model_dump_json()
    assert "LEAK" not in cases[0].model_dump_json()
    assert gold[0].relevant_document_ids == ["chunk-123:0-27"]
    result = evaluate_retrieval(cases, gold)
    assert result["metrics"]["bm25"]["1"]["recall_at_k"] == 1
    assert result["model_api_calls"] == 0


@pytest.mark.parametrize("change", ["no_article", "no_span", "NEI"])
def test_exclusions_visible(change, tmp_path):
    queries, chunks = fixture()
    if change == "no_article":
        queries[0]["document.pmid"] = "999"
    elif change == "no_span":
        queries[0]["evidence"][0]["meta"] = {}
    else:
        queries[0]["gold_label_name"] = "NEI"
    cases, gold, audit = import_retrieval(queries, chunks)
    assert not cases and audit["excluded"]
    with pytest.raises(ValueError):
        prepare_retrieval(queries, chunks, tmp_path)
    assert (tmp_path / "retrieval_audit.json").exists()


def test_duplicate_queries_union_without_changing_input():
    queries, chunks = fixture()
    before = copy.deepcopy(queries)
    cases, gold, audit = import_retrieval(queries + queries, chunks)
    assert len(cases) == len(gold) == 1
    assert audit["merged_duplicate_rows"] == 1
    assert queries == before


def test_duplicate_queries_conflicting_labels():
    queries, chunks = fixture()
    other = copy.deepcopy(queries[0])
    other["gold_label_name"] = "NEI"
    with pytest.raises(ValueError, match="conflicting"):
        import_retrieval(queries + [other], chunks)


@pytest.mark.parametrize("change", ["chunk", "span", "partition"])
def test_invalid_raw_boundaries(change):
    queries, chunks = fixture()
    if change == "chunk":
        chunks[0]["chunk.end"] = 500
    elif change == "span":
        queries[0]["evidence"][0]["meta"]["end"] = -1
    else:
        chunks[1]["partition"] = "test"
    with pytest.raises(ValueError):
        import_retrieval(queries, chunks)


def test_retrieval_prepare_and_exclusion_review(tmp_path):
    queries, chunks = fixture()
    excluded = copy.deepcopy(queries[0])
    excluded["claim.flat"] = "Other query"
    excluded["gold_label_name"] = "NEI"
    with pytest.raises(ValueError, match="excluded"):
        prepare_retrieval(queries + [excluded], chunks, tmp_path)
    result = prepare_retrieval(queries + [excluded], chunks, tmp_path, True)
    assert result["manifest"]["count"] == 1


@pytest.mark.parametrize("ks", [(), (0,), (101,)])
def test_invalid_ranking_cutoffs(ks):
    cases, gold, _ = import_retrieval(*fixture())
    with pytest.raises(ValueError):
        evaluate_retrieval(cases, gold, ks)


def test_unknown_relevance_id_fails():
    cases, gold, _ = import_retrieval(*fixture())
    gold[0].relevant_document_ids = ["wrong"]
    with pytest.raises(ValueError):
        evaluate_retrieval(cases, gold)
