import copy
import json

import pytest
from jsonschema import ValidationError
from pydantic import ValidationError as PydanticError

from oncofusion.schemas import CaseInput
from oncofusion.upstream_tools import (TOOLS, TOOL_VERSION, SourcePlan, ToolFailure, ToolRequest,
                                      ToolUniverseSources, attach_snapshot)


class SDK:
    def __init__(self, result=None):
        self.calls = []
        self.result = {"hits": [{"symbol": "BRAF", "entrezgene": "673"}]} if result is None else result

    def load_tools(self, include_tools):
        self.loaded = include_tools

    def tool_specification(self, name, format):
        return {"name": name, "parameters": {"type": "object", "required": ["query"],
                                             "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}}

    def run(self, request):
        self.calls.append(request)
        return self.result


def plan(*requests):
    return SourcePlan(requests=list(requests) or [ToolRequest(name="MyGene_query_genes", arguments={"query": "BRAF"})],
                      public_queries_reviewed=True, source_terms_accepted=True)


def case():
    return CaseInput(id="custom", patient_id="anonymous", task="synthesis", question="Compare source evidence.",
                     data_class="synthetic")


def test_actual_adapter_calls_sdk_and_retains_provenance():
    sdk = SDK()
    adapter = ToolUniverseSources(sdk, TOOL_VERSION)
    snapshot = adapter.collect(plan())
    assert set(sdk.loaded) == set(TOOLS)
    assert sdk.calls == [{"name": "MyGene_query_genes", "arguments": {"query": "BRAF"}}]
    assert snapshot["llm_calls"] == 0 and snapshot["tool_calls"] == 1
    enriched = attach_snapshot(case(), snapshot)
    assert enriched.documents[0].kind == "genomics"
    assert "not an independently verified primary-paper" in enriched.documents[0].text
    assert attach_snapshot(enriched, snapshot) == enriched


@pytest.mark.parametrize("error", [{"error": "network"}, {"errors": ["query"]}, {"success": False},
                                    {"status": "failed"}, "Error: unavailable", [], {}, ""])
def test_sdk_error_is_not_evidence(error):
    with pytest.raises(ToolFailure):
        ToolUniverseSources(SDK(error), TOOL_VERSION).collect(plan())


def test_network_exception_not_mocked():
    class Broken(SDK):
        def run(self, request):
            raise TimeoutError("private details")
    with pytest.raises(ToolFailure, match="TimeoutError") as error:
        ToolUniverseSources(Broken(), TOOL_VERSION).collect(plan())
    assert "private details" not in str(error.value)


@pytest.mark.parametrize("arguments", [{"q": "BRAF"}, {"query": "BRAF", "api_key": "private"},
                                       {"query": 12}, {"query": "BRAF", "patient_notes": "private"}])
def test_invalid_args_fail_before_any_external_call(arguments):
    sdk = SDK()
    request = ToolRequest(name="MyGene_query_genes", arguments=arguments)
    with pytest.raises(ValidationError):
        ToolUniverseSources(sdk, TOOL_VERSION).collect(plan(plan().requests[0], request))
    assert sdk.calls == []


def test_duplicate_plan_queries_cost_one_call():
    sdk = SDK()
    request = plan().requests[0]
    result = ToolUniverseSources(sdk, TOOL_VERSION).collect(plan(request, request))
    assert result["tool_calls"] == len(sdk.calls) == 1


@pytest.mark.parametrize("patch", [{"task": "verification"}, {"stage": 1}, {"as_of_day": 100},
                                   {"data_class": "unreviewed"}])
def test_benchmark_and_historical_snapshots_rejected(patch):
    snapshot = ToolUniverseSources(SDK(), TOOL_VERSION).collect(plan())
    with pytest.raises(ValueError):
        attach_snapshot(case().model_copy(update=patch), snapshot)


def test_tampered_snapshot_fails():
    snapshot = ToolUniverseSources(SDK(), TOOL_VERSION).collect(plan())
    snapshot["records"][0]["response"] = {"fabricated": "answer"}
    with pytest.raises(ValueError, match="hash"):
        attach_snapshot(case(), snapshot)


def test_snapshot_requires_version_and_review():
    snapshot = ToolUniverseSources(SDK(), TOOL_VERSION).collect(plan())
    for field, value in (("tooluniverse_version", "0"), ("public_queries_reviewed", False)):
        changed = {**snapshot, field: value}
        with pytest.raises(ValueError):
            attach_snapshot(case(), changed)


def test_no_arbitrary_tool_or_silent_truncation():
    with pytest.raises(PydanticError):
        ToolRequest(name="python_executor", arguments={"code": "pass"})
    with pytest.raises(ToolFailure, match="limit"):
        ToolUniverseSources(SDK({"response": "x" * 95000}), TOOL_VERSION).collect(plan())


@pytest.mark.parametrize("limit", [0, 11])
def test_pubmed_bounded(limit):
    sdk = SDK()
    with pytest.raises(ValueError):
        ToolUniverseSources(sdk, TOOL_VERSION).collect(plan(ToolRequest(name="PubMed_search_articles",
                                                                      arguments={"query": "BRAF", "limit": limit})))
    assert not sdk.calls
