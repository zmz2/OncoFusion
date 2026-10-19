"""First-release scope and boundary regressions. All biomedical records are fictional."""
import json
from pathlib import Path
from importlib.metadata import PackageNotFoundError

import httpx
import pytest
from fastapi.testclient import TestClient

from oncofusion.api import create_app
from oncofusion.datasets import GoldRecord
from oncofusion.engine import Engine
from oncofusion.evaluation import evaluate, load_evaluation
from oncofusion.examples import examples
from oncofusion.experiments import StudyPlan, select_cases
from oncofusion.profiles import (coverage_report, inspect_case, integration_example, profile_catalog, v1_config, available_backend)
from oncofusion.providers import MockProvider, ModelReply, OpenAICompatibleProvider, ProviderError
from oncofusion.schemas import CaseInput, Document, RunConfig
from oncofusion.upstream_tools import TOOL_VERSION, SourcePlan, ToolRequest, ToolUniverseSources, attach_snapshot
from oncofusion.workflow import specification
from test_api_store_cli import wait_for
from test_upstream_tools import SDK


ROOT = Path(__file__).resolve().parents[1]


def test_v1_fixed_seven_roles_and_no_optional_requery():
    config = v1_config('native')
    result = Engine(MockProvider()).run(integration_example(), config)
    assert result.status == 'completed'
    assert [r.role for r in result.reports] == ['literature','timeline','genomics','pathology','drug','verifier']
    assert result.usage.calls == 7 and result.decision
    assert not any(e.kind == 'requery_requested' for e in result.trace)
    assert specification(config)['max_requeries'] == 0
    # the catalog advertises the backend this interpreter can actually run, and says whether
    # LangGraph is installed; the classroom service is the same code path either way.
    assert profile_catalog()['v1']['config']['workflow_backend'] == available_backend()
    assert profile_catalog()['v1']['graph_installed'] == (available_backend() == 'langgraph')


def test_readiness_distinguishes_component_and_heterogeneous_input():
    integrated = inspect_case(integration_example())
    component_case = examples()['synthetic-support']
    component_case.documents = [d for d in component_case.documents if d.kind == 'literature']
    component = inspect_case(component_case)
    assert integrated['heterogeneous_document_input']
    assert not integrated['roles_without_explicit_inputs']
    assert integrated['distinct_literature_candidates'] == 2
    assert not component['heterogeneous_document_input']
    assert component['warnings']
    assert coverage_report([integration_example(), component_case])['heterogeneous_input_cases'] == 1


def test_readiness_does_not_count_future_or_duplicate_evidence():
    case = examples()['synthetic-support']
    case.documents = [d for d in case.documents if d.kind == 'literature']
    first = case.documents[0]
    case.documents += [first.model_copy(update={'id':'copy'}), Document(
        id='future', origin_id='future-origin', kind='genomics', text='FUTURE_CANARY', available_stage=99)]
    result = inspect_case(case)
    assert result['distinct_literature_candidates'] == 1
    assert 'genomics' not in result['visible_document_kinds']
    assert 'FUTURE_CANARY' not in json.dumps(result)


def test_empty_input_has_no_false_evidence_readiness():
    case = CaseInput(id='empty', patient_id='p', question='What evidence is available?', task='synthesis')
    result = inspect_case(case)
    assert result['visible_document_count'] == 0
    assert not any(result['explicit_role_inputs'].values())
    assert len(result['warnings']) >= 3
    assert coverage_report([])['cases'] == 0


def test_profile_inspection_does_not_persist_or_submit(client):
    assert client.get('/v1/profiles').status_code == 200
    case = client.get('/v1/profiles/v1/example').json()
    response = client.post('/v1/cases/inspect', json=case)
    assert response.status_code == 200
    assert response.json()['heterogeneous_document_input']
    assert client.get('/v1/cases').json() == client.get('/v1/runs').json() == []


@pytest.mark.parametrize('path', ['/v1/profiles', '/v1/profiles/v1/example'])
def test_profile_endpoints_use_same_auth(tmp_path, path):
    with TestClient(create_app(tmp_path/'auth.db', MockProvider(), api_token='secret')) as client:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={'Authorization':'Bearer secret'}).status_code == 200


def test_missing_graph_is_rejected_before_job_or_case_is_created(client, monkeypatch):
    import oncofusion.workflow as workflow
    def missing(_):
        raise PackageNotFoundError('langgraph')
    monkeypatch.setattr(workflow, 'version', missing)
    response = client.post('/v1/runs', json={'example_id':'synthetic-support',
                                             'config':v1_config('langgraph').model_dump()})
    assert response.status_code == 503
    assert client.get('/v1/cases').json() == client.get('/v1/runs').json() == []


