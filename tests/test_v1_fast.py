"""Regression for the v1_fast evidence-fragment citation path (mock model, no network)."""
import copy
import json

import pytest

from oncofusion.engine import Engine
from oncofusion.evidence import fragment_documents, resolve_fragment_citations
from oncofusion.examples import examples
from oncofusion.profiles import v1_config, v1_fast_config
from oncofusion.providers import MockProvider, ModelReply, ProviderError
from oncofusion.schemas import Ablations, Document, FragmentCitation, RunResult


def case():
    return next(c for c in examples().values() if c.task == "verification")


def docs():
    return [Document(id="d1", origin_id="o1", kind="clinical", text="Alpha beta. Gamma delta. " * 60)]


def capture(provider=None):
    provider = provider or MockProvider()
    seen = {"payloads": [], "systems": []}
    original = provider.complete

    def complete(system, payload, max_tokens, temperature, seed):
        seen["payloads"].append(copy.deepcopy(payload))
        seen["systems"].append(system)
        return original(system, payload, max_tokens, temperature, seed)

    provider.complete = complete
    return provider, seen


def test_fragment_ids_are_deterministic_and_bounded():
    listed, index = fragment_documents(docs(), 200, 4)
    again, _ = fragment_documents(docs(), 200, 4)
    assert listed == again
    assert [f["evidence_id"] for f in listed] == ["d1:f01", "d1:f02", "d1:f03", "d1:f04"]
    assert set(index) == {f["evidence_id"] for f in listed}


def test_resolution_backfills_the_exact_source_span():
    listed, index = fragment_documents(docs(), 200, 4)
    citation = resolve_fragment_citations([FragmentCitation(evidence_id="d1:f02")], index)[0]
    text = docs()[0].text
    assert citation.document_id == "d1"
    assert citation.start is not None and citation.end is not None
    assert text[citation.start:citation.end] == citation.quote
    assert citation.quote.strip()


@pytest.mark.parametrize("evidence_id", ["d1:f99", "other-case:f01", "d1-02"])
def test_resolution_rejects_unknown_or_foreign_fragment_ids(evidence_id):
    _, index = fragment_documents(docs(), 200, 4)
    with pytest.raises(ValueError):
        resolve_fragment_citations([FragmentCitation(evidence_id=evidence_id)], index)


def test_fast_run_resolves_spans_and_keeps_the_result_schema():
    provider, seen = capture()
    result = Engine(provider).run(case(), v1_fast_config("native"))
    assert result.status == "completed"
    RunResult.model_validate_json(result.model_dump_json())
    assert all("text" not in entry for entry in seen["payloads"][0]["sources"])
    assert seen["payloads"][0]["evidence"]
    assert "evidence_id" in seen["systems"][0] and "exact source quote" not in seen["systems"][0]
    cited = [c for report in result.reports for finding in report.output.findings for c in finding.citations]
    assert cited and all(c.start is not None and c.quote for c in cited)
    usage = [e for e in result.trace if e.kind == "model_usage"]
    assert len(usage) == 7
    assert all(isinstance(e.details["seconds"], float) and e.details["seconds"] >= 0 for e in usage)
    assert all(e.details["evidence_fragments"] >= 1 for e in usage)
    assert all(e.details["attempts"] == 1 for e in usage)


def long_source_case():
    model = case().model_dump()
    model["documents"][0]["text"] = "Sentence describing fictional tumour markers. " * 700
    from oncofusion.schemas import CaseInput
    return CaseInput.model_validate(model)


def sent_source_chars(payload):
    return sum(len(entry.get("text", "")) for entry in payload["sources"]) + \
        sum(len(entry["text"]) for entry in payload.get("evidence", []))


