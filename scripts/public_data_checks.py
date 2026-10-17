"""Opt-in public-data integration. Downloads frozen public sources; model remains simulated."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from collections import Counter

import httpx
from oncofusion.datasets import iter_jsonl
from oncofusion.engine import Engine
from oncofusion.evaluation import evaluate, load_evaluation
from oncofusion.experiments import select_cases, standard_plan
from oncofusion.preparation import CIVIC_URL, CIVIC_BLOB, CIVIC_REVISION, acquire_mtb, download, prepare_civic, prepare_mtb
from oncofusion.providers import MockProvider
from oncofusion.retrieval_benchmark import evaluate_retrieval, prepare_retrieval
from oncofusion.config import presets, research_v1_config
from oncofusion.specialists import coverage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('data/public_checks'))
    parser.add_argument('--out', type=Path, default=Path('results/public_data_checks.json'))
    parser.add_argument('--accept-source-terms', action='store_true')
    parser.add_argument('--clinical-graph', action='store_true', help='exercise installed graph and clinical packages')
    parser.add_argument('--datasets', nargs='+', choices=['civicfact','mtbbench','retrieval'], default=['civicfact','mtbbench','retrieval'])
    args = parser.parse_args()
    if not args.accept_source_terms:
        parser.error('review source terms and pass --accept-source-terms')
    results = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for dataset in args.datasets:
        started = time.monotonic()
        try:
            folder = args.root / dataset
            raw, prepared = folder / 'raw', folder / 'prepared'
            with httpx.Client(timeout=120) as client:
                if dataset == 'civicfact':
                    source = raw / 'data.jsonl.gz'
                    download(client, CIVIC_URL, source, git_blob=CIVIC_BLOB)
                    audit = prepare_civic(source, prepared)
                elif dataset == 'mtbbench':
                    source = acquire_mtb(client, raw)
                    audit = prepare_mtb(raw / source['questions'], raw, prepared, source['path_map'])
                else:
                    prefix = f'https://raw.githubusercontent.com/creisle/civicfact/{CIVIC_REVISION}/data_builder/builds/civicfact-2026.06.09/'
                    queries, chunks = raw / 'retreival.jsonl.gz', raw / 'document_chunks.jsonl.gz'
                    download(client, prefix + queries.name, queries, git_blob='4783a5ad0b63b9387b191f814a1e562337b39cb9')
                    download(client, prefix + chunks.name, chunks, git_blob='4a1b5acf727d9fb1b2ff000ccde9ea9b6702d60b')
                    audit = prepare_retrieval(iter_jsonl(queries), iter_jsonl(chunks), prepared, allow_exclusions=True)
            cases, gold = load_evaluation(prepared / 'inputs.jsonl', prepared / '_gold/labels.jsonl')
            plan = standard_plan('mcq' if dataset == 'mtbbench' else 'verification', group_limit=2, smoke=True)
            selected, targets = select_cases(cases, gold, plan)
            if dataset == 'retrieval':
                report = evaluate_retrieval(selected, targets)
                test = {'sample_count':len(selected), 'retrieval_methods':list(report['metrics']), 'model_calls':0}
            else:
                runs = [evaluate(selected, targets, Engine(MockProvider()), presets()[name]) for name in ['full','single_direct','single_tools','single_iterative','fixed_five']]
                test = {'sample_count':len(selected), 'configurations':len(runs), 'case_executions':len(selected)*len(runs),
                        'completed':sum(r['count']-r['failed_or_incomplete'] for r in runs),
                        'failed_or_incomplete':sum(r['failed_or_incomplete'] for r in runs)}
            entry = {'dataset':dataset,'status':'passed', 'audit':audit, 'test':test}
            if dataset != 'retrieval':
                # Exercise the new role views on genuine contents, independently of
                # optional package tests. Clinical/graph runtimes have their own CI.
                base = research_v1_config(clinical=args.clinical_graph and dataset == "mtbbench").model_copy(
                    update={"workflow_backend": "langgraph" if args.clinical_graph else "native"})
                candidates = [base.model_copy(update={"mode": mode})
                              for mode in ("multi", "single_tools", "single_iterative", "fixed_five")]
                checked = [evaluate(selected, targets, Engine(MockProvider()), cfg) for cfg in candidates]
                scopes = [coverage(c) for c in cases]
                entry["v1_test"] = {"sample_count": len(selected), "configurations": len(checked),
                    "case_executions": len(selected)*len(checked),
                    "failed_or_incomplete": sum(r["failed_or_incomplete"] for r in checked),
                    "workflow_backend": base.workflow_backend, "clinical_context": base.clinical_context,
                    "status_by_configuration": {r["config"]["mode"]: dict(Counter(row["status"] for row in r["rows"])) for r in checked},
                    "failure_details": [{"mode": r["config"]["mode"], "status": row["status"],
                                         "error": row.get("error", ""), "usage": row.get("usage", {})}
                                        for r in checked for row in r["rows"] if row["status"] != "completed"]}
                entry["input_scope"] = {"heterogeneous_cases": sum(c["heterogeneous_input"] for c in scopes),
                    "applicable_cases_by_role": {role: sum(c["roles"][role]["applicable"] for c in scopes)
                                                 for role in scopes[0]["roles"]}}
                if entry["v1_test"]["failed_or_incomplete"]:
                    entry["status"] = "failed"
            entry['duration_seconds'] = round(time.monotonic()-started,3)
            results.append(entry)
        except Exception as exc:
            # Integration boundary: retain failures separately so other public sources are still checked.
            results.append({'dataset':dataset,'status':'failed','error_type':type(exc).__name__,'error':str(exc)[:2000],
                            'duration_seconds':round(time.monotonic()-started,3)})
        summary = {'source_data':'public authentic benchmark data', 'model':'deterministic simulator',
                   'real_provider_calls':0, 'results':results, 'scientific_accuracy_claim':False}
        args.out.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    return 0 if all(r['status']=='passed' and not r.get('test',{}).get('failed_or_incomplete') for r in results) else 2


if __name__ == '__main__':
    raise SystemExit(main())
