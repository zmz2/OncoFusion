"""Adapted from GeneAgent's get_pathway_for_gene_set (NLM public domain).

Source: ncbi-nlp/GeneAgent/apis/get_pathway_for_gene_set.py
Revision: 88fd1adb40dce9545bde5b904ef3a628c09d747c
Original authors: Zhizheng Wang et al.; see third_party/geneagent.LICENSE.
Changes: HTTPS/timeouts, explicit failures, validated responses, original and
adjusted p-values, per-library provenance, bounded output and no silent skips.
The upstream addList -> per-library enrich algorithm is retained.
"""
from __future__ import annotations
import re
from typing import Literal
import httpx
from pydantic import Field
from ..schemas import StrictModel
from ..tools import PublicToolError

LIBRARIES = ("Reactome_2022", "MSigDB_Hallmark_2020")


class PathwayHit(StrictModel):
    term: str
    library: str
    p_value: float = Field(ge=0, le=1)
    adjusted_p_value: float = Field(ge=0, le=1)
    overlapping_genes: list[str]
    evidence_type: Literal["gene_set_enrichment"] = "gene_set_enrichment"


def get_pathway_for_gene_set(genes: list[str], *, allow_remote: bool,
                             libraries: tuple[str, ...] = LIBRARIES,
                             client: httpx.Client | None = None) -> list[PathwayHit]:
    if not allow_remote:
        raise ValueError("review the public gene symbols and explicitly allow remote processing")
    if not 2 <= len(genes) <= 500 or len(set(genes)) != len(genes) or any(
            not isinstance(g, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,39}", g) for g in genes):
        raise ValueError("provide 2-500 unique gene symbols")
    if not libraries or len(set(libraries)) != len(libraries) or set(libraries) - set(LIBRARIES):
        raise ValueError("choose unique libraries from the frozen allowlist")
    own = client is None
    client = httpx.Client(timeout=30, follow_redirects=False) if own else client
    base = "https://maayanlab.cloud/Enrichr/"
    try:
        added = client.post(base + "addList", files={"list": (None, "\n".join(genes)),
                                                   "description": (None, "OncoFusion reviewed public gene set")})
        added.raise_for_status()
        list_id = added.json()["userListId"]
        if type(list_id) is not int or list_id < 1:
            raise ValueError("invalid Enrichr list identifier")
        hits = []
        for library in libraries:
            response = client.get(base + "enrich", params={"userListId": list_id, "backgroundType": library})
            response.raise_for_status()
            rows = response.json()[library]
            if not isinstance(rows, list):
                raise ValueError("invalid Enrichr library response")
            for row in rows[:5]:
                hits.append(PathwayHit(term=row[1], library=library, p_value=row[2],
                                       adjusted_p_value=row[6], overlapping_genes=row[5]))
        return sorted(hits, key=lambda h: (h.adjusted_p_value, h.p_value, h.library, h.term))
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as exc:
        raise PublicToolError("GeneAgent-derived pathway enrichment failed") from exc
    finally:
        if own:
            client.close()