def test_fast_payload_carries_less_source_text_than_quote_mode():
    long_case = long_source_case()
    full = len(long_case.documents[0].text)
    quote_provider, quote_seen = capture()
    Engine(quote_provider).run(long_case, v1_config("native"))
    fast_provider, fast_seen = capture()
    Engine(fast_provider).run(long_case, v1_fast_config("native"))
    assert sent_source_chars(quote_seen["payloads"][0]) >= full
    assert "evidence" not in quote_seen["payloads"][0]
    assert "source_characters" not in quote_seen["payloads"][0]
    # bounded fragments per document, and the roster still reports the real source length
    assert sent_source_chars(fast_seen["payloads"][0]) < full
    assert fast_seen["payloads"][0]["source_characters"][long_case.documents[0].id] == full
    assert len(json.dumps(fast_seen["payloads"][0], ensure_ascii=False)) < \
        len(json.dumps(quote_seen["payloads"][0], ensure_ascii=False))


def test_future_source_is_never_offered_as_citable_evidence():
    source = case()
    model = source.model_dump()
    model["documents"].append({"id": "future-doc", "origin_id": "future", "kind": "clinical",
                               "text": "FUTURE_CANARY result measured later.", "available_stage": 99})
    from oncofusion.schemas import CaseInput
    provider, seen = capture()
    Engine(provider).run(CaseInput.model_validate(model), v1_fast_config("native"))
    offered = {entry["document_id"] for payload in seen["payloads"] for entry in payload["evidence"]}
    assert "future-doc" not in offered
    assert "FUTURE_CANARY" not in json.dumps(seen["payloads"], ensure_ascii=False)


def test_model_citing_an_unlisted_fragment_fails_the_run():
    provider = MockProvider()

    def complete(system, payload, max_tokens, temperature, seed):
        if payload["role"] == "decision":
            body = {"answer": "SUPPORTS", "explanation": "traced", "unresolved": [], "confidence": None,
                    "citations": [{"evidence_id": "invented:f01"}]}
        else:
            body = {"findings": [{"statement": "observed", "relation": "SUPPORTS",
                                  "citations": [{"evidence_id": "invented:f01"}]}],
                    "unresolved": [], "requery": ""}
        content = json.dumps(body)
        return ModelReply(content, 10, len(content) // 4, 1, False)

    provider.complete = complete
    config = v1_fast_config("native").model_copy(update={"schema_retries": 0})
    with pytest.raises(ProviderError):
        Engine(provider).run(case(), config)


def test_fragment_mode_requires_external_verification():
    provider, _ = capture()
    config = v1_fast_config("native").model_copy(
        update={"ablations": Ablations(targeted_requery=False, external_verification=False)})
    with pytest.raises(ValueError):
        Engine(provider).run(case(), config)


def test_board_carries_handles_not_resolved_quote_text():
    long_case = long_source_case()
    provider, seen = capture()
    Engine(provider).run(long_case, v1_fast_config("native"))
    payloads = seen["payloads"]
    boards = [pl["board"] for pl in payloads[1:] if pl["board"]]
    assert boards
    for board in boards:
        for finding in board:
            for citation in finding["citations"]:
                assert "quote" not in citation
                assert "evidence_id" in citation or {"document_id", "start", "end"} <= set(citation)
    handle_board_chars = sum(len(json.dumps(b, ensure_ascii=False)) for b in boards)
    evidence_chars = sum(len(json.dumps(pl["evidence"], ensure_ascii=False)) for pl in payloads[1:])
    assert handle_board_chars < evidence_chars


def test_cross_role_recite_of_a_board_handle_still_resolves():
    long_case = long_source_case()
    provider = MockProvider()
    original = provider.complete
    recited = []

    def complete(system, payload, max_tokens, temperature, seed):
        reply = original(system, payload, max_tokens, temperature, seed)
        if payload["board"]:
            handle = payload["board"][0]["citations"][0].get("evidence_id")
            if handle:
                body = json.loads(reply.content)
                if body.get("findings"):
                    body["findings"][0]["citations"] = [{"evidence_id": handle}]
                    recited.append(handle)
                    reply.content = json.dumps(body)
        return reply

    provider.complete = complete
    result = Engine(provider).run(long_case, v1_fast_config("native"))
    assert recited, "the scripted provider never saw a board handle"
    assert result.status == "completed"
    spans = {(c.document_id, c.start, c.end) for r in result.reports for f in r.output.findings for c in f.citations}
    assert spans and all(c.quote == long_case.documents[0].text[c.start:c.end]
                         for r in result.reports for f in r.output.findings for c in f.citations)
