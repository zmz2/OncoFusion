"""Offline evidence tools with mandatory visibility and citation boundaries."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from .schemas import CaseInput, Citation, Document, Entities, Finding, FragmentCitation

AMINO = dict(zip(
    "Ala Arg Asn Asp Cys Gln Glu Gly His Ile Leu Lys Met Phe Pro Ser Thr Trp Tyr Val".split(),
    "ARNDCQEGHILKMFPSTWYV",
))


def canonical_variant(value: str) -> str:
    """Protein substitutions only; preserve unsupported HGVS verbatim."""
    value = value.strip()
    match = re.fullmatch(r"(?:p\.)?([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})", value)
    if match and match[1] in AMINO and match[3] in AMINO:
        return AMINO[match[1]] + match[2] + AMINO[match[3]]
    match = re.fullmatch(r"(?:p\.)?([A-Z]\d+[A-Z*])", value)
    return match[1] if match else value


def normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def tokens(text: str) -> list[str]:
    return re.findall(r"[\w]+", text.casefold())


def polarity(text: str) -> str:
    """Lexical feature, not a clinical assertion or a semantic verifier."""
    low = text.casefold()
    resistant = bool(re.search(r"\b(resistant|resistance|insensitive|nonresponse)\b|not sensitive|no response", low))
    sensitive = bool(re.search(r"\b(sensitive|sensitivity|responded|response)\b", low))
    positive_text = re.sub(r"not sensitive|no response|nonresponse|insensitive", "", low)
    sensitive = bool(re.search(r"\b(sensitive|sensitivity|responded|response)\b", positive_text))
    if resistant and sensitive:
        return "mixed"
    return "resistance" if resistant else "sensitivity" if sensitive else "unknown"


def visible_case(case: CaseInput) -> CaseInput:
    docs = [d for d in case.documents if d.available_stage <= case.stage
            and (case.as_of_day is None or d.event_day is None or d.event_day <= case.as_of_day)]
    return case.model_copy(update={"documents": docs}, deep=True)


def check_citations(citations: list[Citation], docs: list[Document]) -> None:
    allowed = {d.id: d for d in docs}
    for c in citations:
        if c.document_id not in allowed:
            raise ValueError("citation refers to an unavailable document")
        if c.start is None:
            text = allowed[c.document_id].text
            start = text.find(c.quote)
            if start < 0 or text.find(c.quote, start + 1) >= 0:
                raise ValueError("quote must match exactly once when offsets are omitted")
            c.start, c.end = start, start + len(c.quote)
        if allowed[c.document_id].text[c.start:c.end] != c.quote or c.end > len(allowed[c.document_id].text):
            raise ValueError("citation quote does not match the source span")


def quote_document(doc: Document, limit: int = 600) -> Citation:
    quote = doc.text[:limit]
    return Citation(document_id=doc.id, start=0, end=len(quote), quote=quote)


def citation_key(c: Citation, docs: dict[str, Document]) -> tuple:
    return (docs[c.document_id].origin_id, c.start, c.end, c.quote)


def deduplicate_findings(findings: list[Finding], documents: list[Document]) -> list[Finding]:
    docs, seen, result = {d.id: d for d in documents}, set(), []
    for finding in findings:
        sources = tuple(sorted({citation_key(c, docs) for c in finding.citations}))
        key = (normalized(finding.statement), finding.relation, sources)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result


def deduplicate_documents(documents: list[Document]) -> list[Document]:
    seen, result = set(), []
    for doc in documents:
        key = (doc.origin_id, hashlib.sha256(doc.text.encode()).hexdigest())
        if key not in seen:
            seen.add(key)
            result.append(doc)
    return result


def entity_compatibility(query: Entities, source: Entities, normalize_variant: bool = True) -> dict[str, str]:
    result = {}
    for field in ("gene", "variant", "disease", "drug"):
        left, right = getattr(query, field), getattr(source, field)
        if not left or not right:
            result[field] = "unknown"
        else:
            if field == "variant" and normalize_variant:
                left, right = canonical_variant(left), canonical_variant(right)
            result[field] = "match" if normalized(left) == normalized(right) else "mismatch"
    return result


def retrieve(query: str, documents: list[Document], top_k: int, candidate_k: int,
             entities: Entities, rerank: bool = True, *,
             normalize_variant: bool = True, match_disease: bool = True) -> list[Document]:
    """BM25 shortlist then transparent entity-overlap reranking (not a neural reranker)."""
    if not documents:
        return []
    bags = [Counter(tokens(d.text + " " + d.title)) for d in documents]
    lengths = [sum(b.values()) for b in bags]
    avg = sum(lengths) / len(lengths) or 1
    terms = set(tokens(query))
    df = {t: sum(t in b for b in bags) for t in terms}
    scores = []
    for d, bag, length in zip(documents, bags, lengths):
        score = 0.0
        for t in terms:
            freq = bag[t]
            idf = math.log(1 + (len(documents) - df[t] + .5) / (df[t] + .5))
            score += idf * freq * 2.5 / (freq + 1.5 * (.25 + .75 * length / avg))
        scores.append((score, d))
    candidates = sorted(scores, key=lambda x: (-x[0], x[1].id))[:candidate_k]
    if rerank:
        def key(item):
            score, doc = item
            matches = entity_compatibility(entities, doc.entities, normalize_variant)
            if not match_disease:
                del matches["disease"]
            # Raw passage corpora may not carry curated entity metadata. Literal
            # query-entity mentions supply a transparent, query-only coverage feature.
            for field, state in matches.items():
                entity = getattr(entities, field)
                if state == "unknown" and entity and re.search(r"(?<!\w)" + re.escape(entity) + r"(?!\w)", doc.text, re.I):
                    matches[field] = "match"
            bonus = sum(1 if x == "match" else -1 if x == "mismatch" else 0 for x in matches.values())
            return (-bonus, -score, doc.id)
        candidates.sort(key=key)
    return [d for _, d in candidates[:top_k]]


def evidence_graph(reports, docs: list[Document], decision=None) -> dict:
    nodes = [{"id": "source:" + d.id, "type": "source", "origin_id": d.origin_id, "title": d.title} for d in docs]
    edges = []
    for i, report in enumerate(reports):
        for j, finding in enumerate(report.output.findings):
            fid = f"finding:{i}:{j}"
            nodes.append({"id": fid, "type": "finding", "role": report.role,
                          "statement": finding.statement, "relation": finding.relation})
            edges.extend({"source": "source:" + c.document_id, "target": fid, "type": "cited_by",
                          "start": c.start, "end": c.end} for c in finding.citations)
    if decision is not None:
        nodes.append({"id": "decision", "type": "decision", "answer": decision.answer,
                      "explanation": decision.explanation, "unresolved": decision.unresolved})
        edges.extend({"source": "source:" + c.document_id, "target": "decision", "type": "cited_by",
                      "start": c.start, "end": c.end} for c in decision.citations)
    return {"nodes": nodes, "edges": edges}


def variant_mentions(documents: list[Document]) -> list[dict]:
    """Source-grounded spelling normalization, without inferring pathogenicity or activity."""
    aa = "(?:" + "|".join(AMINO) + ")"
    pattern = re.compile(r"(?<![A-Za-z0-9])(?:p\.)?(?:" + aa + r"\d{1,6}" + aa + r"|[ACDEFGHIKLMNPQRSTVWY]\d{1,6}[ACDEFGHIKLMNPQRSTVWY*])(?![A-Za-z0-9_])")
    mentions = []
    for doc in documents:
        if doc.kind not in ("genomics", "literature"):
            continue
        for match in pattern.finditer(doc.text):
            mentions.append({"document_id": doc.id, "start": match.start(), "end": match.end(),
                             "raw": match[0], "canonical": canonical_variant(match[0])})
            if len(mentions) >= 200:
                return mentions
    return mentions


def pathology_fields(documents: list[Document]) -> list[dict]:
    """Extract explicit labeled disease/specimen fields only; retain source spans."""
    labels = r"(?:cancer[_ ]type(?:[_ ]detailed)?|histology|histological[_ ](?:type|diagnosis)|primary[_ ]site|specimen[_ ]type|oncotree[_ ]code)"
    pattern = re.compile(r'[\"\']?(' + labels + r')[\"\']?\s*[:\t]\s*[\"\']?([^\n\r\"\',}]+)', re.I)
    rows = []
    for doc in documents:
        if doc.kind != "pathology":
            continue
        for match in pattern.finditer(doc.text):
            rows.append({"document_id": doc.id, "field": normalized(match[1]), "value": match[2].strip(),
                         "start": match.start(), "end": match.end()})
            if len(rows) >= 100:
                return rows
    return rows


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-\']{2,}")
_STOPWORDS = {"the", "and", "that", "with", "from", "will", "have", "has", "had", "not", "for",
              "are", "was", "were", "what", "which", "when", "does", "did", "patient", "patients",
              "this", "than", "then", "into", "about", "after", "before", "per"}
# A record that carries one of these is a candidate the specialist roles cannot do without.
# Deliberately excludes plain "AGE:" lines: in MTBBench timelines every record has one, and
# forcing all of them degenerates back into sending only the first records of the document.
KEY_FIELD = re.compile(
    r"MUTATION|AMPLIFIC|DELETION|FUSION|VARIANT|CANCER|ONCOTREE|SUBTYPE|GRADE|STAGE|"
    r"SPECIMEN|BIOPSY|HISTOLOG|DRUG|TREATMENT|THERAPY|MEDICAT|EXPOSURE", re.I)
NEWEST_EVENT = re.compile(r"(?:AGE|DAY)[\s:]+(\d+(?:\.\d+)?)")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-\']{2,}")
_STOPWORDS = {"the", "and", "that", "with", "from", "will", "have", "has", "had", "not", "for",
              "are", "was", "were", "what", "which", "when", "does", "did", "patient", "patients",
              "this", "than", "then", "into", "about", "after", "before", "per"}


def _question_terms(query: str) -> set[str]:
    return {t.lower() for t in _WORD.findall(query or "")} - _STOPWORDS


def fragment_spans(text: str, chars: int) -> list[tuple[int, int]]:
    """Record-aligned spans covering the whole text.

    A span ends after a completed line and the newline advances exactly one character, so the
    next span starts on the first letter of the next record (a two-character stride used to clip
    the leading "A" off the following "AGE:"). Only a single record longer than the span budget
    is split, and then only at a sentence or clause boundary, never inside a word.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        stop = min(len(text), start + chars)
        if stop < len(text):
            cut = text.rfind("\n", start, stop)
            if cut >= start:
                stop = cut + 1
            else:
                cut = max((text.rfind(sep, start, stop) for sep in (". ", "; ", ", ", " ")), default=-1)
                stop = cut + 2 if text[cut:cut + 2] in (". ", "; ") and cut > start else cut + 1
                if cut <= start:
                    stop = min(len(text), start + chars)
        if stop <= start:
            stop = min(len(text), start + chars)
        spans.append((start, stop))
        start = stop
    return spans


