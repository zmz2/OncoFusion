"""Optional public enrichment adapters. Not invoked by the default benchmark engine.

Freeze downloaded public evidence before experiments. Never send patient notes as
PubMed queries; pass reviewed biological search terms only.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from .schemas import Document


class PublicToolError(RuntimeError):
    pass


class SnapshotCache:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path(self, namespace: str, request: dict) -> Path:
        digest = hashlib.sha256(json.dumps([namespace, request], sort_keys=True).encode()).hexdigest()
        return self.root / (digest + ".json")

    def put(self, namespace: str, request: dict, response: dict | list):
        path = self.path(namespace, request)
        # Callers populate frozen snapshots serially, outside inference workers.
        path.write_text(json.dumps({"namespace": namespace, "request": request, "response": response}, ensure_ascii=False), encoding="utf-8")

    def get(self, namespace: str, request: dict):
        return json.loads(self.path(namespace, request).read_text(encoding="utf-8"))["response"]


class PubMedTool:
    BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def __init__(self, client: httpx.Client):
        self.client = client

    def search(self, query: str, limit: int = 10) -> list[str]:
        if not query.strip() or len(query) > 1000 or not 1 <= limit <= 20:
            raise ValueError("provide a short query and limit in [1,20]")
        try:
            response = self.client.get(self.BASE + "esearch.fcgi", params={
                "db": "pubmed", "term": query, "retmode": "json", "retmax": limit})
            response.raise_for_status()
            ids = response.json()["esearchresult"]["idlist"]
            if not isinstance(ids, list) or any(not isinstance(p, str) or not p.isdigit() for p in ids):
                raise ValueError("invalid IDs")
            return ids
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise PublicToolError("PubMed search failed") from exc

    def abstracts(self, pmids: list[str]) -> list[Document]:
        if not 1 <= len(pmids) <= 20 or any(not p.isdigit() for p in pmids):
            raise ValueError("provide 1-20 numeric PubMed IDs")
        try:
            response = self.client.get(self.BASE + "efetch.fcgi", params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
            response.raise_for_status()
            if len(response.content) > 2_000_000 or b"<!ENTITY" in response.content:
                raise ValueError("XML response exceeds safety boundary")
            root = ET.fromstring(response.content)
            documents = []
            for article in root.findall(".//PubmedArticle"):
                pmid = article.findtext("./MedlineCitation/PMID")
                if pmid not in pmids:
                    raise ValueError("unexpected article ID")
                title_node = article.find(".//ArticleTitle")
                title = "".join(title_node.itertext()) if title_node is not None else ""
                text = "\n".join("".join(node.itertext()) for node in article.findall(".//Abstract/AbstractText"))
                if text.strip():
                    documents.append(Document(id="pubmed-" + pmid, origin_id="pmid-" + pmid,
                                              kind="literature", text=text, title=title,
                                              url="https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/",
                                              license="Check source article reuse terms"))
            return documents
        except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
            raise PublicToolError("PubMed abstract fetch failed") from exc


class EnsemblVEPTool:
    URL = "https://rest.ensembl.org/vep/human/hgvs"

    def __init__(self, client: httpx.Client):
        self.client = client

    def annotate(self, hgvs: list[str]) -> list[dict]:
        if not 1 <= len(hgvs) <= 100 or any(not h.strip() or len(h) > 300 for h in hgvs):
            raise ValueError("provide 1-100 HGVS strings")
        try:
            response = self.client.post(self.URL, json={"hgvs_notations": hgvs}, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("invalid VEP response")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise PublicToolError("Ensembl VEP annotation failed") from exc
