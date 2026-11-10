"""Aggregate real-API study outputs: failure rate, tokens, p95 latency, cost, citations."""
import argparse
import json
import statistics
from pathlib import Path

from oncofusion.datasets import read_jsonl
from oncofusion.schemas import RunResult


def pct(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1)))]


def treatment_rows(study_dir: Path, treatment: str, seed: str) -> list[dict]:
    directory = study_dir / treatment / seed
    rows = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        if path.name == "summary.json":
            continue
        if path.name.endswith(".failed.json"):
            rows.append(json.loads(path.read_text()) | {"_failed_marker": True, "case_id": path.stem[:-len(".failed")]})
            continue
        rows.append(json.loads(path.read_text()))
    return rows



def per_role_table(study_dir: Path) -> dict:
    """Per-role latency, tokens, HTTP retries and evidence-fragment counts, failures included."""
    buckets = {}
    for path in study_dir.glob("*/*/*.json"):
        if path.name == "summary.json":
            continue
        data = json.loads(path.read_text())
        trace = data.get("trace") or []
        failed = path.name.endswith(".failed.json")
        last_role = None
        for event in trace:
            if event["kind"] == "agent_started":
                last_role = event.get("role")
            if event["kind"] != "model_usage":
                continue
            role, d = event.get("role"), event["details"]
            row = buckets.setdefault(role, {"calls": 0, "seconds": [], "input_tokens": 0,
                                            "output_tokens": 0, "retried_calls": 0,
                                            "estimated_calls": 0, "fragments": [], "failed_runs": 0})
            row["calls"] += 1
            if isinstance(d.get("seconds"), (int, float)):
                row["seconds"].append(d["seconds"])
            row["input_tokens"] += d.get("input_tokens") or 0
            row["output_tokens"] += d.get("output_tokens") or 0
            row["retried_calls"] += (d.get("attempts") or 1) > 1
            row["estimated_calls"] += bool(d.get("estimated"))
            if isinstance(d.get("evidence_fragments"), int):
                row["fragments"].append(d["evidence_fragments"])
            if failed and role == last_role:
                row["failed_runs"] += 1
    table = {}
    for role, row in buckets.items():
        seconds = sorted(row["seconds"])
        table[role] = {"calls": row["calls"],
                       "seconds_mean": round(statistics.mean(seconds), 2) if seconds else None,
                       "seconds_p50": round(statistics.median(seconds), 2) if seconds else None,
                       "seconds_p95": round(pct(seconds, 0.95), 2) if seconds else None,
                       "seconds_max": round(max(seconds), 2) if seconds else None,
                       "input_tokens_mean": round(row["input_tokens"] / row["calls"], 1),
                       "output_tokens_mean": round(row["output_tokens"] / row["calls"], 1),
                       "calls_with_http_retry": row["retried_calls"],
                       "calls_with_estimated_usage": row["estimated_calls"],
                       "evidence_fragments_mean": round(statistics.mean(row["fragments"]), 1) if row["fragments"] else None,
                       "runs_failing_at_role": row["failed_runs"]}
    return table

