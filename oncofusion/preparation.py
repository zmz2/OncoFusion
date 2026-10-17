"""Auditable dataset acquisition and import helpers. No inference-time downloads."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path, PurePosixPath

import httpx
from .datasets import GoldRecord, import_civicfact, import_mtbbench, group_split, read_jsonl, validate_alignment, write_dataset
from .schemas import CaseInput, Entities, VerificationScheme
from .profiles import coverage_report

CIVIC_REVISION = "1a767d889b015a836f0f4331afcac5cef165ec7f"
CIVIC_FILE = "data_builder/builds/civicfact-2026.06.09/data.jsonl.gz"
CIVIC_BLOB = "af1b4ee457b2f96f661a27ecce72e1c938dc8c4c"
CIVIC_URL = f"https://raw.githubusercontent.com/creisle/civicfact/{CIVIC_REVISION}/{CIVIC_FILE}"
HF_REPO = "EeshaanJain/MTBBench"


def download(client: httpx.Client, url: str, destination: Path, max_bytes: int = 100_000_000,
             git_blob: str | None = None) -> dict:
    """Caller supplies a trusted source URL. Write atomically, pin and record checksums."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    try:
        with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            size = 0
            with tmp.open("wb") as stream:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("download exceeds configured size limit")
                    stream.write(chunk)
        raw = tmp.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if git_blob and blob != git_blob:
            raise ValueError("upstream Git blob checksum differs from the pinned version")
        tmp.replace(destination)
        return {"url": url, "bytes": size, "sha256": hashlib.sha256(raw).hexdigest(), "git_blob_sha1": blob}
    finally:
        tmp.unlink(missing_ok=True)


def build_path_map(upstream_paths: list[str], local_paths: list[str]) -> dict[str, str]:
    """Longest suffix match of >=2 path components; ambiguity is an explicit failure."""
    mapped = {}
    for source in sorted(set(upstream_paths)):
        parts = PurePosixPath(source.replace("\\", "/")).parts
        best, candidates = 0, []
        for local in local_paths:
            target = PurePosixPath(local).parts
            common = 0
            for a, b in zip(reversed(parts), reversed(target)):
                if a != b:
                    break
                common += 1
            if common > best:
                best, candidates = common, [local]
            elif common == best:
                candidates.append(local)
        if best < 2 or len(candidates) != 1:
            raise ValueError(f"ambiguous or missing source mapping: {source}; candidates={candidates[:5]}")
        mapped[source] = candidates[0]
    return mapped


def claim_entities(row: dict) -> Entities:
    """Extract only declared claim-table fields. Never copy claim entities into source evidence."""
    blocks = row.get("claim", [])
    if isinstance(blocks, dict):
        blocks = [blocks]
    pairs = {}
    for block in blocks:
        if block.get("type") == "table":
            for key, value in block["content"]:
                pairs[key.casefold().replace(" ", "")] = str(value)
    molecular = pairs.get("molecularprofile", "")
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]*)\s+([^;]+)", molecular)
    return Entities(gene=match[1] if match else "", variant=match[2] if match else "",
                    disease=pairs.get("diseases", ""), drug=pairs.get("therapies", ""))


