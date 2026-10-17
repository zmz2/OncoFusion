"""Local dataset adapters. Evaluation labels are written to a separate sidecar."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field
from .schemas import CaseInput, Document, Identifier, StrictModel, VerificationScheme, VERIFICATION_LABELS


class GoldRecord(StrictModel):
    case_id: Identifier
    label: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    split: Literal["train", "dev", "test", "unassigned"] = "unassigned"
    relevant_document_ids: list[str] = Field(default_factory=list)


def iter_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON on line {number}") from exc


def read_jsonl(path: Path) -> list[dict]:
    return list(iter_jsonl(path))


def write_dataset(cases: list[CaseInput], gold: list[GoldRecord], output: Path, source: str) -> dict:
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)) or set(ids) != {g.case_id for g in gold} or len(gold) != len(cases):
        raise ValueError("case and gold IDs must be unique and match exactly")
    output.mkdir(parents=True, exist_ok=True)
    private = output / "_gold"
    private.mkdir(exist_ok=True, mode=0o700)
    inputs = "".join(c.model_dump_json() + "\n" for c in cases)
    labels = "".join(g.model_dump_json() + "\n" for g in gold)
    (output / "inputs.jsonl").write_text(inputs, encoding="utf-8")
    (private / "labels.jsonl").write_text(labels, encoding="utf-8")
    (private / "labels.jsonl").chmod(0o600)
    manifest = {"schema_version": "1.0", "source": source, "count": len(cases),
                "inputs_sha256": hashlib.sha256(inputs.encode()).hexdigest(),
                "labels_sha256": hashlib.sha256(labels.encode()).hexdigest()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def civic_article_reference(value: str | int) -> tuple[str, str, str]:
    """Preserve the source identifier formats observed in the pinned CIViC release."""
    source = str(value)
    if re.fullmatch(r"[0-9]+", source):
        return "pmid-" + source, "article-" + source, "https://pubmed.ncbi.nlm.nih.gov/" + source + "/"
    if re.fullmatch(r"ASH:10\.[0-9]{4,9}/\S+", source):
        digest = hashlib.sha256(source.encode()).hexdigest()
        return "source-" + digest, "article-" + digest, "https://doi.org/" + quote(source[4:], safe="/():.-")
    if re.fullmatch(r"ASCO:[0-9]+", source):
        # This namespace is an abstract identifier, not a PMID or a DOI.
        return "source-" + source, "article-" + source, ""
    raise ValueError("unsupported article identifier; inspect source namespace before importing")


def import_civicfact(rows: list[dict], refutes_label: str = "REFUTES", *,
                     verification_scheme: VerificationScheme = "refutes") -> tuple[list[CaseInput], list[GoldRecord]]:
    if refutes_label != "REFUTES":
        raise ValueError("label remapping is unsupported; preserve REVISIONS with verification_scheme=revisions")
    allowed = VERIFICATION_LABELS[verification_scheme]
    cases, gold = [], []
    for row in rows:
        label = row["gold_label_name"]
        if label not in allowed:
            raise ValueError(f"unsupported CIViC-Fact label {label!r}; inspect release semantics explicitly")
        cid = "civic-" + str(row["id"])
        origin_id, group_id, source_url = civic_article_reference(row["document.pmid"])
        evidence = row["evidence.flat"]
        # Whitelist fields; never forward civic.description, reviews, labels, or augmentation metadata.
        documents = [] if not evidence.strip() else [Document(
            id="evidence", origin_id=origin_id, kind="literature", text=evidence,
            title="" if row.get("document.title") is None else row["document.title"], url=source_url,
            license="" if row.get("document.license") is None else row["document.license"])]
        cases.append(CaseInput(id=cid, patient_id=group_id, task="verification",
                               question=row["claim.flat"], documents=documents, data_class="deidentified",
                               verification_scheme=verification_scheme))
        gold.append(GoldRecord(case_id=cid, label=label, group_id=group_id,
                               split=row["partition"]))
    return cases, gold


def parse_mcq(question: str) -> tuple[str, dict[str, str]]:
    matches = list(re.finditer(r"(?:^|\n)\s*([A-Z])[).:]\s+", question))
    if len(matches) < 2:
        raise ValueError("MCQ options must be line-separated, e.g. A) ...\nB) ...")
    options = {m[1]: question[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(question)].strip()
               for i, m in enumerate(matches)}
    if len(options) != len(matches):
        raise ValueError("duplicate MCQ option keys")
    return question[:matches[0].start()].strip(), options


def safe_source(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("source path escapes dataset root")
    if path.suffix.lower() not in (".txt", ".json", ".csv", ".tsv"):
        raise ValueError("this adapter supports text/structured files only")
    if path.stat().st_size > 100_000:
        raise ValueError("source file exceeds 100 KB; preprocess explicitly")
    return path


def import_mtbbench(records: dict[str, list[dict]], root: Path,
                    path_map: dict[str, str]) -> tuple[list[CaseInput], list[GoldRecord]]:
    """Replay native context/file_paths/question events; path_map is an explicit audited allowlist.

    root contains the downloaded source files. Keys in path_map are upstream paths;
    values are relative local paths. No filesystem globbing or recursive patient-folder ingestion.
    Retain previously announced source snapshots, mirroring visible conversation history.
    """
    cases, gold = [], []
    for patient, entries in records.items():
        docs: dict[str, Document] = {}
        question_number = 0
        for stage, entry in enumerate(entries):
            if "context" in entry and entry["context"].strip():
                sid = f"context-{stage}"
                docs[sid] = Document(id=sid, origin_id=sid, kind="clinical", text=entry["context"], available_stage=stage)
            if "file_paths" in entry:
                for upstream in entry["file_paths"]:
                    if upstream not in path_map:
                        raise ValueError("unmapped upstream file; audit and add it to path_map")
                    path = safe_source(root, path_map[upstream])
                    text = path.read_text(encoding="utf-8")
                    if not text.strip():
                        # Empty upstream files have no citable evidence. Do not infer a negative finding.
                        continue
                    sid = "file-" + hashlib.sha256(upstream.encode()).hexdigest()[:20]
                    if sid not in docs:
                        name = path.name.casefold()
                        kind = "genomics" if "mutation" in name or "genom" in name else "pathology" if "specimen" in name or "pathol" in name else "clinical"
                        docs[sid] = Document(id=sid, origin_id=sid, kind=kind, text=text,
                                             title=path.name, available_stage=stage)
            if "question" in entry:
                question, options = parse_mcq(entry["question"])
                answer = re.match(r"\s*([A-Z])(?:\s*[).:]|\s|$)", entry["answer"])
                if not answer or answer[1] not in options:
                    raise ValueError("unrecognized MTBBench answer format")
                cid = f"mtb-{patient}-q{question_number}"
                cases.append(CaseInput(id=cid, patient_id=patient, task="mcq", question=question,
                                       options=options, stage=stage, documents=list(docs.values()), data_class="deidentified"))
                gold.append(GoldRecord(case_id=cid, label=answer[1], group_id=patient))
                question_number += 1
    return cases, gold


def validate_splits(gold: list[GoldRecord]) -> None:
    groups = {}
    for row in gold:
        if row.split == "unassigned":
            continue
        previous = groups.setdefault(row.group_id, row.split)
        if previous != row.split:
            raise ValueError(f"group {row.group_id} crosses partitions")


def group_split(group_ids: list[str], seed: int = 0, dev_fraction: float = .2) -> dict[str, str]:
    if not 0 < dev_fraction < 1:
        raise ValueError("dev_fraction must be between zero and one")
    groups = sorted(set(group_ids), key=lambda g: hashlib.sha256(f"{seed}:{g}".encode()).digest())
    if len(groups) < 2:
        raise ValueError("at least two groups are required")
    count = max(1, min(len(groups) - 1, round(len(groups) * dev_fraction)))
    return {g: "dev" if i < count else "test" for i, g in enumerate(groups)}


def validate_alignment(cases: list[CaseInput], gold: list[GoldRecord]) -> None:
    """Validate external input/label joins and preserve patient/article grouping.

    Group names may be aliases, but one patient/article must map to one group.
    Call before selecting any split; otherwise cross-split aliases disappear.
    """
    labels = {g.case_id: g for g in gold}
    if len(labels) != len(gold) or len({c.id for c in cases}) != len(cases) or set(labels) != {c.id for c in cases}:
        raise ValueError("unique and exactly aligned case/gold sets required")
    validate_splits(gold)
    patients = {}
    for case in cases:
        record = labels[case.id]
        previous = patients.setdefault(case.patient_id, record.group_id)
        if previous != record.group_id:
            raise ValueError("patient/article maps to multiple evaluation groups")