def summarise(study_dir: Path, inputs: Path | None, citation_limit: int) -> dict:
    study = json.loads((study_dir / "study.json").read_text())
    identity = json.loads((study_dir / "identity.json").read_text())
    table = {row["treatment"]: row for row in study["table"]}
    per_treatment = {}
    for treatment in table:
        rows, failures = [], []
        for seed_dir in sorted((study_dir / treatment).iterdir()) if (study_dir / treatment).is_dir() else []:
            rows.extend(treatment_rows(study_dir, treatment, seed_dir.name))
        statuses = {}
        durations, calls, tokens_in, tokens_out, costs, incomplete = [], [], [], [], [], 0
        errors = {}
        for row in rows:
            status = row.get("status", "failed")
            statuses[status] = statuses.get(status, 0) + 1
            if row.get("_failed_marker") or status == "failed":
                error = str(row.get("error", ""))[:160]
                errors[error] = errors.get(error, 0) + 1
            usage = row.get("usage") or row.get("observed_usage") or {}
            if usage:
                calls.append(usage.get("calls", 0))
                tokens_in.append(usage.get("input_tokens", 0))
                tokens_out.append(usage.get("output_tokens", 0))
            if "duration_seconds" in row:
                durations.append(row["duration_seconds"])
            costs.append(row.get("known_cost_usd", 0.0))
            incomplete += bool(row.get("usage_incomplete"))
        per_treatment[treatment] = {
            "executions": len(rows),
            "statuses": statuses,
            "failed_or_incomplete": table[treatment]["failed_or_incomplete"],
            "accuracy_mean": table[treatment]["accuracy_mean"],
            "error_kinds": errors,
            "calls_mean": round(statistics.mean(calls), 2) if calls else None,
            "input_tokens_mean": round(statistics.mean(tokens_in), 1) if tokens_in else None,
            "output_tokens_mean": round(statistics.mean(tokens_out), 1) if tokens_out else None,
            "total_input_tokens": sum(tokens_in),
            "total_output_tokens": sum(tokens_out),
            "run_seconds": {"mean": round(statistics.mean(durations), 1) if durations else None,
                            "p50": round(pct(durations, .5), 1) if durations else None,
                            "p95": round(pct(durations, .95), 1) if durations else None,
                            "max": round(max(durations), 1) if durations else None},
            "known_cost_usd": round(sum(costs), 6),
            "cost_complete": table[treatment]["cost_complete"],
            "usage_incomplete_runs": table[treatment]["usage_incomplete_runs"],
        }
    citations = []
    if inputs and citation_limit:
        visible = {row["id"]: row for row in read_jsonl(inputs)}
        for treatment in sorted(per_treatment):
            for seed_dir in sorted((study_dir / treatment).iterdir()) if (study_dir / treatment).is_dir() else []:
                for path in sorted(seed_dir.glob("*.json")):
                    if path.name == "summary.json" or path.name.endswith(".failed.json"):
                        continue
                    result = RunResult.model_validate_json(path.read_text())
                    for citation in (result.decision.citations if result.decision else [])[:3]:
                        document = visible.get(result.case_id, {}).get("documents", [])
                        source_text = next((d["text"] for d in document if d["id"] == citation.document_id), "")
                        citations.append({"treatment": treatment, "case_id": result.case_id,
                                          "status": result.status, "answer": result.decision.answer if result.decision else None,
                                          "document_id": citation.document_id, "quote": citation.quote,
                                          "quote_in_source": citation.quote in source_text,
                                          "offset_ok": (citation.start is None or citation.end is None or citation.start <= citation.end <= len(source_text)),
                                          "source_excerpt": source_text[:160]})
                    if len(citations) >= citation_limit:
                        break
                if len(citations) >= citation_limit:
                    break
            if len(citations) >= citation_limit:
                break
    return {"simulated": identity.get("simulated"), "identity": identity["identity"][:16],
            "provider": study["plan"].get("name"), "treatments": per_treatment,
            "per_role": per_role_table(study_dir),
            "citation_samples": citations[:citation_limit],
            "citation_quote_check": {"checked": len(citations),
                                     "quote_found": sum(c["quote_in_source"] for c in citations),
                                     "offset_ok": sum(c["offset_ok"] for c in citations)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--citations", type=int, default=12)
    args = parser.parse_args()
    report = summarise(args.study, args.inputs, args.citations)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for treatment, row in report["treatments"].items():
        print("%-18s exec=%-3d statuses=%s acc=%s p95=%ss calls=%s in=%s out=%s cost=%s" % (
            treatment, row["executions"], row["statuses"], row["accuracy_mean"],
            row["run_seconds"]["p95"], row["calls_mean"], row["input_tokens_mean"],
            row["output_tokens_mean"], row["known_cost_usd"]))
    roles = report.get("per_role", {})
    print("per-role latency (s):", ", ".join(
        "%s p50=%s p95=%s in=%s out=%s retry=%s" % (
            role, row["seconds_p50"], row["seconds_p95"], row["input_tokens_mean"],
            row["output_tokens_mean"], row["calls_with_http_retry"])
        for role, row in roles.items()))
    print("quote_check:", report["citation_quote_check"], "simulated:", report["simulated"])
    print("written:", args.out)


main()
