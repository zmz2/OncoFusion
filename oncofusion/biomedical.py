"""Read-only, allowlisted ToolUniverse integration for reviewed evidence preparation.

TxAgent uses ToolUniverse; this module imports that SDK directly, not TxAgent's
GPU model. Live enrichment is separate from closed benchmark inference.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from .schemas import StrictModel, Document, Entities, CaseInput
from .tools import PublicToolError

# A deliberately small subset of upstream read-only tools. Upstream still validates
# exact parameter schemas; these caps constrain the user-facing preparation boundary.
ALLOWED_TOOLS = {
    "MyGene_query_genes": ("genomics", "https://mygene.info/", {"query", "species", "fields", "size"}),
    "Reactome_map_uniprot_to_pathways": ("genomics", "https://reactome.org/", {"uniprot_id"}),
    "OncoTree_get_type": ("pathology", "https://oncotree.mskcc.org/", {"code", "version"}),
    "ChEMBL_get_drug_mechanisms": ("therapy", "https://www.ebi.ac.uk/chembl/", {"drug_chembl_id", "limit"}),
    "OpenTargets_get_associated_drugs_by_target_ensemblID": ("therapy", "https://platform.opentargets.org/", {"ensemblId"}),
    "PubMed_search_articles": ("literature", "https://pubmed.ncbi.nlm.nih.gov/",
                               {"query", "limit", "mindate", "maxdate", "datetype", "include_abstract", "sort"}),
}


class ToolQuery(StrictModel):
    name: str
    arguments: dict[str, Any]
    purpose: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def reviewed_boundary(self):
        if self.name not in ALLOWED_TOOLS:
            raise ValueError("tool is outside the reviewed biomedical allowlist")
        if set(self.arguments) - ALLOWED_TOOLS[self.name][2]:
            raise ValueError("unsupported tool arguments")
        if len(json.dumps(self.arguments)) > 2000:
            raise ValueError("supply reviewed identifiers/search terms, not patient notes")
        query = self.arguments.get("query")
        if query is not None and (not isinstance(query, str) or not query.strip() or len(query) > 240):
            raise ValueError("query must be a reviewed public search expression of 1-240 characters")
        for name in ("size", "limit"):
            if name in self.arguments and (type(self.arguments[name]) is not int or not 1 <= self.arguments[name] <= 10):
                raise ValueError("search result count must be in [1,10]")
        if self.name == "OncoTree_get_type" and not self.arguments.get("version"):
            raise ValueError("record an explicit OncoTree version; latest alias is allowed only with a frozen response")
        return self


class EvidenceSnapshot(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    toolkit: str
    toolkit_version: str
    query: ToolQuery
    fetched_at: str
    response_sha256: str
    response: dict | list
    interpretation: str = "External knowledge context; not a patient observation or independently verified clinical conclusion."

    @model_validator(mode="after")
    def valid_digest(self):
        if response_digest(self.response) != self.response_sha256:
            raise ValueError("snapshot content checksum mismatch")
        return self

    def document(self, *, stage: int, entities: Entities | None = None) -> Document:
        kind, url, _ = ALLOWED_TOOLS[self.query.name]
        text = json.dumps({"source_tool": self.query.name, "fetched_at": self.fetched_at,
                           "query": self.query.arguments, "interpretation": self.interpretation,
                           "response": self.response}, ensure_ascii=False, sort_keys=True)
        # Keep the whole source response; oversized snapshots fail rather than silently truncating.
        return Document(id="snapshot-" + self.response_sha256[:32], origin_id="tool-" + self.query.name,
                        kind=kind, text=text, available_stage=stage, entities=entities or Entities(),
                        title=self.query.name, url=url, license="Consult the underlying database/article terms")


    def documents(self, *, stage: int) -> list[Document]:
        if self.query.name != "PubMed_search_articles":
            return [self.document(stage=stage)]
        articles = self.response["data"] if isinstance(self.response, dict) else self.response
        if not isinstance(articles, list):
            raise ValueError("PubMed snapshot requires an article list")
        result = []
        for article in articles:
            pmid, abstract = article.get("pmid"), article.get("abstract")
            if not isinstance(pmid, str) or not pmid.isdigit() or not isinstance(abstract, str) or not abstract.strip():
                raise ValueError("PubMed attachment requires actual abstracts and PMIDs; metadata-only results stay in the snapshot")
            result.append(Document(id="pubmed-" + pmid, origin_id="pmid-" + pmid,
                kind="literature", text=abstract, title=article.get("title") or "",
                available_stage=stage, url="https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/",
                license="Consult source article reuse terms"))
        return result


def response_digest(value: dict | list) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class ToolUniverseAdapter:
    """Actual SDK execution with all code-execution tools and hooks excluded."""
    def __init__(self):
        from tooluniverse import ToolUniverse
        self.version = version("tooluniverse")
        self.sdk = ToolUniverse(load_workspace=False, hooks_enabled=False, log_level="ERROR")
        self.sdk.load_tools(include_tools=list(ALLOWED_TOOLS), quiet=True)
        if set(self.sdk.all_tool_dict) != set(ALLOWED_TOOLS):
            raise RuntimeError("installed ToolUniverse does not expose the pinned allowlist")

    def schema(self, name: str) -> dict:
        if name not in ALLOWED_TOOLS:
            raise ValueError("tool is outside the allowlist")
        return self.sdk.all_tool_dict[name]["parameter"]

    def execute(self, query: ToolQuery, *, allow_remote: bool) -> EvidenceSnapshot:
        if not allow_remote:
            raise ValueError("public term review and explicit remote-processing consent are required")
        import jsonschema
        jsonschema.validate(query.arguments, self.schema(query.name))
        try:
            response = self.sdk.run_one_function({"name": query.name, "arguments": query.arguments},
                                                use_cache=False, validate=True)
            if isinstance(response, str):
                response = json.loads(response)
            if not isinstance(response, (dict, list)):
                raise ValueError("tool returned a non-JSON evidence response")
            if isinstance(response, dict) and (response.get("error") or response.get("status") in {"error", "failed"}):
                raise PublicToolError("upstream tool returned an error; no snapshot created")
            digest = response_digest(response)
        except (ValueError, TypeError) as exc:
            raise PublicToolError("invalid upstream tool response") from exc
        return EvidenceSnapshot(toolkit="ToolUniverse", toolkit_version=self.version, query=query,
                                fetched_at=datetime.now(timezone.utc).isoformat(),
                                response=response, response_sha256=digest)


def save_snapshot(snapshot: EvidenceSnapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A frozen file is immutable. A new acquisition goes to a new versioned directory.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(snapshot.model_dump_json(indent=2))


def enrich_synthesis_case(case: CaseInput, snapshots: list[EvidenceSnapshot]) -> CaseInput:
    """Attach reviewed snapshots only to an explicit open-evidence synthesis task."""
    if case.task != "synthesis":
        raise ValueError("external enrichment is separate from closed verification/MCQ benchmarks")
    documents = list(case.documents)
    existing = {d.id: d for d in documents}
    for snapshot in snapshots:
        for document in snapshot.documents(stage=case.stage):
            if document.id in existing and existing[document.id] != document:
                raise ValueError("conflicting source content under the same document ID")
            if document.id not in existing:
                documents.append(document)
                existing[document.id] = document
    return CaseInput.model_validate({**case.model_dump(), "documents": [d.model_dump() for d in documents]})
