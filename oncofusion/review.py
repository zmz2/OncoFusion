"""Deterministic blinded citation review sheets; semantic support requires human labels."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from .experiments import StudyPlan, perturb
from .schemas import CaseInput, RunResult

COLUMNS = ("review_id", "question", "claim", "relation", "quote", "source_text", "supports", "comment")
LABELS = {"yes", "no", "unclear"}


def write_csv(path: Path, rows: list[dict], columns=COLUMNS):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def export_review(study_dir: Path, cases: list[CaseInput], output: Path, limit: int = 200, seed: int = 0):
    if not 1 <= limit <= 5000:
        raise ValueError("review limit must be in [1,5000]")
    identity = json.loads((study_dir / "identity.json").read_text())
    plan = StudyPlan.model_validate(identity["plan"])
    by_id = {c.id: c for c in cases}
    if len(by_id) != len(cases):
        raise ValueError("duplicate case IDs")
    rows, keys = [], {}
    for treatment in plan.treatments:
        for repeat in plan.seeds:
            directory = study_dir / treatment.name / str(repeat)
            for path in sorted(directory.glob("*.json")):
                if path.name == "summary.json" or path.name.endswith(".failed.json"):
                    continue
                result = RunResult.model_validate_json(path.read_text())
                source_case = perturb(by_id[result.case_id], treatment.perturbation, repeat)
                docs = {d.id: d for d in source_case.documents}
                findings = [(f.statement, f.relation, f.citations) for report in result.reports for f in report.output.findings]
                if result.decision:
                    findings.append((result.decision.explanation, result.decision.answer, result.decision.citations))
                for index, (claim, relation, citations) in enumerate(findings):
                    for j, citation in enumerate(citations):
                        rid = hashlib.sha256(f"{seed}:{treatment.name}:{repeat}:{result.case_id}:{index}:{j}".encode()).hexdigest()[:24]
                        rows.append({"review_id": rid, "question": source_case.question, "claim": claim,
                                     "relation": relation, "quote": citation.quote, "source_text": docs[citation.document_id].text,
                                     "supports": "", "comment": ""})
                        keys[rid] = {"treatment": treatment.name, "seed": repeat, "case_id": result.case_id,
                                     "finding_index": index, "citation_index": j}
    rows = sorted(rows, key=lambda row: row["review_id"])[:limit]
    if not rows:
        raise ValueError("no citations available for review")
    output.mkdir(parents=True, exist_ok=True)
    for reviewer in ("A", "B"):
        write_csv(output / f"reviewer_{reviewer}.csv", rows)
    private = output / "_private"
    private.mkdir(exist_ok=True, mode=0o700)
    key_path = private / "blinding_key.json"
    key_path.write_text(json.dumps({row["review_id"]: keys[row["review_id"]] for row in rows}, indent=2))
    key_path.chmod(0o600)
    return {"count": len(rows), "scope": "sampled cited claims, not uncited claims", "seed": seed,
            "instructions": "Each reviewer independently marks yes/no/unclear. Keep _private away from reviewers."}


def read_review(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    result = {}
    for row in rows:
        rid, value = row["review_id"], row["supports"].strip().lower()
        if not rid or rid in result or value not in LABELS:
            raise ValueError("review requires unique nonempty IDs and yes/no/unclear labels")
        result[rid] = value
    if not result:
        raise ValueError("review is empty")
    return result


def score_reviews(first: Path, second: Path) -> dict:
    a, b = read_review(first), read_review(second)
    if set(a) != set(b):
        raise ValueError("reviewers must annotate exactly the same items")
    n = len(a)
    counts_a, counts_b = Counter(a.values()), Counter(b.values())
    agreement = sum(a[k] == b[k] for k in a) / n
    expected = sum(counts_a[v] * counts_b[v] for v in LABELS) / (n * n)
    return {"count": n, "agreement": agreement, "cohen_kappa": (agreement - expected) / (1 - expected) if expected < 1 else None,
            "reviewer_A_support_fraction": counts_a["yes"] / n, "reviewer_B_support_fraction": counts_b["yes"] / n,
            "conservative_agreed_support_fraction": sum(a[k] == b[k] == "yes" for k in a) / n,
            "requires_adjudication": [k for k in sorted(a) if a[k] != b[k] or a[k] == "unclear"],
            "interpretation": "Human semantic labels; conservative fraction is not a substitute for adjudicated consensus."}
