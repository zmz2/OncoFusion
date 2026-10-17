"""Opt-in public-data integration. Downloads frozen public sources; model remains simulated."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
from oncofusion.datasets import iter_jsonl
from oncofusion.engine import Engine
from oncofusion.evaluation import evaluate, load_evaluation
from oncofusion.experiments import select_cases, standard_plan
from oncofusion.preparation import CIVIC_URL, CIVIC_BLOB, CIVIC_REVISION, acquire_mtb, download, prepare_civic, prepare_mtb
from oncofusion.providers import MockProvider
from oncofusion.retrieval_benchmark import evaluate_retrieval, prepare_retrieval
from oncofusion.config import presets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('data/public_checks'))
    parser.add_argument('--out', type=Path, default=Path('results/public_data_checks.json'))
    parser.add_argument('--accept-source-terms', action='store_true')
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
            results.append({'dataset':dataset,'status':'passed', 'audit':audit, 'test':test, 'duration_seconds':round(time.monotonic()-started,3)})
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
