import copy
import json
from pathlib import Path
import sys
import types

import httpx
import pytest
from oncofusion.biomedical import (ALLOWED_TOOLS, EvidenceSnapshot, ToolQuery, ToolUniverseAdapter,
                                   response_digest, save_snapshot)
from oncofusion.tools import PublicToolError
from oncofusion.vendor.geneagent_enrichment import get_pathway_for_gene_set
from oncofusion.vendor.paperqa_prompts import summary_json_prompt, summary_json_system_prompt


def query():
    return ToolQuery(name='OncoTree_get_type',arguments={'code':'LUAD','version':'oncotree_latest_stable'},purpose='Resolve public cancer terminology')


@pytest.fixture
def sdk_boundary(monkeypatch):
    class SDK:
        def __init__(self,**kwargs):
            assert kwargs['hooks_enabled'] is False and kwargs['load_workspace'] is False
            self.response={'status':'success','data':{'code':'LUAD','name':'Lung Adenocarcinoma'}}
        def load_tools(self,include_tools,quiet):
            self.all_tool_dict={name:{'parameter':{'type':'object'}} for name in include_tools}
        def run_one_function(self,request,**kwargs):
            assert kwargs==dict(use_cache=False,validate=True)
            assert request['name'] in ALLOWED_TOOLS
            return self.response
    monkeypatch.setitem(sys.modules,'tooluniverse',types.SimpleNamespace(ToolUniverse=SDK))
    monkeypatch.setattr('oncofusion.biomedical.version',lambda package:'1.5.7')
    return ToolUniverseAdapter()


def test_sdk_boundary_contract_and_snapshot(sdk_boundary,tmp_path):
    snapshot=sdk_boundary.execute(query(),allow_remote=True)
    assert snapshot.toolkit=='ToolUniverse' and snapshot.toolkit_version=='1.5.7'
    assert snapshot.response_sha256==response_digest(snapshot.response)
    path=tmp_path/'snapshot.json'
    save_snapshot(snapshot,path)
    assert EvidenceSnapshot.model_validate_json(path.read_text())==snapshot
    with pytest.raises(FileExistsError):save_snapshot(snapshot,path)
    doc=snapshot.document(stage=2)
    assert doc.available_stage==2 and doc.kind=='pathology' and doc.event_day is None
    assert 'not a patient observation' in doc.text
    record=snapshot.model_dump();record['response']['data']['code']='MUTATED'
    with pytest.raises(ValueError,match='checksum'):EvidenceSnapshot.model_validate(record)


@pytest.mark.parametrize('response', [None,17,'not json',{'status':'error'}, {'error':'upstream failure'}, {'bad':float('nan')}])
def test_upstream_error_never_becomes_evidence(sdk_boundary,response):
    sdk_boundary.sdk.response=response
    with pytest.raises(PublicToolError):sdk_boundary.execute(query(),allow_remote=True)


def test_string_json_response_allowed(sdk_boundary):
    sdk_boundary.sdk.response='{"status":"success","data":[]}'
    assert sdk_boundary.execute(query(),allow_remote=True).response['data']==[]


def test_consent_before_tool_execution(sdk_boundary):
    with pytest.raises(ValueError,match='consent'):sdk_boundary.execute(query(),allow_remote=False)
    with pytest.raises(ValueError):sdk_boundary.schema('execute_python')


@pytest.mark.parametrize('name,args',[
    ('execute_python',{'code':'print(1)'}),
    ('PubMed_search_articles',{'query':'valid','url':'https://malicious.invalid'}),
    ('PubMed_search_articles',{'query':' ' }),
    ('PubMed_search_articles',{'query':'x'*241}),
    ('PubMed_search_articles',{'query':7}),
    ('PubMed_search_articles',{'query':'EGFR','limit':0}),
    ('PubMed_search_articles',{'query':'EGFR','limit':11}),
    ('PubMed_search_articles',{'query':'EGFR','limit':True}),
    ('MyGene_query_genes',{'query':'EGFR','fields':'x'*2000}),
    ('OncoTree_get_type',{'code':'LUAD'}),
])
def test_query_allowlist_boundary(name,args):
    with pytest.raises(ValueError):ToolQuery(name=name,arguments=args,purpose='test')


@pytest.mark.parametrize('genes', [[],['EGFR'],['EGFR','EGFR'],['EGFR','malformed input'],['EGFR','../file'], ['EGFR',7]])
def test_geneagent_input_boundary(genes):
    with pytest.raises(ValueError):get_pathway_for_gene_set(genes,allow_remote=True)


