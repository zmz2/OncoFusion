"""Requires the actual ToolUniverse package; only its upstream HTTP is replaced."""
import json
import socket
import pytest
import requests
from oncofusion.biomedical import ToolUniverseAdapter, ToolQuery, ALLOWED_TOOLS
from oncofusion.tools import PublicToolError


@pytest.fixture(scope='module')
def adapter():
    return ToolUniverseAdapter()


@pytest.fixture(autouse=True)
def block_unexpected_network(monkeypatch):
    def deny(*args,**kwargs): raise AssertionError('unexpected external network')
    monkeypatch.setattr(socket.socket,'connect',deny)


@pytest.mark.parametrize('name', list(ALLOWED_TOOLS))
def test_actual_sdk_catalog_and_schema(adapter,name):
    schema=adapter.schema(name)
    assert schema['type']=='object' and schema['properties']
    assert adapter.version=='1.5.7'


@pytest.mark.parametrize('code', ['LUAD','BRCA'])
def test_actual_oncotree_tool_decodes_http(adapter,monkeypatch,code):
    def get(url,params,timeout):
        assert url.endswith('/tumorTypes/search/code/'+code)
        assert params=={'exactMatch':'true','version':'oncotree_latest_stable'}
        assert 0<timeout<=60
        r=requests.Response();r.status_code=200
        r._content=json.dumps([{'code':code,'name':'TEST ontology term','mainType':'TEST','tissue':'TEST','level':2}]).encode()
        return r
    monkeypatch.setattr(requests,'get',get)
    snapshot=adapter.execute(ToolQuery(name='OncoTree_get_type',arguments={'code':code,'version':'oncotree_latest_stable'},purpose='catalog contract'),allow_remote=True)
    assert snapshot.response['data']['code']==code


def test_actual_mygene_tool_decodes_http(adapter,monkeypatch):
    def get(url,params,timeout):
        assert url.endswith('/query') and params['q']=='symbol:EGFR'
        r=requests.Response();r.status_code=200
        r._content=json.dumps({'hits':[{'symbol':'EGFR','entrezgene':1956}]}).encode();return r
    monkeypatch.setattr(requests,'get',get)
    snapshot=adapter.execute(ToolQuery(name='MyGene_query_genes',arguments={'query':'symbol:EGFR','size':1},purpose='gene ID lookup'),allow_remote=True)
    assert snapshot.response['data']['hits'][0]['entrezgene']==1956


def test_actual_upstream_timeout_becomes_failure(adapter,monkeypatch):
    def fail(*args,**kwargs):raise requests.exceptions.Timeout()
    monkeypatch.setattr(requests,'get',fail)
    with pytest.raises(PublicToolError):
        adapter.execute(ToolQuery(name='OncoTree_get_type',arguments={'code':'LUAD','version':'oncotree_latest_stable'},purpose='error propagation'),allow_remote=True)
