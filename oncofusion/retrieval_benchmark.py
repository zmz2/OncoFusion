"""Article-local passage retrieval with independently held-out relevance labels.

Relevance is derived from >=75% overlap with a curated evidence span. This is a
versioned evaluation protocol, not a claim to reproduce every upstream IR metric.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .datasets import GoldRecord, validate_splits, write_dataset
from .evaluation import retrieval_metrics
from .evidence import retrieve
from .preparation import claim_entities, dataset_audit
from .schemas import CaseInput, Document


def import_retrieval(queries: Iterable[dict], chunks: Iterable[dict], min_overlap: float = .75, *,
                     exclude_conflicts: bool = False):
    if not 0 < min_overlap <= 1:
        raise ValueError("min_overlap must be in (0,1]")
    by_article = defaultdict(list)
    for row in chunks:
        start, end = int(row["chunk.start"]), int(row["chunk.end"])
        if start < 0 or end <= start or end - start != len(row["chunk.text"]):
            raise ValueError("chunk offsets and text length differ")
        pmid = str(row["document.pmid"])
        document = Document(id="chunk-" + row["chunk.id"], origin_id="pmid-" + pmid,
                            kind="literature", text=row["chunk.text"], license=row.get("license", ""))
        by_article[pmid].append((document, start, end, row["partition"]))
    grouped = {}
    conflicts = set()
    merged_rows = 0
    for row in queries:
        key = (str(row["document.pmid"]), row["claim.flat"])
        if key in grouped:
            existing = grouped[key]
            if row.get("gold_label_name", "SUPPORTS") != existing.get("gold_label_name", "SUPPORTS"):
                if not exclude_conflicts:
                    raise ValueError("duplicate retrieval query has conflicting source labels")
                conflicts.add(key)
            existing["evidence"].extend(row["evidence"])
            merged_rows += 1
        else:
            grouped[key] = {**row, "evidence": list(row["evidence"])}
    cases, gold, excluded = [], [], []
    for number, row in enumerate(grouped.values()):
        pmid, question = str(row["document.pmid"]), row["claim.flat"]
        # A query groups all equivalent curated selections for one claim in one article.
        cid = "retrieval-" + hashlib.sha256((pmid + "\0" + question).encode()).hexdigest()[:32]
        if (pmid, question) in conflicts:
            excluded.append({"row": number, "case_id": cid, "reason": "same article and claim have conflicting evidence labels"})
            continue
        if row.get("gold_label_name") == "NEI":
            excluded.append({"row": number, "case_id": cid, "reason": "NEI has no retrieval relevance target"})
            continue
        spans = []
        for evidence in row["evidence"]:
            meta = evidence.get("meta", {})
            if meta.get("start") is not None and meta.get("end") is not None:
                start, end = int(meta["start"]), int(meta["end"])
                if start < 0 or end <= start:
                    raise ValueError("invalid curated evidence offsets")
                spans.append((start, end))
        source = by_article.get(pmid, [])
        relevant = [d.id for d, a, b, _ in source if any(max(0, min(b, y) - max(a, x)) / (y - x) >= min_overlap for x, y in spans)]
        if len(source) > 500 or sum(len(d.text) for d, _, _, _ in source) > 1_000_000:
            excluded.append({"row": number, "case_id": cid, "reason": "article exceeds declared runtime schema limits"})
            continue
        if not source or not spans or not relevant:
            excluded.append({"row": number, "case_id": cid, "reason": "missing article, aligned spans or relevant chunks"})
            continue
        splits = {part for _, _, _, part in source}
        if len(splits) != 1:
            raise ValueError("one article appears in multiple partitions")
        cases.append(CaseInput(id=cid, patient_id="article-" + pmid, task="verification", question=question,
                               entities=claim_entities(row), documents=[d for d, _, _, _ in source], data_class="deidentified"))
        gold.append(GoldRecord(case_id=cid, group_id="article-" + pmid, label=row.get("gold_label_name", "SUPPORTS"),
                               split=next(iter(splits)), relevant_document_ids=relevant))
    validate_splits(gold)
    return cases, gold, {"merged_duplicate_rows": merged_rows, "min_curated_span_overlap": min_overlap, "included": len(cases), "excluded": excluded,
                         "conflicting_query_groups": len(conflicts),
                         "source_metadata_forwarded": ["chunk.id", "document.pmid", "chunk.text", "license"],
                         "scope": "same source article, not global PubMed retrieval"}


def prepare_retrieval(queries, chunks, output: Path, allow_exclusions: bool = False):
    cases, gold, audit = import_retrieval(queries, chunks, exclude_conflicts=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "retrieval_audit.json").write_text(json.dumps(audit, indent=2))
    if not cases:
        raise ValueError("no aligned retrieval samples; inspect retrieval_audit.json")
    if audit["excluded"] and not allow_exclusions:
        raise ValueError("retrieval rows excluded; review audit and explicitly allow exclusions")
    manifest = write_dataset(cases, gold, output, "CIViC-Fact article-local curated-span retrieval")
    (output / "audit.json").write_text(json.dumps(dataset_audit(cases, gold), indent=2))
    return {"manifest": manifest, "audit": audit}


def evaluate_retrieval(cases: list[CaseInput], gold: list[GoldRecord], ks=(1, 3, 6, 10)) -> dict:
    validate_splits(gold)
    labels = {g.case_id: g for g in gold}
    if not cases or len(labels) != len(gold) or len({c.id for c in cases}) != len(cases) or set(labels) != {c.id for c in cases}:
        raise ValueError("aligned unique cases and relevance labels required")
    if not ks or any(k < 1 or k > 100 for k in ks):
        raise ValueError("provide retrieval k in [1,100]")
    rows = []
    for case in cases:
        target = labels[case.id]
        relevant = set(target.relevant_document_ids)
        if not relevant or not relevant <= {d.id for d in case.documents}:
            raise ValueError("relevance labels must identify source chunks")
        for rerank in (False, True):
            ranked = retrieve(case.question, case.documents, max(ks), max(20, max(ks)), case.entities, rerank)
            row = {"case_id": case.id, "group_id": target.group_id, "method": "bm25_entity" if rerank else "bm25",
                   "ranked_ids": [d.id for d in ranked], "metrics": {str(k): retrieval_metrics(relevant, [d.id for d in ranked], k) for k in ks}}
            rows.append(row)
    aggregate = {}
    for method in ("bm25", "bm25_entity"):
        subset = [r for r in rows if r["method"] == method]
        aggregate[method] = {str(k): {metric: statistics.mean(r["metrics"][str(k)][metric] for r in subset)
                                    for metric in ("recall_at_k", "average_precision_at_k")} for k in ks}
    return {"task": "article_local_retrieval", "model_api_calls": 0, "count": len(cases), "metrics": aggregate,
            "protocol": "curated-span overlap relevance; source-entity reranker is lexical, not neural", "rows": rows}
