import importlib.util
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from oncofusion.agent_design import CONTRACTS, duty
from oncofusion.api import create_app
from oncofusion.config import presets
from oncofusion.engine import Engine
from oncofusion.examples import examples
from oncofusion.providers import MockProvider, ModelReply, ProviderError
from oncofusion.schemas import ROLES, RunConfig
from oncofusion.workflow import execute, specification


def test_evidence_first_reaches_specialists(case, recorder):
    result = Engine(recorder).run(case, RunConfig(evidence_first=True, specialist_contracts=True))
    assert result.status == "completed"
    assert recorder.payloads[0]["role"] == "literature"
    for role in ("genomics", "pathology", "drug"):
        payload = next(p for p in recorder.payloads if p["role"] == role)
        assert any(d["kind"] == "literature" for d in payload["sources"])
    assert "FUTURE_CANARY" not in json.dumps(recorder.payloads)
    assert result.usage.calls == 7 and result.usage.tool_calls == 6


@pytest.mark.parametrize("role", ROLES)
def test_specialist_protocol_has_auditable_steps_and_is_delegatable(case, recorder, role):
    assert CONTRACTS[role]["basis"] and len(CONTRACTS[role]["steps"]) >= 4
    Engine(recorder).run(case, RunConfig(specialist_contracts=True, delegated_roles=[role]))
    index = next(i for i, p in enumerate(recorder.payloads) if p["role"] == role)
    assert duty(role) not in recorder.systems[index]


def test_workflow_only_one_requery_even_if_requested_again():
    calls = []
    execute(RunConfig(evidence_first=True), lambda r: calls.append(r), lambda: None,
            lambda: True, lambda: calls.append("requery"), lambda: calls.append("decision"))
    assert calls == ["literature", "timeline", "genomics", "pathology", "drug", "verifier", "requery", "decision"]


def test_latest_board_replaces_old_findings_but_preserves_trace():
    class Changing(MockProvider):
        def __init__(self):
            self.payloads = []
            self.n = 0

        def complete(self, system, payload, *args, **kwargs):
            self.payloads.append(deepcopy(payload))
            reply = super().complete(system, payload, *args, **kwargs)
            if payload["role"] == "literature":
                self.n += 1
                data = json.loads(reply.content)
                data["findings"] = [{"statement": f"literature-version-{self.n}", "relation": "NEI", "citations": []}]
                reply.content = json.dumps(data)
            return reply

    provider = Changing()
    result = Engine(provider).run(examples()["synthetic-nei"], RunConfig(latest_role_board=True))
    assert result.status == "completed"
    assert sum(r.role == "literature" for r in result.reports) == 2
    final = json.dumps(provider.payloads[-1]["board"])
    assert "literature-version-1" not in final
    assert "literature-version-2" in final
    assert "literature-version-1" in result.model_dump_json()


def test_catalog_api_and_legacy_presets_unchanged(tmp_path):
    with TestClient(create_app(tmp_path / "db", MockProvider(), api_token="secret")) as client:
        assert client.get("/v1/agents").status_code == 401
        client.headers["Authorization"] = "Bearer secret"
        catalog = client.get("/v1/agents").json()
        assert set(catalog["roles"]) == set(ROLES)
        graph = client.get("/v1/workflows").json()
        assert graph["evidence_first"]["initial_sequence"][0] == "literature"
        assert graph["evidence_first"]["checkpoint_resume"] is False
        assert len(client.get("/v1/configs").json()) == 25


@pytest.mark.parametrize("preset", list(presets()))
@pytest.mark.parametrize("example", list(examples()))
def test_genuine_graph_native_equivalence(preset, example):
    pytest.importorskip("langgraph.graph")
    config = presets()[preset]
    config.evidence_first = True
    config.specialist_contracts = True
    config.latest_role_board = True
    native = Engine(MockProvider()).run(examples()[example], config)
    graph = Engine(MockProvider()).run(examples()[example], config.model_copy(update={"workflow_backend": "langgraph"}))
    assert native.status == graph.status == "completed"
    assert native.decision == graph.decision
    assert native.reports == graph.reports
    assert native.usage == graph.usage
    assert native.visible_document_ids == graph.visible_document_ids
    assert "FUTURE_CANARY" not in graph.model_dump_json()
    assert native.fingerprint != graph.fingerprint


@pytest.mark.parametrize("limit", ["max_calls", "max_tool_calls", "max_total_tokens"])
def test_graph_budget_matches_native(case, limit):
    pytest.importorskip("langgraph.graph")
    config = RunConfig(**{limit: 100 if limit == "max_total_tokens" else 1})
    a = Engine(MockProvider()).run(case, config)
    b = Engine(MockProvider()).run(case, config.model_copy(update={"workflow_backend": "langgraph"}))
    assert a.status == b.status == "budget_exhausted"
    assert a.usage == b.usage


def test_graph_missing_dependency_is_explicit(monkeypatch, case):
    import oncofusion.workflow as workflow
    def missing(name):
        raise workflow.PackageNotFoundError(name)
    monkeypatch.setattr(workflow, "version", missing)
    with pytest.raises(RuntimeError, match="requires"):
        Engine(MockProvider()).run(case, RunConfig(workflow_backend="langgraph"))


def test_genuine_graph_propagates_provider_failure(case):
    pytest.importorskip("langgraph.graph")
    class Broken(MockProvider):
        def complete(self, *args, **kwargs):
            raise ProviderError("failure canary")
    with pytest.raises(ProviderError, match="failure canary"):
        Engine(Broken()).run(case, RunConfig(workflow_backend="langgraph"))
