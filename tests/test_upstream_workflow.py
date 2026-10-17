import json
from itertools import product

import pytest
from oncofusion.config import presets, legacy_presets
from oncofusion.engine import Engine, implementation_digest
from oncofusion.examples import examples
from oncofusion.protocols import GROUNDED_DUTIES
from oncofusion.providers import MockProvider, ModelReply, ProviderError
from oncofusion.schemas import (AgentReport, AnalysisOutput, ClaimReview, Finding,
                                RunConfig, VerifiedAnalysisOutput)
from oncofusion.verification import verification_targets, validate_reviews


def v2(**changes):
    return RunConfig.model_validate({**presets()['grounded_v2'].model_dump(), **changes})


@pytest.mark.parametrize('example', list(examples()))
@pytest.mark.parametrize('contexts', [False, True])
@pytest.mark.parametrize('routing', ['fixed', 'adaptive'])
def test_real_graph_matches_reference(example, contexts, routing):
    case = examples()[example]
    graph = Engine(MockProvider()).run(case, v2(literature_contexts=contexts, routing=routing))
    ref = Engine(MockProvider()).run(case, v2(orchestrator='python', literature_contexts=contexts, routing=routing))
    assert graph.status == ref.status == 'completed'
    assert graph.reports == ref.reports and graph.decision == ref.decision
    assert graph.usage == ref.usage
    assert graph.trace[1:] == ref.trace[1:]


def test_evidence_reaches_every_specialist(case, recorder):
    Engine(recorder).run(case, v2())
    roles = [p['role'] for p in recorder.payloads]
    assert roles[:6] == ['literature','timeline','genomics','pathology','drug','verifier']
    for payload in recorder.payloads:
        assert 'FUTURE_CANARY' not in json.dumps(payload)
        if payload['role'] in {'timeline','genomics','pathology','drug'}:
            assert 'paper1' in {d['id'] for d in payload['sources']}
    assert recorder.payloads[-1]['claim_reviews']
    assert all(r['verdict'] == 'insufficient' for r in recorder.payloads[-1]['claim_reviews'])


def test_limit_preserves_unreviewed_claims(case, recorder):
    Engine(recorder).run(case, v2(max_review_claims=1))
    verifier = next(p for p in recorder.payloads if p['role']=='verifier')
    assert len(verifier['verification_targets']) == 1
    assert recorder.payloads[-1]['unreviewed_claims']


@pytest.mark.parametrize('role', list(GROUNDED_DUTIES))
def test_specialist_delegation_really_replaces_protocol(case, recorder, role):
    Engine(recorder).run(case, v2(delegated_roles=[role]))
    i = next(i for i,p in enumerate(recorder.payloads) if p['role']==role)
    assert GROUNDED_DUTIES[role] not in recorder.systems[i]
    assert 'generalist' in recorder.systems[i]


@pytest.mark.parametrize('change', ['missing','duplicate','invented','badquote','noquote'])
def test_verifier_rejects_corrupt_coverage(case, change):
    class Broken(MockProvider):
        def complete(self, system, payload, *args):
            reply = super().complete(system,payload,*args)
            if payload['role']=='verifier':
                output = json.loads(reply.content)
                if change=='missing': output['reviews'].pop()
                if change=='duplicate': output['reviews'].append(output['reviews'][0])
                if change=='invented': output['reviews'][0]['claim_id']='claim-'+'a'*24
                if change in {'badquote','noquote'}:
                    output['reviews'][0]['verdict']='supported'
                    if change=='badquote':
                        output['reviews'][0]['citations']=[{'document_id':'future','quote':'bogus'}]
                reply.content=json.dumps(output)
            return reply
    with pytest.raises(ProviderError):
        Engine(Broken()).run(case,v2())


@pytest.mark.parametrize('orchestrator', ['python','langgraph'])
def test_review_requery_is_bounded_and_source_isolated(orchestrator,recorder):
    case=examples()['synthetic-nei']
    result=Engine(recorder).run(case,v2(orchestrator=orchestrator))
    assert sum(e.kind=='requery_requested' for e in result.trace)==1
    assert result.usage.calls==9
    assert result.reports[-1].role=='verifier'
    assert all('FUTURE_CANARY' not in json.dumps(p) for p in recorder.payloads)


@pytest.mark.parametrize('budget', [1,3,6,7])
@pytest.mark.parametrize('orchestrator', ['python','langgraph'])
def test_graph_budget_equals_reference(case,budget,orchestrator):
    result=Engine(MockProvider()).run(case,v2(orchestrator=orchestrator,max_calls=budget))
    assert result.usage.calls==budget
    assert result.status==('completed' if budget==7 else 'budget_exhausted')