def test_final_decision_is_present_in_evidence_graph(client):
    response = client.post('/v1/runs', json={'case':integration_example().model_dump(), 'config':v1_config('native').model_dump()})
    rid = response.json()['run_id']
    completed = wait_for(client, rid)
    assert completed['status'] == 'succeeded'
    graph = client.get(f'/v1/runs/{rid}/graph').json()
    decision = next(n for n in graph['nodes'] if n['id'] == 'decision')
    assert decision['answer'] == completed['result']['decision']['answer']
    citations = completed['result']['decision']['citations']
    assert len([e for e in graph['edges'] if e['target'] == 'decision']) == len(citations)


def test_unreviewed_remote_case_is_rejected_before_provider_and_persistence(tmp_path, recorder):
    recorder.simulated = False
    case = integration_example().model_copy(update={'data_class':'unreviewed'})
    with pytest.raises(ValueError, match='review'):
        Engine(recorder).run(case, v1_config('native'))
    with TestClient(create_app(tmp_path/'review.db', recorder)) as client:
        response = client.post('/v1/runs', json={'case':case.model_dump(), 'allow_remote_processing':True})
        assert response.status_code == 422
        assert client.get('/v1/runs').json() == client.get('/v1/cases').json() == []
    assert recorder.payloads == []


@pytest.mark.parametrize('dataset', ['mtb','civic'])
@pytest.mark.parametrize('phase,count,repeats', [('smoke',3,1),('ablations',11,3)])
def test_v1_plans_are_small_and_comparable(dataset, phase, count, repeats):
    plan = StudyPlan.model_validate_json((ROOT/f'experiments/v1_{dataset}_{phase}.json').read_text())
    assert plan.split == 'dev'
    assert len(plan.treatments) == count and len(plan.seeds) == repeats
    configs = [t.config(0) for t in plan.treatments]
    assert {c.workflow_backend for c in configs} == {'langgraph'}
    assert len({(c.max_calls,c.max_tool_calls,c.max_total_tokens,c.max_output_tokens) for c in configs}) == 1
    assert all(c.evidence_first and not c.ablations.targeted_requery for c in configs)


def test_patient_alignment_checked_before_selecting_or_reading_split(tmp_path):
    a = examples()['synthetic-support']
    b = a.model_copy(update={'id':'other'}, deep=True)
    gold = [GoldRecord(case_id=a.id,group_id='one',label='SUPPORTS',split='dev'),
            GoldRecord(case_id=b.id,group_id='two',label='SUPPORTS',split='test')]
    plan = StudyPlan.model_validate_json((ROOT/'experiments/v1_civic_smoke.json').read_text())
    with pytest.raises(ValueError, match='patient|group'):
        select_cases([a,b], gold, plan)
    inputs, labels = tmp_path/'inputs.jsonl', tmp_path/'labels.jsonl'
    inputs.write_text('\n'.join(c.model_dump_json() for c in [a,b]))
    labels.write_text('\n'.join(g.model_dump_json() for g in gold))
    with pytest.raises(ValueError, match='patient|group'):
        load_evaluation(inputs, labels)


def test_mcq_gold_must_be_in_its_own_case_not_another_cases_options(recorder):
    a = CaseInput(id='a',patient_id='pa',question='Q?',task='mcq',options={'A':'yes','B':'no'},data_class='synthetic')
    b = a.model_copy(update={'id':'b','patient_id':'pb','options':{'C':'yes','D':'no'}})
    gold = [GoldRecord(case_id='a',group_id='pa',label='C'), GoldRecord(case_id='b',group_id='pb',label='C')]
    with pytest.raises(ValueError, match='vocabulary'):
        evaluate([a,b],gold,Engine(recorder),RunConfig())
    assert recorder.payloads == []


def test_schema_repair_uses_original_invalid_output_and_validation_errors(recorder):
    original = recorder.complete
    seen = []
    def complete(system, payload, *args):
        seen.append(payload)
        if len(seen) == 1:
            return ModelReply('{"bad_field":"test"}',10,5)
        return original(system,payload,*args)
    recorder.complete = complete
    result = Engine(recorder).run(examples()['synthetic-support'], RunConfig(mode='single_direct',schema_retries=1))
    assert result.status == 'completed'
    assert result.usage.calls == 2
    repair = seen[1]['repair']
    assert repair['previous_output'] == '{"bad_field":"test"}'
    assert repair['validation_errors'] and not repair['output_truncated_in_trace']
    assert all('input' not in e for e in repair['validation_errors'])


