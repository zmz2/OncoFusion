"""Command-line entrypoints for local runs, imports and reproducible experiments."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import presets
from .datasets import (GoldRecord, group_split, import_civicfact, import_mtbbench,
                       read_jsonl, write_dataset)
from .engine import Engine
from .evaluation import evaluate, load_evaluation
from .examples import examples
from .providers import MockProvider, provider_from_env
from .schemas import CaseInput


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="oncofusion")
    commands = p.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--db", default="runtime/oncofusion.sqlite3")
    sample = commands.add_parser("examples")
    sample.add_argument("--out", type=Path, required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--example", choices=list(examples()), default="synthetic-support")
    demo.add_argument("--preset", choices=list(presets()), default="full")
    demo.add_argument("--out", type=Path, required=True)
    demo.add_argument("--allow-remote", action="store_true")
    civic = commands.add_parser("import-civic")
    civic.add_argument("--source", type=Path, required=True)
    civic.add_argument("--out", type=Path, required=True)
    civic.add_argument("--refutes-label", default="REFUTES")
    mtb = commands.add_parser("import-mtb")
    mtb.add_argument("--source", type=Path, required=True)
    mtb.add_argument("--root", type=Path, required=True)
    mtb.add_argument("--path-map", type=Path, required=True)
    mtb.add_argument("--out", type=Path, required=True)
    for name in ("evaluate", "matrix"):
        command = commands.add_parser(name)
        command.add_argument("--inputs", type=Path, required=True)
        command.add_argument("--labels", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--task", choices=("verification", "mcq"), default="verification")
        command.add_argument("--split", choices=("all", "train", "dev", "test"), default="all")
        command.add_argument("--allow-remote", action="store_true")
        if name == "evaluate":
            command.add_argument("--preset", choices=list(presets()), default="full")
        else:
            command.add_argument("--presets", nargs="+", choices=["all"] + list(presets()), default=["all"])
            command.add_argument("--repeats", type=int, default=1)
    schema = commands.add_parser("openapi")
    schema.add_argument("--out", type=Path, required=True)
    return p


def save(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.command == "serve":
        import os
        import uvicorn
        from .api import create_app
        if args.host not in ("127.0.0.1", "localhost", "::1") and not os.getenv("ONCOFUSION_API_TOKEN"):
            p.error("set ONCOFUSION_API_TOKEN before binding a non-loopback address")
        uvicorn.run(create_app(db_path=args.db), host=args.host, port=args.port, workers=1)
        return 0
    if args.command == "openapi":
        from .api import create_app
        with TemporaryDirectory() as td:
            save(args.out, create_app(Path(td) / "schema.db", provider=MockProvider()).openapi())
        return 0
    if args.command == "examples":
        cases = list(examples().values())
        labels = ["SUPPORTS", "REFUTES", "NEI", "A"]
        gold = [GoldRecord(case_id=c.id, group_id=c.patient_id, label=label, split="dev") for c, label in zip(cases, labels)]
        print(json.dumps(write_dataset(cases, gold, args.out, "OncoFusion synthetic software fixtures")))
        return 0
    if args.command == "import-civic":
        cases, gold = import_civicfact(read_jsonl(args.source), args.refutes_label)
        print(json.dumps(write_dataset(cases, gold, args.out, str(args.source))))
        return 0
    if args.command == "import-mtb":
        cases, gold = import_mtbbench(json.loads(args.source.read_text(encoding="utf-8")), args.root,
                                     json.loads(args.path_map.read_text(encoding="utf-8")))
        split = group_split([g.group_id for g in gold])
        for g in gold:
            g.split = split[g.group_id]
        print(json.dumps(write_dataset(cases, gold, args.out, str(args.source))))
        return 0
    provider = provider_from_env()
    if not provider.simulated and not args.allow_remote:
        p.error("real API calls require --allow-remote after reviewing data and cost")
    engine = Engine(provider)
    if args.command == "demo":
        result = engine.run(examples()[args.example], presets()[args.preset])
        save(args.out, result.model_dump(mode="json"))
        print(json.dumps({"status": result.status, "simulated": result.simulated, "output": str(args.out)}))
        return 0 if result.status == "completed" else 2
    cases, gold = load_evaluation(args.inputs, args.labels)
    allowed = {g.case_id for g in gold if args.split == "all" or g.split == args.split}
    cases = [c for c in cases if c.task == args.task and c.id in allowed]
    ids = {c.id for c in cases}
    gold = [g for g in gold if g.case_id in ids]
    if args.command == "evaluate":
        report = evaluate(cases, gold, engine, presets()[args.preset], args.out)
        print(json.dumps({"simulated": report["simulated"], "metrics": report["metrics"], "failed_or_incomplete": report["failed_or_incomplete"]}))
        return 0 if report["failed_or_incomplete"] == 0 else 2
    if args.repeats < 1 or args.repeats > 20:
        p.error("repeats must be in [1,20]")
    selected = presets() if "all" in args.presets else {name: presets()[name] for name in args.presets}
    summaries = []
    for name, config in selected.items():
        for repeat in range(args.repeats):
            config = config.model_copy(update={"seed": repeat})
            report = evaluate(cases, gold, engine, config, args.out / name / str(repeat))
            summaries.append({"preset": name, "repeat": repeat, "simulated": report["simulated"],
                              "metrics": report["metrics"], "efficiency": report["efficiency"], "failed_or_incomplete": report["failed_or_incomplete"]})
    save(args.out / "matrix.json", {"results": summaries, "simulated": provider.simulated})
    print(json.dumps({"configurations": len(selected), "runs": len(summaries), "simulated": provider.simulated}))
    return 0 if not any(s["failed_or_incomplete"] for s in summaries) else 2


if __name__ == "__main__":
    sys.exit(main())
