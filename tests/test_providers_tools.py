import json
import httpx
import pytest
from oncofusion.providers import (OpenAICompatibleProvider, ProviderError, provider_from_env)
from oncofusion.tools import EnsemblVEPTool, PubMedTool, PublicToolError, SnapshotCache


def envelope(content='{"answer":"NEI","explanation":"test"}', usage=True):
    data = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    if usage:
        data["usage"] = {"prompt_tokens": 10, "completion_tokens": 5}
    return data


def real(handler, **kwargs):
    return OpenAICompatibleProvider("https://provider.example/v1", "model-test", "SECRET_API_KEY",
                                    transport=httpx.MockTransport(handler), **kwargs)


def test_wire_contract_and_usage():
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=envelope())
    provider = real(handler)
    reply = provider.complete("system", {"question": "test"}, 500, .1, 42)
    body = json.loads(captured[0].content)
    assert str(captured[0].url) == "https://provider.example/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer SECRET_API_KEY"
    assert body["messages"][0] == {"role": "system", "content": "system"}
    assert body["model"] == "model-test" and body["seed"] == 42
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 500
    assert reply.input_tokens == 10 and reply.output_tokens == 5 and not reply.estimated
    assert "SECRET_API_KEY" not in repr(provider)


def test_provider_parameter_switch():
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=envelope(usage=False))
    reply = real(handler, json_mode=False, token_parameter="max_completion_tokens").complete("s", {}, 200, 0, 0)
    assert "response_format" not in captured[0]
    assert "max_tokens" not in captured[0] and captured[0]["max_completion_tokens"] == 200
    assert reply.estimated


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_retry(status, monkeypatch):
    monkeypatch.setattr("oncofusion.providers.time.sleep", lambda _: None)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status if len(calls) == 1 else 200, json=envelope())
    reply = real(handler).complete("s", {}, 200, 0, 0)
    assert len(calls) == reply.attempts == 2


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 422])
def test_nontransient_not_retried_or_leaked(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="SECRET_API_KEY confidential source")
    with pytest.raises(ProviderError) as err:
        real(handler).complete("s", {}, 200, 0, 0)
    assert len(calls) == 1
    assert str(status) in str(err.value)
    assert "SECRET" not in str(err.value)


def test_network_retry_limit(monkeypatch):
    monkeypatch.setattr("oncofusion.providers.time.sleep", lambda _: None)
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("SECRET_URL", request=request)
    with pytest.raises(ProviderError, match="upstream usage may be unknown"):
        real(handler).complete("s", {}, 200, 0, 0)
    assert len(calls) == 3


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]},
                                  {"choices": [{"message": {"content": ""}}]},
                                  {**envelope(), "usage": {"prompt_tokens": -1, "completion_tokens": 2}},
                                  {**envelope(), "usage": {"prompt_tokens": 1.2, "completion_tokens": 2}}])
def test_bad_envelope(body):
    with pytest.raises(ProviderError):
        real(lambda r: httpx.Response(200, json=body)).complete("s", {}, 200, 0, 0)


def test_truncation():
    body = envelope()
    body["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ProviderError, match="truncated"):
        real(lambda r: httpx.Response(200, json=body)).complete("s", {}, 200, 0, 0)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://remote.example/v1", "https://x/v1?api_key=secret",
                                 "https://u:p@x/v1", "https://x/v1#fragment"])
def test_provider_url_boundary(url):
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(url, "model", "secret")


@pytest.mark.parametrize("kw", [{"token_parameter": "invalid"}, {"retries": -1}, {"timeout": 0}, {"input_price": -1}])
def test_provider_settings_boundary(kw):
    with pytest.raises(ValueError):
        real(lambda _: None, **kw)