def dataset_audit(cases: list[CaseInput], gold: list[GoldRecord]) -> dict:
    validate_alignment(cases, gold)
    if len(cases) != len(gold) or len({c.id for c in cases}) != len(cases) or {c.id for c in cases} != {g.case_id for g in gold}:
        raise ValueError("case and label sets must align uniquely")
    tasks = Counter(c.task for c in cases)
    labels = Counter(g.label for g in gold)
    splits = Counter(g.split for g in gold)
    group_counts = Counter(g.group_id for g in gold)
    kinds = Counter(d.kind for c in cases for d in c.documents)
    licenses = Counter(d.license or "UNSPECIFIED" for c in cases for d in c.documents if d.kind == "literature")
    lengths = sorted(sum(len(d.text.encode()) for d in c.documents) for c in cases)
    warnings = []
    if splits["unassigned"]:
        warnings.append("Unassigned cases must receive a declared group split before a study.")
    if licenses["UNSPECIFIED"]:
        warnings.append("Source reuse licenses require review before redistribution.")
    if lengths and lengths[-1] > 100_000:
        warnings.append("Large cases may exceed token budgets; inspect dry-run and smoke traces.")
    return {"role_coverage": coverage_report(cases), "cases": len(cases), "groups": len(group_counts), "tasks": dict(tasks), "labels": dict(labels),
            "splits": dict(splits), "document_kinds": dict(kinds), "licenses": dict(licenses),
            "source_bytes_median": lengths[len(lengths)//2] if lengths else 0,
            "source_bytes_max": max(lengths, default=0), "warnings": warnings,
            "label_location": "_gold/labels.jsonl only; not part of CaseInput",
            "runtime_input_schema": "oncofusion.schemas.CaseInput"}


def prepare_civic(source: Path, output: Path, refutes_label: str = "REFUTES", *,
                  verification_scheme: VerificationScheme = "revisions") -> dict:
    rows = read_jsonl(source)
    cases, gold = import_civicfact(rows, refutes_label, verification_scheme=verification_scheme)
    for case, row in zip(cases, rows):
        case.entities = claim_entities(row)
    audit = dataset_audit(cases, gold)
    manifest = write_dataset(cases, gold, output, str(source))
    audit["manifest"] = manifest
    audit["missing_title_records"] = sum(not row.get("document.title") for row in rows)
    audit["missing_license_records"] = sum(not row.get("document.license") for row in rows)
    audit["unknown_metadata_policy"] = "blank metadata remains unknown; no license grant inferred"
    audit["verification_scheme"] = verification_scheme
    audit["label_policy"] = "native upstream labels retained; no REVISIONS to REFUTES mapping"
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    return audit


def prepare_mtb(source: Path, root: Path, output: Path, path_map: dict[str, str] | None = None) -> dict:
    records = json.loads(source.read_text(encoding="utf-8"))
    upstream = [path for entries in records.values() for event in entries for path in event.get("file_paths", [])]
    if path_map is None:
        available = [str(path.relative_to(root).as_posix()) for path in root.rglob("*")
                     if path.is_file() and path.suffix.lower() in (".txt", ".json", ".csv", ".tsv")
                     and not any(x in path.parts for x in ("_gold", "agent_logs_msk", "agent_logs_hancock"))
                     and "question" not in path.name.lower() and "answer" not in path.name.lower()]
        path_map = build_path_map(upstream, available)
    cases, gold = import_mtbbench(records, root, path_map)
    split = group_split([g.group_id for g in gold])
    for row in gold:
        row.split = split[row.group_id]
    audit = dataset_audit(cases, gold)
    manifest = write_dataset(cases, gold, output, str(source))
    empty_files = sorted({name for name in path_map.values() if not (root / name).read_text(encoding="utf-8").strip()})
    audit.update({"manifest": manifest, "split_seed": 0, "dev_fraction": .2,
                  "empty_source_files": empty_files, "empty_source_policy": "omit empty files; infer no biological absence",
                  "protocol": "stage-visible text adapter; compare within this protocol, not as identical to official tool runs"})
    (output / "path_map.json").write_text(json.dumps(path_map, indent=2))
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    return audit


def acquire_mtb(client: httpx.Client, root: Path) -> dict:
    response = client.get(f"https://huggingface.co/api/datasets/{HF_REPO}/revision/main")
    response.raise_for_status()
    metadata = response.json()
    revision = metadata["sha"]
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise ValueError("invalid Hugging Face revision")
    names = [s["rfilename"] for s in metadata["siblings"]]
    questions = [name for name in names if PurePosixPath(name).name == "questions_msk_bench.json"]
    if len(questions) != 1:
        raise ValueError("expected one questions_msk_bench.json; inspect upstream schema before proceeding")
    source = root / questions[0]
    records = [download(client, f"https://huggingface.co/datasets/{HF_REPO}/resolve/{revision}/{questions[0]}", source)]
    data = json.loads(source.read_text())
    upstream = [path for entries in data.values() for event in entries for path in event.get("file_paths", [])]
    mapping = build_path_map(upstream, names)
    for name in sorted(set(mapping.values())):
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or path.suffix.lower() not in (".txt", ".csv", ".tsv", ".json"):
            raise ValueError("unsupported or unsafe benchmark source path")
        records.append(download(client, f"https://huggingface.co/datasets/{HF_REPO}/resolve/{revision}/{name}", path))
    inventory = {"repository": HF_REPO, "revision": revision, "downloads": records,
                 "questions": questions[0], "path_map": mapping}
    (root / "acquisition.json").write_text(json.dumps(inventory, indent=2))
    return inventory
