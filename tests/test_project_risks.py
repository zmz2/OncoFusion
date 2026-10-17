"""Independent regressions found during the whole-project review."""
import copy
import json

import httpx
import pytest

from oncofusion.datasets import GoldRecord
from oncofusion.engine import Engine
from oncofusion.evaluation import evaluate
from oncofusion.providers import MockProvider, OpenAICompatibleProvider, ProviderError
from oncofusion.schemas import CaseInput, Document, RunConfig


def example(cid="a", options=None):
    return CaseInput(id=cid, patient_id=cid, task="mcq", question="Which observation is supported?",
                     options=options or {"A": "response", "B": "progression"}, data_class="synthetic",
                     documents=[Document(id="note", origin_id="note", kind="clinical", text="Progression was observed.")])


class Recorder(MockProvider):
    def __init__(self):
        super().__init__()
        self.seen = []
    def complete(self, system, payload, *args):
        self.seen.append(copy.deepcopy(payload))
        return super().complete(system, payload, *args)


def test_gold_must_belong_to_its_own_question_options():
    a, b = example(), example("b", {"A": "response", "B": "progression", "C": "stable"})
    provider = Recorder()
    with pytest.raises(ValueError, match="case|option"):
        evaluate([a, b], [GoldRecord(case_id="a", label="C", group_id="a"),
                           GoldRecord(case_id="b", label="C", group_id="b")],
                 Engine(provider), RunConfig())
    assert provider.seen == []


def test_same_patient_cannot_cross_gold_groups_and_splits():
    a, b = example(), example("b")
    b.patient_id = a.patient_id
    provider = Recorder()
    with pytest.raises(ValueError, match="patient"):
        evaluate([a,b], [GoldRecord(case_id="a", label="A", group_id="one", split="dev"),
                         GoldRecord(case_id="b", label="B", group_id="two", split="test")],
                 Engine(provider), RunConfig())
    assert provider.seen == []


def test_truncated_response_usage_is_preserved():
    def reply(request):
        return httpx.Response(200, json={"choices":[{"message":{"content":"{bad"}, "finish_reason":"length"}],
                                        "usage":{"prompt_tokens":123,"completion_tokens":45}})
    provider=OpenAICompatibleProvider("http://localhost/v1", "fake", "not-real", retries=0,
                                      transport=httpx.MockTransport(reply), input_price=1, output_price=2)
    report=evaluate([example()], [GoldRecord(case_id="a",label="B",group_id="a")], Engine(provider),RunConfig())
    assert report["failed_or_incomplete"] == 1
    assert report["efficiency"]["total_input_tokens"] == 123
    assert report["efficiency"]["total_output_tokens"] == 45
    assert report["efficiency"]["known_cost_usd"] == pytest.approx(0.000213)


def test_semantically_invalid_body_preserves_reported_usage():
    def reply(request):
        return httpx.Response(200,json={"choices":[{"message":{"content":None}}],
                                       "usage":{"prompt_tokens":10,"completion_tokens":2}})
    provider=OpenAICompatibleProvider("http://localhost/v1","fake","not-real",retries=0,
                                      transport=httpx.MockTransport(reply))
    events=[]
    with pytest.raises(ProviderError):
        Engine(provider).run(example(),RunConfig(),events.append)
    usage=[e.details for e in events if e.kind=="model_usage"]
    assert usage and usage[0]["input_tokens"] == 10


def test_unreviewed_case_blocked_before_remote_request():
    called=[]
    provider=OpenAICompatibleProvider("http://localhost/v1","fake","not-real",retries=0,
                    transport=httpx.MockTransport(lambda r: called.append(r)))
    case=example(); case.data_class="unreviewed"
    with pytest.raises(ValueError, match="review"):
        Engine(provider).run(case)
    assert called == []


def test_loader_checks_patient_groups_before_split_selection(tmp_path):
    from oncofusion.evaluation import load_evaluation
    a, b = example(), example("b")
    b.patient_id = a.patient_id
    inputs, labels = tmp_path / "inputs.jsonl", tmp_path / "labels.jsonl"
    inputs.write_text("\n".join(c.model_dump_json() for c in (a, b)))
    labels.write_text("\n".join(g.model_dump_json() for g in (
        GoldRecord(case_id="a", label="A", group_id="one", split="dev"),
        GoldRecord(case_id="b", label="B", group_id="two", split="test"))))
    with pytest.raises(ValueError, match="patient"):
        load_evaluation(inputs, labels)