@pytest.mark.parametrize('libraries', [(),('unknown',),('Reactome_2022','Reactome_2022')])
def test_geneagent_library_boundary(libraries):
    with pytest.raises(ValueError):get_pathway_for_gene_set(['EGFR','BRAF'],allow_remote=True,libraries=libraries)


def test_geneagent_explicit_consent():
    with pytest.raises(ValueError,match='remote'):get_pathway_for_gene_set(['EGFR','BRAF'],allow_remote=False)


def test_geneagent_algorithm_and_statistics_retained():
    calls=[]
    def respond(request):
        calls.append(request)
        assert request.url.scheme=='https'
        if request.method=='POST':
            assert b'EGFR\nBRAF' in request.content
            return httpx.Response(200,json={'userListId':42})
        library=request.url.params['backgroundType']
        return httpx.Response(200,json={library:[[1,'MAPK signaling',0.001,1.1,3.0,['EGFR','BRAF'],0.02,0,0]]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        results=get_pathway_for_gene_set(['EGFR','BRAF'],allow_remote=True,client=client)
        assert not client.is_closed
    assert len(calls)==3 and len(results)==2
    assert results[0].adjusted_p_value==0.02 and results[0].p_value==0.001
    assert results[0].evidence_type=='gene_set_enrichment'


@pytest.mark.parametrize('bad', ['http','missing_id','invalid_id','missing_library','bad_rows','short_row','pvalue'])
def test_geneagent_upstream_error_fails_whole_acquisition(bad):
    def respond(request):
        if bad=='http':return httpx.Response(503)
        if request.method=='POST':
            return httpx.Response(200,json={} if bad=='missing_id' else {'userListId':'wrong' if bad=='invalid_id' else 42})
        library=request.url.params['backgroundType']
        if bad=='missing_library': return httpx.Response(200,json={})
        if bad=='bad_rows': return httpx.Response(200,json={library:None})
        row=[] if bad=='short_row' else [1,'term',2,1,1,['EGFR'],2]
        return httpx.Response(200,json={library:[row]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(PublicToolError):get_pathway_for_gene_set(['EGFR','BRAF'],allow_remote=True,client=client)


def test_upstream_templates_are_format_safe():
    assert 'relevance_score' in summary_json_system_prompt.format(summary_length='120 words')
    assert 'BRAF' in summary_json_prompt.format(citation='ref',text='BRAF',question='What?')


def test_missing_sdk_allowlist_fails(monkeypatch):
    class Missing:
        def __init__(self,**kwargs):pass
        def load_tools(self,**kwargs):self.all_tool_dict={}
    monkeypatch.setitem(sys.modules,'tooluniverse',types.SimpleNamespace(ToolUniverse=Missing))
    monkeypatch.setattr('oncofusion.biomedical.version',lambda package:'1.5.7')
    with pytest.raises(RuntimeError,match='allowlist'):ToolUniverseAdapter()


def test_enrichment_is_separate_from_closed_benchmarks(case,sdk_boundary):
    from oncofusion.biomedical import enrich_synthesis_case
    snap=sdk_boundary.execute(query(),allow_remote=True)
    with pytest.raises(ValueError,match='separate'):enrich_synthesis_case(case,[snap])
    case.task='synthesis'
    extended=enrich_synthesis_case(case,[snap,snap])
    assert len(extended.documents)==len(case.documents)+1
    assert 'External knowledge context' in extended.documents[-1].text


def test_pubmed_original_provenance_and_partial_results(sdk_boundary):
    q=ToolQuery(name='PubMed_search_articles',arguments={'query':'EGFR','include_abstract':True,'limit':1},purpose='public literature')
    sdk_boundary.sdk.response={'status':'success','data':[{'pmid':'42','title':'Example','abstract':'Real source text.'}]}
    snap=sdk_boundary.execute(q,allow_remote=True)
    document=snap.documents(stage=1)[0]
    assert document.origin_id=='pmid-42' and document.text=='Real source text.'
    sdk_boundary.sdk.response={'status':'success','data':[{'pmid':'42','abstract':None,'partial':True}]}
    snap=sdk_boundary.execute(q,allow_remote=True)
    with pytest.raises(ValueError,match='actual abstracts'):snap.documents(stage=1)