def _must_send(text: str, spans: list[tuple[int, int]]) -> set[int]:
    """First record, last record, and the record holding the newest AGE/DAY observation."""
    forced = {0, len(spans) - 1}
    best_value, best_index = None, None
    for i, (s, e) in enumerate(spans):
        for match in NEWEST_EVENT.finditer(text[s:e]):
            value = float(match[1])
            if best_value is None or value >= best_value:
                best_value, best_index = value, i
    if best_index is not None:
        forced.add(best_index)
    return forced


def fragment_documents(documents: list[Document], chars: int, per_document: int,
                       query: str = "", budget: int | None = None):
    """Plan this stage's evidence: number every span, send a selected subset, report coverage.

    Candidates span the full text of every stage-visible document. Each document gets a share of
    the character budget and always contributes its first record, its last record and the newest
    dated observation, so the clinical tail that used to be cut off is never what gets dropped.
    Leftover budget is spent on molecular/pathology key fields first, then on question overlap.
    Only sent ids resolve, so citing evidence the model never received still fails visibly.
    """
    if not documents:
        return [], {}, {"documents": {}, "candidates": 0, "sent": 0, "chars_total": 0,
                        "chars_sent": 0, "budget_characters": 0, "fragment_characters": chars,
                        "fragments_per_document": per_document, "tail_dropped": False}
    budget = budget if budget else max(24_000, len(documents) * per_document * chars)
    share = max(chars, budget // len(documents))
    terms = _question_terms(query)

    planned = []
    for doc in documents:
        spans = fragment_spans(doc.text, chars)
        must = _must_send(doc.text, spans)
        key = {i for i, (s, e) in enumerate(spans) if KEY_FIELD.search(doc.text[s:e])}
        scored = []
        for i, (s, e) in enumerate(spans):
            overlap = len(terms & {t.lower() for t in _WORD.findall(doc.text[s:e])})
            tier = 0 if i in must else (1 if i in key else 2)
            scored.append((tier, -overlap, i, s, e))
        planned.append((doc, spans, must, sorted(scored, key=lambda c: (c[0], c[1], c[2]))))

    chosen: dict[str, list[int]] = {doc.id: [] for doc, _, _, _ in planned}
    spent = 0
    # first pass: every visible document must be represented inside its own share
    for doc, spans, must, ranked in planned:
        doc_spent = 0
        for tier, _, i, s, e in sorted(ranked, key=lambda c: (0 if c[2] in must else 1, c[2])):
            if i not in must:
                continue
            if chosen[doc.id] and spent + (e - s) > budget and doc_spent + (e - s) > share:
                break
            chosen[doc.id].append(i)
            doc_spent += e - s
            spent += e - s
    # second pass: spend what is left on key fields, then on question overlap
    leftovers = [(tier, overlap, i, doc, s, e) for doc, spans, must, ranked in planned
                 for tier, overlap, i, s, e in ranked if i not in chosen[doc.id]]
    for tier, overlap, i, doc, s, e in sorted(leftovers, key=lambda c: (c[0], c[1], c[3].id, c[2])):
        if spent + (e - s) > budget or len(chosen[doc.id]) >= per_document:
            continue
        chosen[doc.id].append(i)
        spent += e - s

    listed: list[dict] = []
    index: dict[str, tuple[Document, int, int]] = {}
    coverage: dict[str, dict] = {}
    for doc, spans, must, _ in planned:
        picked = sorted(set(chosen[doc.id]))
        sent_ids = []
        for i in picked:
            s, e = spans[i]
            evidence_id = "%s:f%02d" % (doc.id, i + 1)
            listed.append({"evidence_id": evidence_id, "document_id": doc.id, "kind": doc.kind,
                           "stage": doc.available_stage, "text": doc.text[s:e],
                           "forced": bool(i in must), "position": i + 1, "record_span": [s, e]})
            index[evidence_id] = (doc, s, e)
            sent_ids.append(evidence_id)
        coverage[doc.id] = {"candidates": len(spans), "sent": len(sent_ids),
                            "chars_total": len(doc.text),
                            "chars_sent": sum(spans[i][1] - spans[i][0] for i in picked),
                            "key_records": sum(1 for i in picked if i in must),
                            "share_characters": share, "evidence_ids": sent_ids}
    listed.sort(key=lambda f: (f["document_id"], f["position"]))
    return listed, index, {
        "documents": coverage,
        "candidates": sum(v["candidates"] for v in coverage.values()),
        "sent": sum(v["sent"] for v in coverage.values()),
        "chars_total": sum(v["chars_total"] for v in coverage.values()),
        "chars_sent": sum(v["chars_sent"] for v in coverage.values()),
        "budget_characters": budget,
        "fragment_characters": chars,
        "fragments_per_document": per_document,
        "documents_without_evidence": [d for d, v in coverage.items() if not v["sent"]],
        "tail_dropped": any(v["sent"] < v["candidates"] for v in coverage.values()),
    }


def resolve_fragment_citations(citations: list[FragmentCitation], index: dict) -> list[Citation]:
    """Turn selected fragment ids into source-checked citations; unknown ids fail the run visibly."""
    resolved = []
    for c in citations:
        entry = index.get(c.evidence_id)
        if entry is None:
            raise ValueError("citation refers to an evidence fragment that was not supplied for this stage")
        doc, start, end = entry
        resolved.append(Citation(document_id=doc.id, quote=doc.text[start:end], start=start, end=end))
    return resolved