def test_env_explicit_real_failure(monkeypatch):
    assert provider_from_env().simulated
    monkeypatch.setenv("ONCOFUSION_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="unknown"):
        provider_from_env()
    monkeypatch.setenv("ONCOFUSION_PROVIDER", "openai_compatible")
    for key in ("ONCOFUSION_BASE_URL", "ONCOFUSION_MODEL", "ONCOFUSION_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="missing"):
        provider_from_env()
    monkeypatch.setenv("ONCOFUSION_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("ONCOFUSION_MODEL", "local-model")
    monkeypatch.setenv("ONCOFUSION_API_KEY", "test-key")
    monkeypatch.setenv("ONCOFUSION_INPUT_PRICE", "1.5")
    monkeypatch.setenv("ONCOFUSION_OUTPUT_PRICE", "4.5")
    provider = provider_from_env()
    assert not provider.simulated and provider.input_price == 1.5


def test_pubmed_search_and_abstracts():
    xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Gene <i>study</i></ArticleTitle><Abstract><AbstractText>Synthetic text.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
    def handler(request):
        if request.url.path.endswith("esearch.fcgi"):
            assert request.url.params["db"] == "pubmed"
            return httpx.Response(200, json={"esearchresult": {"idlist": ["123"]}})
        return httpx.Response(200, text=xml)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        tool = PubMedTool(client)
        assert tool.search("gene", 1) == ["123"]
        doc = tool.abstracts(["123"])[0]
        assert doc.text == "Synthetic text." and doc.title == "Gene study"
        assert doc.origin_id == "pmid-123"


@pytest.mark.parametrize("query,limit", [("", 10), ("x" * 1001, 10), ("gene", 0), ("gene", 21)])
def test_pubmed_search_boundary(query, limit):
    with httpx.Client(transport=httpx.MockTransport(lambda _: None)) as client:
        with pytest.raises(ValueError):
            PubMedTool(client).search(query, limit)


@pytest.mark.parametrize("ids", [[], ["../secret"], ["1"] * 21])
def test_pubmed_ids_boundary(ids):
    with httpx.Client(transport=httpx.MockTransport(lambda _: None)) as client:
        with pytest.raises(ValueError):
            PubMedTool(client).abstracts(ids)


@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, text="not json"),
                                      httpx.Response(200, json={"esearchresult": {"idlist": ["bad"]}})])
def test_pubmed_errors(response):
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(PublicToolError):
            PubMedTool(client).search("gene")


@pytest.mark.parametrize("xml", ["not xml", '<!ENTITY x SYSTEM "file:///etc/passwd">',
                                '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>999</PMID></MedlineCitation></PubmedArticle></PubmedArticleSet>'])
def test_pubmed_xml_boundary(xml):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=xml))) as client:
        with pytest.raises(PublicToolError):
            PubMedTool(client).abstracts(["123"])


def test_pubmed_no_abstract():
    xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID></MedlineCitation></PubmedArticle></PubmedArticleSet>'
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=xml))) as client:
        assert PubMedTool(client).abstracts(["123"]) == []


def test_vep_wire_contract():
    def handler(request):
        assert json.loads(request.content) == {"hgvs_notations": ["ENST:test"]}
        return httpx.Response(200, json=[{"input": "ENST:test", "most_severe_consequence": "missense_variant"}])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert EnsemblVEPTool(client).annotate(["ENST:test"])[0]["input"] == "ENST:test"


@pytest.mark.parametrize("data", [[], [""], ["x"] * 101])
def test_vep_input_boundary(data):
    with httpx.Client(transport=httpx.MockTransport(lambda _: None)) as client:
        with pytest.raises(ValueError):
            EnsemblVEPTool(client).annotate(data)


def test_vep_bad_response():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))) as client:
        with pytest.raises(PublicToolError):
            EnsemblVEPTool(client).annotate(["variant"])


def test_snapshot_cache(tmp_path):
    cache = SnapshotCache(tmp_path)
    cache.put("pubmed", {"q": "gene"}, {"ids": ["123"]})
    assert cache.get("pubmed", {"q": "gene"}) == {"ids": ["123"]}
    assert cache.path("../outside", {"q": "../../etc/passwd"}).parent == tmp_path
    with pytest.raises(FileNotFoundError):
        cache.get("pubmed", {"q": "different"})


@pytest.mark.parametrize("price", [float("nan"), float("inf"), -1])
def test_price_must_be_finite(price):
    with pytest.raises(ValueError):
        real(lambda _: None, input_price=price)


def test_mock_large_output_budget():
    from oncofusion.providers import MockProvider
    from oncofusion.schemas import Document, AnalysisOutput, DecisionOutput
    sources = [Document(id=f"d{i}", origin_id=f"o{i}", kind="literature", text="gene sensitive drug " * 100).model_dump() for i in range(30)]
    payload = {"role": "literature", "sources": sources, "signals": {}, "question": "gene drug",
               "task": "synthesis", "options": {}, "board": []}
    reply = MockProvider().complete("s", payload, 1000, 0, 0)
    assert reply.output_tokens <= 1000
    assert len(AnalysisOutput.model_validate_json(reply.content).findings) < 20
    payload["role"] = "decision"
    reply = MockProvider().complete("s", payload, 1000, 0, 0)
    assert reply.output_tokens <= 1000
    assert len(DecisionOutput.model_validate_json(reply.content).citations) < 30
    with pytest.raises(ProviderError):
        MockProvider().complete("s", payload, 5, 0, 0)
