"""Regressions found by the v1 scientific/engineering audit; fictional records only."""
import json

import httpx
import pytest

from oncofusion.datasets import GoldRecord
from oncofusion.engine import Engine
from oncofusion.evaluation import evaluate
from oncofusion.examples import examples
from oncofusion.providers import MockProvider, OpenAICompatibleProvider
from oncofusion.schemas import CaseInput, Document, RunConfig


def test_duplicates_do_not_consume_literature_slots(recorder):
    original = Document(id='a', origin_id='source-a', kind='literature', text='oncology drug sensitivity')
    duplicate = original.model_copy(update={'id': 'a-copy'})
    counter = Document(id='z', origin_id='source-b', kind='literature', text='oncology drug resistance')
    case = CaseInput(id='duplicates', patient_id='p', task='verification',
                     question='oncology drug', documents=[original, duplicate, counter])
    result = Engine(recorder).run(case, RunConfig(top_k=2, candidate_k=2, evidence_first=True))
    retrieved = next(e.details['ranked_ids'] for e in result.trace if e.kind == 'retrieval_completed')
    assert set(retrieved) == {'a', 'z'}


@pytest.mark.parametrize('limits', [{'max_calls': 7}, {'max_calls': 8}, {'max_tool_calls': 6}])
def test_optional_requery_preserves_final_decision(limits):
    result = Engine(MockProvider()).run(examples()['synthetic-nei'], RunConfig(**limits))
    assert result.status == 'completed'
    assert result.decision is not None
    assert result.usage.calls == 7
    assert any(e.kind == 'requery_skipped' for e in result.trace)


def test_revision_vocabulary_reaches_every_specialist(recorder):
    case = examples()['synthetic-support']
    case.verification_scheme = 'revisions'
    Engine(recorder).run(case, RunConfig(evidence_first=True))
    for payload, system in zip(recorder.payloads, recorder.systems):
        assert 'REVISIONS means partial support' in system
        raw = system.split('Return JSON only, conforming to this schema: ', 1)[1]
        schema = json.JSONDecoder().raw_decode(raw)[0]
        if payload['role'] != 'decision':
            assert schema['$defs']['Finding']['properties']['relation']['enum'] == ['SUPPORTS', 'REVISIONS', 'NEI']


def test_patient_alias_cannot_bypass_split_isolation():
    first = examples()['synthetic-support']
    second = first.model_copy(update={'id': 'second'}, deep=True)
    gold = [GoldRecord(case_id=first.id, group_id='alias-1', label='SUPPORTS', split='dev'),
            GoldRecord(case_id=second.id, group_id='alias-2', label='SUPPORTS', split='test')]
    with pytest.raises(ValueError, match='patient|group'):
        evaluate([first, second], gold, Engine(MockProvider()), RunConfig())


def test_truncated_provider_usage_remains_counted():
    def handler(request):
        return httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': '{'}}],
                                        'usage': {'prompt_tokens': 500, 'completion_tokens': 60}})
    provider = OpenAICompatibleProvider('https://example.test/v1', 'test-model', 'test-key', retries=0,
                                       input_price=1., output_price=2., transport=httpx.MockTransport(handler))
    case = examples()['synthetic-support']
    gold = [GoldRecord(case_id=case.id, group_id=case.patient_id, label='SUPPORTS')]
    report = evaluate([case], gold, Engine(provider), RunConfig(mode='single_direct'))
    assert report['failed_or_incomplete'] == 1
    assert report['efficiency']['total_input_tokens'] == 500
    assert report['efficiency']['total_output_tokens'] == 60
    assert report['efficiency']['known_cost_usd'] == pytest.approx(.00062)
