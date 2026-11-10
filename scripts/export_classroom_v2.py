"""Export all six fixed executions and three historical records, without source text."""
import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from oncofusion.classroom import Classroom, digest
from oncofusion.store import Store, TERMINAL


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    environment = json.loads((args.root / "environment.json").read_text())
    store = Store(args.root / "runs.sqlite3")
    classroom = Classroom(store, SimpleNamespace(model=environment["provider"]["model"], simulated=False), args.root)
    protocol = classroom.protocol()
    public, rows, identities = [], [], []
    args.out.mkdir(parents=True, exist_ok=True)
    for case in protocol["cases"]:
        alias = case["alias"]
        for source, system, rid in [("historical", "OncoFusion", "history-" + alias)] + [
                ("new", system, classroom.new_id(alias, system)) for system in ["B0", "OncoFusion"]]:
            if rid is None:
                raise RuntimeError(f"fixed slot was not submitted: {alias}/{system}")
            projected = classroom.record(rid, private=False)
            if projected["status"] not in TERMINAL:
                raise RuntimeError(f"fixed execution is still running: {rid}")
            if source == "new":
                run = store.run(rid)
                raw = run["result"] or {"error": run["error"], "trace": store.events(rid, limit=10000)}
                raw_path = args.root / "new" / (alias + "__" + system + ".json")
                raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False))
                (args.root / "new" / (alias + "__" + system + ".metadata.json")).write_text(
                    json.dumps({**{k: v for k, v in run.items() if k != "result"},
                                "code_commit": protocol["code_commit"],
                                "input_fingerprint": case["input_fingerprint"],
                                "evidence_fingerprint": case["evidence_fingerprint"]}, indent=2, ensure_ascii=False))
            else:
                raw_path = args.root / "history" / (alias + ".json")
            usage = projected["usage"] or {}
            row = {"source": source, "case_alias": alias, "system": system, "run_id": rid,
                   "status": projected["status"], "prediction": (projected["decision"] or {}).get("answer"),
                   "reference_label": projected["gold"], "simulated": projected["simulated"],
                   "calls": usage.get("calls", 0), "input_tokens": usage.get("input_tokens", 0),
                   "output_tokens": usage.get("output_tokens", 0), "seconds": projected["seconds"],
                   "arbitration_triggered": (projected["vote"] or {}).get("arbitration", {}).get("triggered"),
                   "initial_label": (projected["vote"] or {}).get("arbitration", {}).get("initial_label")
                       if (projected["vote"] or {}).get("valid_votes", 0) else None,
                   "final_label": (projected["decision"] or {}).get("answer"),
                   "raw_aggregate_label": (projected["vote"] or {}).get("label"),
                   "input_fingerprint": case["input_fingerprint"], "evidence_fingerprint": case["evidence_fingerprint"],
                   "result_sha256": sha(raw_path), "code_commit": projected["code_commit"],
                   "created_at": projected["created_at"], "server_trace_path": str(raw_path)}
            rows.append(row)
            public.append(projected)
            identities.append({k: row[k] for k in ["source", "case_alias", "system", "run_id", "code_commit",
                "input_fingerprint", "evidence_fingerprint", "result_sha256", "simulated", "server_trace_path"]})
    with (args.out / "runs_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "cases_public.json").write_text(json.dumps({
        "schema_version": "classroom-public-v2", "model_display": environment["model_display"],
        "redaction": "Original clinical questions and source quotes omitted. Chinese descriptions are reviewed paraphrases, not original quotations.",
        "records": public}, indent=2, ensure_ascii=False) + "\n")
    (args.out / "presentation_annotations.json").write_text(json.dumps(classroom.annotations(), indent=2, ensure_ascii=False) + "\n")
    generated = datetime.now(timezone.utc).isoformat()
    manifest = {
        "generated_at": generated, "branch": "codex/classroom-web-v2",
        "frozen_execution_commit": protocol["code_commit"],
        "delivery_commit_parent": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "frozen_implementation_digest": protocol["implementation_digest"],
        "source_code_snapshot": protocol["source_code_commit"],
        "historical_implementation": {"commit": protocol["history"]["case-01"]["commit"],
            "implementation_digest": protocol["history"]["case-01"]["implementation_digest"],
            "dirty_worktree": True, "rendered_prompts_not_saved": True},
        "model_display": environment["model_display"], "model_api_id": environment["provider"]["model"],
        "provider_settings": environment["provider"], "configs": protocol["configs"],
        "protocol_sha256": sha(args.root / "protocol.json"),
        "new_executions": 6, "historical_replays": 3, "max_model_calls": 54,
        "global_api_concurrency_limit": 20, "new_results_never_replace_mtb43": True,
        "dataset": {"name": "MTBBench", "source": "EeshaanJain/MTBBench",
                    "revision": "5054ec8ebeb3998ec50fb63860dd4195f6c2a565"},
        "publication_review": {
            "code_license_reference": "https://github.com/bunnelab/mtbbench/blob/main/LICENSE",
            "data_source_reference": "https://github.com/bunnelab/mtbbench#datasets",
            "source_license_fields": "empty in prepared data; patient-text redistribution not established",
            "raw_patient_text": "omitted", "credentials": "server environment only",
            "public_screenshots": "browser screenshots of public view only",
            "omissions_are_marked": True},
        "records": identities,
        "files": [{"path": str(p.relative_to(args.out)), "bytes": p.stat().st_size,
                   "sha256": sha(p), "source": "real browser" if p.suffix == ".png" else "derived from stored real records"}
                  for p in sorted(args.out.rglob("*")) if p.is_file()
                  and p.name not in {"manifest.json", "SHA256SUMS"}],
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    all_files = [p for p in sorted(args.out.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"]
    (args.out / "SHA256SUMS").write_text("\n".join(sha(p) + "  " + str(p.relative_to(args.out)) for p in all_files) + "\n")
    print(json.dumps({"records": len(rows), "new": sum(r["source"] == "new" for r in rows),
                      "output": str(args.out), "summary": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
