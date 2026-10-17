import json
import pytest
from oncofusion.config import presets
from oncofusion.engine import DUTIES, Engine
from oncofusion.evidence import check_citations, visible_case
from oncofusion.examples import examples
from oncofusion.providers import MockProvider, ModelReply, ProviderError
from oncofusion.schemas import Ablations, AnalysisOutput, DecisionOutput, ROLES, RunConfig


@pytest.mark.parametrize("name", list(presets()))
@pytest.mark.parametrize("example", list(examples()))
def test_all_presets_end_to_end(name, example):
    case = examples()[example]
    result = Engine(MockProvider()).run(case, presets()[name])
    assert result.status == "completed"
    assert result.simulated and result.research_only
    assert result.decision is not None
    assert result.usage.calls <= result.config.max_calls
    assert result.usage.tool_calls <= result.config.max_tool_calls
    assert result.usage.cost_usd == 0
    assert "FUTURE_CANARY" not in result.model_dump_json()
    check_citations(result.decision.citations, visible_case(case).documents)
    for report in result.reports:
        for finding in report.output.findings:
            check_citations(finding.citations, visible_case(case).documents)


@pytest.mark.parametrize("example,answer", [("synthetic-support", "SUPPORTS"), ("synthetic-refute", "REFUTES"),
                                           ("synthetic-nei", "NEI"), ("synthetic-timeline", "A")])
def test_synthetic_fixture_contract(example, answer):
    assert Engine(MockProvider()).run(examples()[example]).decision.answer == answer


def test_reproducible(case):
    a, b = Engine(MockProvider()).run(case), Engine(MockProvider()).run(case)
    assert a.fingerprint == b.fingerprint
    assert a.decision == b.decision
    assert a.trace == b.trace
    assert Engine(MockProvider()).run(case, RunConfig(seed=3)).fingerprint != a.fingerprint


def test_no_future_or_unretrieved_literature_in_early_payloads(case, recorder):
    Engine(recorder).run(case)
    for payload in recorder.payloads:
        assert "FUTURE_CANARY" not in json.dumps(payload)
        if payload["role"] in ("timeline", "genomics", "pathology", "drug"):
            assert all(d["kind"] != "literature" for d in payload["sources"])
            assert "paper1" not in json.dumps(payload)


@pytest.mark.parametrize("feature", list(Ablations.model_fields))
def test_each_feature_changes_executable_representation(case, recorder, feature):
    if feature == "source_deduplication":
        case.documents.append(case.documents[2].model_copy(update={"id": "clone"}))
    config = RunConfig(ablations=Ablations(**{feature: False}))
    result = Engine(recorder).run(case, config)
    final = recorder.payloads[-1]
    if feature == "variant_normalization":
        assert "canonical_variant" not in final["signals"]
        assert final["signals"]["matches"]["paper1"]["variant"] == "mismatch"
    elif feature == "disease_matching":
        assert all("disease" not in m for m in final["signals"]["matches"].values())
    elif feature == "drug_polarity":
        assert final["signals"]["directions"] == {}
    elif feature == "timeline_structure":
        assert "timeline" not in final["signals"]
    elif feature == "external_verification":
        payload = next(p for p in recorder.payloads if p["role"] == "verifier")
        assert payload["sources"] == [] and payload["signals"] == {}
        assert payload["board"]
    elif feature == "structured_board":
        assert isinstance(final["board"], str)
        assert all(isinstance(json.loads(line), dict) for line in final["board"].splitlines())
    elif feature == "source_deduplication":
        assert "clone" in [d["id"] for d in final["sources"]]
    elif feature == "targeted_requery":
        assert all(e.kind != "requery_requested" for e in result.trace)
    else:
        assert result.config.ablations.retrieval_reranking is False


@pytest.mark.parametrize("role", ROLES)
def test_role_delegation_preserves_sources_and_tools(case, recorder, role):
    result = Engine(recorder).run(case, RunConfig(delegated_roles=[role]))
    event = next(e for e in result.trace if e.kind == "agent_started" and e.role == role)
    assert event.details["executor"] == "generalist"
    index = next(i for i, p in enumerate(recorder.payloads) if p["role"] == role)
    assert DUTIES[role] not in recorder.systems[index]
    assert result.visible_document_ids == [d.id for d in visible_case(case).documents]
    assert result.usage.tool_calls == 6


@pytest.mark.parametrize("mode,calls,tools", [("single_direct", 1, 0), ("single_tools", 1, 6), ("single_iterative", 7, 6)])
def test_baseline_budgets(case, mode, calls, tools):
    result = Engine(MockProvider()).run(case, RunConfig(mode=mode))
    assert result.usage.calls == calls and result.usage.tool_calls == tools


@pytest.mark.parametrize("config,calls", [(RunConfig(max_calls=1), 1), (RunConfig(max_tool_calls=1), 1),
                                        (RunConfig(max_total_tokens=100), 0)])
def test_budget_exhaustion_is_explicit(case, config, calls):
    result = Engine(MockProvider()).run(case, config)
    assert result.status == "budget_exhausted" and result.decision is None
    assert result.usage.calls == calls
    assert any(e.kind == "budget_exhausted" for e in result.trace)