def test_context_calls_are_charged_and_retain_original_sources(case,recorder):
    result=Engine(recorder).run(case,v2(literature_contexts=True))
    contexts=[e for e in result.trace if e.kind=='context_completed']
    assert contexts and result.usage.calls==7+len(contexts)
    assert all(e.details['status']=='model_generated_unverified' for e in contexts)
    assert recorder.payloads[-1]['signals']['literature_contexts']
    assert 'paper1' in {d['id'] for d in recorder.payloads[-1]['sources']}
    assert len([e for e in result.trace if e.kind=='model_usage'])==result.usage.calls


@pytest.mark.parametrize('reply', ['{}','{"summary":"", "relevance_score":7}',
                                    '{"summary":"relevant", "relevance_score":100}',
                                    '{"summary":"relevant", "relevance_score":1.5}'])
def test_invalid_paperqa_context_fails_visibly(case,reply):
    class Broken(MockProvider):
        def complete(self,system,payload,*args):
            if payload['role']=='literature_context': return ModelReply(reply,10,10)
            return super().complete(system,payload,*args)
    with pytest.raises(ProviderError,match='PaperQA context'):
        Engine(Broken()).run(case,v2(literature_contexts=True))


def test_reflection_keeps_source_boundary(case,recorder):
    cfg=v2();cfg.ablations.external_verification=False
    Engine(recorder).run(case,cfg)
    payload=next(p for p in recorder.payloads if p['role']=='verifier')
    assert payload['sources']==[] and payload['signals']=={}
    assert payload['verification_targets']


def test_claim_ids_stable_and_deduplicated(case):
    source=case.documents[0]
    finding=Finding(statement='A self-contained molecular claim',citations=[{'document_id':source.id,'quote':source.text}])
    reports=[AgentReport(role=role,executor=role,output=AnalysisOutput(findings=[finding])) for role in ['genomics','drug']]
    targets,extra=verification_targets(reports,case.documents,6)
    assert len(targets)==1 and not extra
    assert targets==verification_targets(reports,case.documents,6)[0]


@pytest.mark.parametrize('configuration', [dict(orchestrator='langgraph'),
  dict(orchestrator='langgraph',workflow='evidence_first',mode='single_direct'),
  dict(claim_verification=True,mode='single_tools')])
def test_invalid_workflow_config_fails(configuration):
    with pytest.raises(ValueError):RunConfig(**configuration)


def test_legacy_presets_and_plans_unchanged():
    assert len(legacy_presets())==25
    assert presets()['full'].workflow=='legacy'
    assert presets()['grounded_v2'].orchestrator=='langgraph'


def test_native_revision_scheme_supported(case,recorder):
    case.verification_scheme='revisions'
    result=Engine(recorder).run(case,v2())
    assert result.decision.answer in case.verification_labels
    assert recorder.payloads[-1]['verification_labels']==['SUPPORTS','REVISIONS','NEI']


def test_verdicts_visible_in_evidence_graph(case):
    from oncofusion.evidence import evidence_graph,visible_case
    run=Engine(MockProvider()).run(case,v2())
    graph=evidence_graph(run.reports,visible_case(case).documents)
    reviews=[n for n in graph['nodes'] if n['type']=='review']
    assert reviews and all(n['verdict']=='insufficient' for n in reviews)
    ids={n['id'] for n in graph['nodes']}
    assert all(e['source'] in ids and e['target'] in ids for e in graph['edges'])
    assert len([e for e in graph['edges'] if e['type']=='reviews'])>=len(reviews)


def test_frontend_discovers_v2_and_result_contract(client):
    assert client.get('/v1/capabilities').json()['recommended_preset']=='grounded_v2'
    schema=client.get('/v1/schemas/result').json()
    assert 'ClaimReview' in schema['$defs']
    configs=client.get('/v1/configs').json()
    assert configs['grounded_v2']['orchestrator']=='langgraph'
    assert configs['full']['workflow']=='legacy'


def test_requery_replaces_superseded_board_findings(case,recorder):
    original=recorder.complete
    count=[0]
    def complete(system,payload,*args):
        reply=original(system,payload,*args)
        data=json.loads(reply.content)
        if payload['role']=='literature':
            count[0]+=1
            for finding in data['findings']:
                finding['statement']='literature-revision-'+str(count[0])
        if payload['role']=='verifier':data['requery']='targeted evidence query'
        reply.content=json.dumps(data);return reply
    recorder.complete=complete
    Engine(recorder).run(case,v2())
    # Verifier may itself reproduce source facts; the old literature finding version is removed.
    board=json.dumps(recorder.payloads[-1]['board'])
    assert 'literature-revision-2' in board and 'literature-revision-1' not in board


def test_order_ablation_preserves_latest_report_policy():
    cfg = v2(workflow="legacy", orchestrator="python")
    assert cfg.latest_report_board and cfg.claim_verification
