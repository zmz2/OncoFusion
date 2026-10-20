"""Regression for the v1_fast evidence-fragment citation path (mock model, no network)."""
import copy
import json

import pytest

from oncofusion.engine import Engine
from oncofusion.evidence import fragment_documents, fragment_spans, resolve_fragment_citations
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
    """Ids number positions in the whole document; the sent subset is stable and ordered."""
    listed, index, coverage = fragment_documents(docs(), 200, 4)
    again, _, _ = fragment_documents(docs(), 200, 4)
    assert listed == again
    numbers = [int(f["evidence_id"].rsplit("f", 1)[1]) for f in listed]
    assert numbers == sorted(numbers)
    assert len(listed) <= 4
    assert set(index) == {f["evidence_id"] for f in listed}
    assert coverage["candidates"] >= coverage["sent"]
    assert coverage["documents"]["d1"]["candidates"] == max(numbers)
    # the newest record of the document is part of the candidate numbering and is sent
    assert max(numbers) == coverage["documents"]["d1"]["candidates"]


def test_newlines_advance_one_character_so_records_are_not_clipped():
    """A record boundary consumes exactly one character, so no record loses its first letter."""
    text = "AGE: 52.0, first record\nAGE: 53.0, second record\nAGE: 54.0, third record\n"
    doc = [Document(id="d9", origin_id="d9", kind="clinical", text=text, available_stage=1)]
    spans = fragment_spans(text, 26)
    assert "".join(text[s:e] for s, e in spans) == text
    assert [text[s:s + 5] for s, _ in spans] == ["AGE: "] * len(spans)
    assert spans[-1][1] == len(text)
    listed, index, coverage = fragment_documents(doc, 26, 8, "AGE 53")
    assert coverage["chars_sent"] == len(text) and not coverage["tail_dropped"]
    assert "".join(f["text"] for f in listed) == text
    for fragment in listed:
        assert not fragment["text"].lstrip().startswith("GE"), fragment["text"][:12]
        ref, s, e = index[fragment["evidence_id"]]
        assert ref.text[s:e] == fragment["text"]
    over_long = "AGE: 52.0, " + "word " * 40 + "\nAGE: 53.0, next\n"
    long_doc = [Document(id="d10", origin_id="d10", kind="clinical", text=over_long, available_stage=1)]
    cut_spans = fragment_spans(over_long, 48)
    for s, _ in cut_spans[1:]:
        assert over_long[s - 1] in " \n", repr(over_long[max(0, s - 8):s + 8])
    sent = fragment_documents(long_doc, 48, 8, "AGE 53")[0]
    assert "".join(f["text"] for f in sent) == over_long
    assert any("AGE: 53.0, next" in f["text"] for f in sent)


def test_candidates_cover_the_whole_document_and_selection_respects_the_budget():
    text = "\n".join("AGE: %.2f, record number %d with some body text" % (50 + i / 10, i) for i in range(60))
    doc = [Document(id="d8", origin_id="d8", kind="clinical", text=text, available_stage=1)]
    _, _, full = fragment_documents(doc, 600, 1000, "AGE 55")
    assert full["chars_sent"] == len(text) and not full["tail_dropped"]
    listed, index, cov = fragment_documents(doc, 600, 8, "recurrence risk of AGE 55.9", budget=2400)
    assert cov["chars_sent"] <= 2400 + 600
    assert cov["documents"]["d8"]["sent"] <= 8
    # forced spans keep the last record even when the question is about something else
    assert any("record number 59" in f["text"] for f in listed)
    assert all(f["evidence_id"] in index for f in listed)


def test_a_fragment_that_was_not_sent_cannot_be_cited():
    text = "\n".join("AGE: %.2f, record %d" % (50 + i / 10, i) for i in range(60))
    doc = [Document(id="d7", origin_id="d7", kind="clinical", text=text, available_stage=1)]
    listed, index, cov = fragment_documents(doc, 600, 2, "record 30", budget=1200)
    missing = "%s:f05" % doc[0].id
    assert missing not in index
    try:
        resolve_fragment_citations([FragmentCitation(evidence_id=missing)], index)
    except ValueError as error:
        assert "was not supplied for this stage" in str(error)
    else:
        raise AssertionError("an unsent fragment id must not resolve")


def test_resolution_backfills_the_exact_source_span():
    listed, index, _ = fragment_documents(docs(), 200, 4)
    citation = resolve_fragment_citations([FragmentCitation(evidence_id="d1:f02")], index)[0]
    text = docs()[0].text
    assert citation.document_id == "d1"
    assert citation.start is not None and citation.end is not None
    assert text[citation.start:citation.end] == citation.quote
    assert citation.quote.strip()


@pytest.mark.parametrize("evidence_id", ["d1:f99", "other-case:f01", "d1-02"])
def test_resolution_rejects_unknown_or_foreign_fragment_ids(evidence_id):
    _, index, _ = fragment_documents(docs(), 200, 4)
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
    by_id = {d.id: d.text for d in long_case.documents}
    assert spans and all(c.quote == by_id[c.document_id][c.start:c.end]
                         for r in result.reports for f in r.output.findings for c in f.citations)
