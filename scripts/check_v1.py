"""Execute the conservative release contract with simulated LLMs, no external data calls."""
from __future__ import annotations
import argparse
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from oncofusion.api import create_app
from oncofusion.engine import Engine
from oncofusion.evidence import evidence_graph, visible_case
from oncofusion.examples import examples
from oncofusion.profiles import coverage_report, integration_example, v1_config
from oncofusion.providers import MockProvider
from oncofusion.workflow import dependency_identity


def check(backend: str) -> dict:
    config = v1_config(backend)
    dependencies = dependency_identity(config)
    cases = [*examples().values(), integration_example()]
    executions, calls = 0, 0
    for case in cases:
        for mode in ('multi','single_tools','single_iterative'):
            current = config.model_copy(update={'mode':mode})
            result = Engine(MockProvider()).run(case,current)
            assert result.status == 'completed' and result.decision is not None
            assert not any(e.kind == 'requery_requested' for e in result.trace)
            assert 'FUTURE_CANARY' not in result.model_dump_json()
            assert next(n for n in evidence_graph(result.reports, visible_case(case).documents, result.decision)['nodes'] if n['id']=='decision')
            if mode == 'multi':
                assert len(result.reports) == 6 and result.usage.calls == 7
            executions += 1
            calls += result.usage.calls
    with tempfile.TemporaryDirectory() as td, TestClient(create_app(Path(td)/'api.db',MockProvider(),api_token='test-only')) as client:
        headers = {'Authorization':'Bearer test-only'}
        assert client.get('/v1/profiles').status_code == 401
        profile = client.get('/v1/profiles',headers=headers).json()['v1']
        assert profile['first_release']['requery_rounds'] == 0
        fixture = client.get('/v1/profiles/v1/example',headers=headers).json()
        inspection = client.post('/v1/cases/inspect',headers=headers,json=fixture)
        assert inspection.status_code == 200 and inspection.json()['heterogeneous_document_input']
        assert not client.get('/v1/cases',headers=headers).json()
    return {'status':'passed','backend':backend,'dependencies':dependencies,
            'executions':executions,'simulated_model_calls':calls,'commercial_llm_calls':0,
            'external_data_calls':0,'llm_simulated':True,'coverage':coverage_report(cases),
            'interpretation':'Software and input-coverage acceptance, not biomedical accuracy or agent efficacy.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=('native','langgraph'),default='langgraph')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    report=check(args.backend)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    main()