def test_requery_bounded():
    case = examples()["synthetic-nei"]
    result = Engine(MockProvider()).run(case)
    assert sum(e.kind == "requery_requested" for e in result.trace) == 1
    assert result.usage.calls == 9
    no = Engine(MockProvider()).run(case, RunConfig(ablations=Ablations(targeted_requery=False)))
    assert no.usage.calls == 7


def test_adaptive_skip():
    case = examples()["synthetic-nei"]
    case.entities = case.entities.model_copy(update={"gene": "", "disease": "", "drug": ""})
    result = Engine(MockProvider()).run(case, RunConfig(routing="adaptive"))
    assert sum(e.kind == "agent_skipped" for e in result.trace) == 4
    assert result.usage.calls < 9


class CorruptProvider(MockProvider):
    def __init__(self, content):
        super().__init__()
        self.content = content
    def complete(self, *args):
        return ModelReply(self.content, 10, 10)


@pytest.mark.parametrize("content", ["not json", "{}", '{"answer":"INVALID","explanation":"x"}',
                                   '{"answer":"SUPPORTS","explanation":"x","citations":[]}',
                                   '{"answer":"NEI","explanation":"x","citations":[{"document_id":"future","start":0,"end":5,"quote":"wrong"}]}'])
def test_invalid_model_answers_fail(case, content):
    with pytest.raises(ProviderError):
        Engine(CorruptProvider(content)).run(case, RunConfig(mode="single_direct"))


def test_invalid_mcq_answer_fails():
    output = DecisionOutput(answer="Z", explanation="invalid key").model_dump_json()
    with pytest.raises(ProviderError):
        Engine(CorruptProvider(output)).run(examples()["synthetic-timeline"], RunConfig(mode="single_direct"))


def test_unsupported_claim_requires_citation(case):
    output = AnalysisOutput(findings=[{"statement": "unsupported", "relation": "SUPPORTS", "citations": []}]).model_dump_json()
    with pytest.raises(ProviderError):
        Engine(CorruptProvider(output)).run(case)


def test_reported_usage_stops_next_call(case):
    class HugeProvider(MockProvider):
        def complete(self, *args):
            return ModelReply(AnalysisOutput().model_dump_json(), 200_000, 100)
    result = Engine(HugeProvider()).run(case)
    assert result.status == "budget_exhausted" and result.usage.calls == 1


def test_event_callback(case):
    captured = []
    result = Engine(MockProvider()).run(case, on_event=captured.append)
    assert captured == result.trace
    assert [e.sequence for e in captured] == list(range(len(captured)))


def test_requery_retains_previously_seen_sources(case, monkeypatch, recorder):
    from oncofusion.schemas import Document
    case.documents.append(Document(id="paper2", origin_id="paper2", kind="literature",
                                   text="Second targeted source describes GENE1.", entities=case.entities))
    calls = []
    def alternating(query, documents, *args):
        calls.append(query)
        return [next(d for d in documents if d.id == ("paper1" if len(calls) == 1 else "paper2"))]
    monkeypatch.setattr("oncofusion.engine.retrieve", alternating)
    original = recorder.complete
    def force_query(system, payload, max_tokens, temperature, seed):
        reply = original(system, payload, max_tokens, temperature, seed)
        if payload["role"] == "verifier":
            parsed = AnalysisOutput.model_validate_json(reply.content)
            parsed.requery = "focused second source"
            reply.content = parsed.model_dump_json()
        return reply
    recorder.complete = force_query
    result = Engine(recorder).run(case)
    assert result.status == "completed"
    assert len(calls) == 2
    assert {"paper1", "paper2"} <= {d["id"] for d in recorder.payloads[-1]["sources"]}


def test_large_mock_reply_respects_output_cap(case):
    case.documents = [d.model_copy(update={"text": d.text * 10}) for d in case.documents]
    result = Engine(MockProvider()).run(case, RunConfig(max_output_tokens=1500))
    assert all(e.details["output_tokens"] <= 1500 for e in result.trace if e.kind == "model_usage")


def test_synthesis_explicit_mock():
    case = examples()["synthetic-support"]
    case.task = "synthesis"
    result = Engine(MockProvider()).run(case)
    assert "Synthetic evidence summary" in result.decision.answer


def test_raw_mtb_preprocessing_active_without_query_entities(recorder):
    from oncofusion.schemas import CaseInput, Document
    case = CaseInput(id="raw-mtb", patient_id="p", task="mcq", question="Which status is documented?", options={"A": "Stable", "B": "Progression"},
                     documents=[Document(id="g", origin_id="g", kind="genomics", text="BRAF p.Val600Glu"),
                                Document(id="p", origin_id="p", kind="pathology", text="CANCER_TYPE: Lung Cancer")])
    Engine(recorder).run(case)
    final = recorder.payloads[-1]
    assert final["signals"]["source_variant_mentions"][0]["canonical"] == "V600E"
    assert final["signals"]["pathology_context"][0]["value"] == "Lung Cancer"
    recorder.payloads.clear()
    Engine(recorder).run(case, RunConfig(ablations=Ablations(variant_normalization=False, disease_matching=False)))
    assert "source_variant_mentions" not in recorder.payloads[-1]["signals"]
    assert "pathology_context" not in recorder.payloads[-1]["signals"]
