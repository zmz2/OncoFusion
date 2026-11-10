"""Execute a JSON study plan. Run --dry-run first to see the workload."""
import argparse
import json
from pathlib import Path
from oncofusion.engine import Engine
from oncofusion.evaluation import load_evaluation
from oncofusion.experiments import StudyPlan, run_study, select_cases
from oncofusion.providers import provider_from_env
from oncofusion.profiles import coverage_report
from oncofusion.scheduling import ProviderScheduler


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--allow-remote", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--retry-failed", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--workers", type=int, default=1,
                   help="parallel case executions per treatment; results and cost are unchanged")
    p.add_argument("--interleave-treatments", action="store_true",
                   help="run each case through every arm together, up to --workers cases in flight")
    p.add_argument("--order-json", type=Path,
                   help="write an append-only provider call log for execution-order audit")
    p.add_argument("--execution-cap", type=int, default=1000, help="maximum permitted real case executions; raise explicitly after reviewing cost")
    args = p.parse_args()
    if args.execution_cap < 1:
        p.error("execution-cap must be positive")
    plan = StudyPlan.model_validate_json(args.plan.read_text())
    cases, gold = load_evaluation(args.dataset / "inputs.jsonl", args.dataset / "_gold" / "labels.jsonl")
    selected, _ = select_cases(cases, gold, plan)
    executions = len(selected) * len(plan.treatments) * len(plan.seeds)
    print(json.dumps({"role_coverage": coverage_report(selected), "case_count": len(selected), "treatments": len(plan.treatments),
                      "repeats": len(plan.seeds), "case_executions": executions,
                      "max_model_calls": len(selected) * sum(t.config(seed).max_calls for t in plan.treatments for seed in plan.seeds)}))
    if args.dry_run:
        return 0
    provider = provider_from_env()
    if not provider.simulated and not args.allow_remote:
        p.error("real API studies require --allow-remote after reviewing data and estimated workload")
    if not provider.simulated and executions > args.execution_cap:
        p.error("planned real workload exceeds --execution-cap; inspect --dry-run and raise the cap explicitly")
    if args.order_json:
        original_complete = provider.complete
        def logged_complete(system, payload, max_tokens, temperature, seed):
            role = payload.get("role", "")
            with args.order_json.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "role": role,
                    "question": payload.get("question", "")[:120],
                    "time": __import__("time").time(),
                }, ensure_ascii=False) + "\n")
            return original_complete(system, payload, max_tokens, temperature, seed)
        provider.complete = logged_complete
    report = run_study(plan, cases, gold, Engine(provider), args.out, args.resume, args.retry_failed,
                       workers=args.workers, interleave_treatments=args.interleave_treatments)
    # The order-log wrapper is attached after the scheduled provider is built, so inspect
    # both the current object and its wrapped inner provider.
    report["concurrency"] = report.get("concurrency") or {
        "capacity": None, "peak_in_flight": None,
        "note": "no process-wide provider scheduler configured"}
    (args.out / "concurrency.json").write_text(
        json.dumps(report["concurrency"], indent=2), encoding="utf-8")
    (args.out / "study.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"simulated": report["simulated"], "output": str(args.out / "study.json"),
                      "failed_or_incomplete": sum(t["failed_or_incomplete"] for t in report["table"]),
                      "concurrency": report["concurrency"]}))
    return 0 if not any(t["failed_or_incomplete"] for t in report["table"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
