"""Reuse the actual ToolUniverse SDK to prepare reviewed, reproducible source snapshots.

No tool here receives a CaseInput or patient narrative. Live preparation is opt-in and
separate from closed-corpus benchmarks. Tool responses are records, not primary papers.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Literal

from pydantic import Field

from .schemas import CaseInput, Document, StrictModel

TOOL_VERSION = "1.5.7"
TOOLS = {
    "MyGene_query_genes": {"kind": "genomics", "url": "https://mygene.info/"},
    "UniProt_get_function_by_accession": {"kind": "genomics", "url": "https://www.uniprot.org/"},
    "DGIdb_get_drug_gene_interactions": {"kind": "therapy", "url": "https://dgidb.org/"},
    "OpenTargets_get_associated_drugs_by_target_ensemblID": {
        "kind": "therapy", "url": "https://platform.opentargets.org/"},
    "PubMed_search_articles": {"kind": "literature", "url": "https://pubmed.ncbi.nlm.nih.gov/"},
}
ToolName = Literal["MyGene_query_genes", "UniProt_get_function_by_accession",
                   "DGIdb_get_drug_gene_interactions",
                   "OpenTargets_get_associated_drugs_by_target_ensemblID", "PubMed_search_articles"]


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ToolRequest(StrictModel):
    name: ToolName
    arguments: dict = Field(min_length=1, max_length=12)


class SourcePlan(StrictModel):
    """Explicit user/operator-reviewed public entity queries; never auto-filled from notes."""
    requests: list[ToolRequest] = Field(min_length=1, max_length=10)
    public_queries_reviewed: Literal[True]
    source_terms_accepted: Literal[True]


class ToolFailure(RuntimeError):
    pass


class ToolUniverseSources:
    def __init__(self, client, sdk_version: str):
        self.client, self.sdk_version = client, sdk_version
        self.client.load_tools(include_tools=list(TOOLS))
        self.specs = {name: self.client.tool_specification(name, format="openai") for name in TOOLS}
        for name, spec in self.specs.items():
            if spec["name"] != name:
                raise ToolFailure("upstream tool identity changed: " + name)

    @classmethod
    def installed(cls):
        actual = version("tooluniverse")
        if actual != TOOL_VERSION:
            raise ToolFailure(f"reviewed ToolUniverse version is {TOOL_VERSION}; installed {actual}")
        from tooluniverse import ToolUniverse
        return cls(ToolUniverse(hooks_enabled=False, load_workspace=False), actual)

    def validate(self, request: ToolRequest) -> None:
        from jsonschema import validate
        schema = dict(self.specs[request.name]["parameters"])
        # Several upstream specs permit arbitrary keys; our public adapter accepts
        # only documented parameters so typos and credential/narrative fields fail.
        schema["additionalProperties"] = False
        validate(request.arguments, schema)
        if len(canonical(request.arguments).encode()) > 2000:
            raise ValueError("public query arguments exceed 2000 bytes")
        if request.name == "PubMed_search_articles":
            count = request.arguments.get("max_results", request.arguments.get("limit", 10))
            if not 1 <= count <= 10:
                raise ValueError("PubMed preparation accepts 1..10 results per request")

    def collect(self, plan: SourcePlan) -> dict:
        # Validate the entire plan before the first external request.
        for request in plan.requests:
            self.validate(request)
        records = []
        seen = set()
        for request in plan.requests:
            key = digest(request.model_dump())
            if key in seen:
                continue
            seen.add(key)
            try:
                result = self.client.run(request.model_dump())
            except Exception as exc:
                # Actual SDK/network boundary. Preserve failure, never fabricate evidence.
                raise ToolFailure(f"{request.name} failed: {type(exc).__name__}") from exc
            if result is None or result == "" or result == [] or result == {}:
                raise ToolFailure(f"{request.name} returned no record")
            if isinstance(result, dict) and (result.get("error") or result.get("errors")
                    or result.get("status") in ("error", "failed") or result.get("success") is False):
                raise ToolFailure(f"{request.name} returned an upstream error record")
            if isinstance(result, str) and result.lstrip().lower().startswith(("error", "failed", "exception")):
                raise ToolFailure(f"{request.name} returned an upstream error string")
            raw = canonical(result)
            if len(raw.encode()) > 90000:
                raise ToolFailure(f"{request.name} response exceeds snapshot limit; narrow the query")
            records.append({"request": request.model_dump(), "response": result,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            "response_sha256": digest(result), "request_sha256": key})
        return {"schema_version": "1.0", "tooluniverse_version": self.sdk_version,
                "public_queries_reviewed": True, "source_terms_accepted": True,
                "tool_calls": len(records), "llm_calls": 0, "records": records}


def attach_snapshot(case: CaseInput, snapshot: dict) -> CaseInput:
    """Append only to an explicitly reviewed contemporary custom synthesis case.

    A snapshot timestamp cannot be converted into a historical benchmark stage. A
    separate extended protocol must be written before enriching MCQ/verification data.
    """
    if case.task != "synthesis" or case.as_of_day is not None or case.stage != 0:
        raise ValueError("live snapshots require a contemporary synthesis case, stage=0, no as_of_day")
    if case.data_class == "unreviewed":
        raise ValueError("review and deidentify the case before attaching external sources")
    if snapshot["tooluniverse_version"] != TOOL_VERSION:
        raise ValueError("snapshot tool version differs from reviewed version")
    if snapshot["public_queries_reviewed"] is not True or snapshot["source_terms_accepted"] is not True:
        raise ValueError("snapshot is missing explicit source review")
    documents = list(case.documents)
    existing = {d.id: d for d in documents}
    for record in snapshot["records"]:
        request = ToolRequest.model_validate(record["request"])
        if digest(record["response"]) != record["response_sha256"] or digest(record["request"]) != record["request_sha256"]:
            raise ValueError("snapshot content hash mismatch")
        text = "ToolUniverse database/search record; not an independently verified primary-paper excerpt.\n"
        text += canonical({"tool": request.name, "query": request.arguments,
                           "retrieved_at": record["retrieved_at"], "response": record["response"]})
        identifier = "tu-" + digest(record)[:32]
        # Multiple retrievals of the same query retain a common origin for deduplication.
        document = Document(id=identifier, origin_id="tuq-" + record["request_sha256"][:32],
                            kind=TOOLS[request.name]["kind"], text=text,
                            title="ToolUniverse record: " + request.name, url=TOOLS[request.name]["url"],
                            license="Upstream source terms apply; inspect returned source licenses.")
        if identifier in existing:
            if existing[identifier] != document:
                raise ValueError("snapshot document ID collision")
        else:
            documents.append(document)
            existing[identifier] = document
    return CaseInput.model_validate({**case.model_dump(), "documents": [d.model_dump() for d in documents]})