@pytest.mark.parametrize('value', [{'choices':[]}, {'choices':[{'message':{'content':None}}]},
                                  {'choices':[{'finish_reason':'content_filter','message':{'content':''}}]}])
def test_invalid_success_envelope_preserves_observed_usage(value):
    value['usage'] = {'prompt_tokens':19,'completion_tokens':3}
    p = OpenAICompatibleProvider('https://example.test/v1','m','k',retries=0,
        transport=httpx.MockTransport(lambda _: httpx.Response(200,json=value)))
    with pytest.raises(ProviderError) as error:
        p.complete('system', {'question':'Q'},20,0,0)
    assert error.value.observed_reply.input_tokens == 19
    assert error.value.observed_reply.output_tokens == 3


def test_reactome_empty_membership_is_valid_negative_lookup():
    class ReactomeSDK(SDK):
        def tool_specification(self, name, format):
            key = 'uniprot_id' if name == 'Reactome_map_uniprot_to_pathways' else 'stId'
            return {'name':name, 'parameters':{'type':'object','required':[key], 'properties':{key:{'type':'string'}}}}
    request = ToolRequest(name='Reactome_map_uniprot_to_pathways', arguments={'uniprot_id':'P15056'})
    plan = SourcePlan(requests=[request],public_queries_reviewed=True,source_terms_accepted=True)
    snapshot = ToolUniverseSources(ReactomeSDK([]),TOOL_VERSION).collect(plan)
    assert snapshot['records'][0]['result_status'] == 'no_results'
    case = attach_snapshot(integration_example(),snapshot)
    assert case.documents[-1].kind == 'genomics'
    assert '"response":[]' in case.documents[-1].text


def test_repeat_sources_without_dedup_is_explicit_ablation(recorder):
    case = examples()['synthetic-support']
    first = case.documents[0]
    case.documents.append(first.model_copy(update={'id':'copy'}))
    config = RunConfig(evidence_first=True)
    config.ablations.source_deduplication = False
    Engine(recorder).run(case,config)
    assert {d['id'] for d in recorder.payloads[0]['sources']} >= {first.id,'copy'}


@pytest.mark.parametrize('command', ['evaluate','matrix'])
def test_cli_defaults_to_development_split_and_has_execution_cap(command):
    from oncofusion.cli import parser
    args=parser().parse_args([command,'--inputs','i','--labels','g','--out','o'])
    assert args.split == 'dev' and args.execution_cap == 1000


@pytest.mark.parametrize('command', ['evaluate','matrix'])
def test_cli_remote_execution_cap_prevents_model_calls(tmp_path,monkeypatch,recorder,command):
    import oncofusion.cli as cli
    from oncofusion.datasets import write_dataset
    case=examples()['synthetic-support']
    other=case.model_copy(update={'id':'other','patient_id':'other-patient'})
    gold=[GoldRecord(case_id=c.id,group_id=c.patient_id,label='SUPPORTS',split='dev') for c in (case,other)]
    write_dataset([case,other],gold,tmp_path/'dataset','synthetic test')
    recorder.simulated=False
    monkeypatch.setattr(cli,'provider_from_env',lambda:recorder)
    with pytest.raises(SystemExit) as error:
        cli.main([command,'--inputs',str(tmp_path/'dataset/inputs.jsonl'),
                  '--labels',str(tmp_path/'dataset/_gold/labels.jsonl'),'--out',str(tmp_path/'out'),
                  '--allow-remote','--execution-cap','1'])
    assert error.value.code == 2 and recorder.payloads == []


def test_v1_long_input_has_headroom_and_all_controls_share_the_declared_cap():
    text = 'FICTIONAL LONG CASE. Clinical information recorded.\n' + ' '.join(
        f'documented-event-{i}' for i in range(2300))
    case = CaseInput(id='long', patient_id='p', task='mcq',
                    question='Which option is supported?', options={'A':'observed','B':'unknown'},
                    documents=[Document(id='clinical', origin_id='clinical', kind='clinical', text=text)])
    config = v1_config('native')
    old = Engine(MockProvider()).run(case, config.model_copy(update={'max_total_tokens':120000}))
    result = Engine(MockProvider()).run(case, config)
    assert old.status == 'budget_exhausted'
    assert result.status == 'completed' and result.usage.calls == 7
    assert config.max_total_tokens == 200000
    for path in (ROOT/'experiments').glob('v1_*.json'):
        plan = json.loads(path.read_text())
        assert all(t['overrides']['max_total_tokens'] == config.max_total_tokens for t in plan['treatments'])
