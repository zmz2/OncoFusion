from __future__ import annotations
import argparse, csv, json
from collections import Counter
from pathlib import Path

def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]

def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def normalize_record(rec):
    vote = rec.get('vote_result') or {}
    status = rec.get('status')
    if status not in {'full', 'degraded', 'failed'}:
        status = vote.get('completion_status') or 'failed'
    label = rec.get('prediction')
    if label is None:
        label = vote.get('label')
    if status == 'failed' or label in (None, ''):
        label = None
    usage = rec.get('usage') or {}
    calls = rec.get('actual_calls')
    if calls is None:
        calls = usage.get('calls', 0)
    in_tok = rec.get('input_tokens')
    if in_tok is None:
        in_tok = usage.get('input_tokens', 0)
    out_tok = rec.get('output_tokens')
    if out_tok is None:
        out_tok = usage.get('output_tokens', 0)
    seconds = rec.get('seconds')
    if seconds is None:
        seconds = rec.get('duration_seconds', 0)
    arb = vote.get('arbitration') or {}
    return {
        'status': status, 'prediction': label,
        'calls': int(calls or 0), 'input_tokens': int(in_tok or 0),
        'output_tokens': int(out_tok or 0), 'seconds': float(seconds or 0),
        'arbitration': arb,
    }

def compute_metrics(case_ids, gold, records, labels):
    matrix = {g: {p: 0 for p in [*labels, 'NO_VALID_ANSWER']} for g in labels}
    correct = valid = full = degraded = failed = 0
    for cid in case_ids:
        row = normalize_record(records.get(cid, {}))
        pred = row['prediction']
        y = gold[cid]
        if row['status'] == 'full': full += 1
        elif row['status'] == 'degraded': degraded += 1
        else: failed += 1
        if pred not in labels:
            matrix[y]['NO_VALID_ANSWER'] += 1
            continue
        valid += 1
        matrix[y][pred] += 1
        correct += int(pred == y)
    per_class = {}
    f1s = []
    for lab in labels:
        tp = matrix[lab][lab]
        fp = sum(matrix[g][lab] for g in labels if g != lab)
        fn = sum(matrix[lab][p] for p in matrix[lab] if p != lab)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[lab] = {'precision': precision, 'recall': recall, 'f1': f1, 'support': sum(matrix[lab].values())}
        f1s.append(f1)
    n = len(case_ids)
    return {
        'n': n, 'correct': correct, 'accuracy': correct / n if n else None,
        'macro_f1': sum(f1s) / len(f1s) if f1s else None,
        'completion_rate': valid / n if n else None,
        'full': full, 'degraded': degraded, 'failed': failed,
        'per_class': per_class, 'confusion': matrix,
    }

def usage_totals(case_ids, records):
    rows = [normalize_record(records.get(cid, {})) for cid in case_ids]
    return {
        'actual_calls': sum(x['calls'] for x in rows),
        'input_tokens': sum(x['input_tokens'] for x in rows),
        'output_tokens': sum(x['output_tokens'] for x in rows),
        'elapsed_case_seconds': round(sum(x['seconds'] for x in rows), 3),
    }

def v3_arb_stats(case_ids, v3_records, pk_records, gold):
    triggered = completed = failed = changed = corrected = broke = stable_correct = stable_wrong = extra_calls = 0
    for cid in case_ids:
        v3 = normalize_record(v3_records[cid])
        pk = normalize_record(pk_records[cid])
        arb = v3['arbitration']
        if not arb.get('triggered'):
            continue
        triggered += 1
        if arb.get('status') == 'completed':
            completed += 1
        else:
            failed += 1
        initial = arb.get('initial_label')
        final = arb.get('final_label')
        if final is None:
            final = v3['prediction']
        changed_here = initial != final
        changed += int(changed_here)
        if initial == gold[cid] and final == gold[cid]: stable_correct += 1
        elif initial != gold[cid] and final != gold[cid]: stable_wrong += 1
        elif initial != gold[cid] and final == gold[cid]: corrected += 1
        elif initial == gold[cid] and final != gold[cid]: broke += 1
        extra_calls += max(0, v3['calls'] - pk['calls'])
    return {'triggered':triggered,'arbitrated_completed':completed,'arbitrated_failed':failed,
            'changed_labels':changed,'corrected':corrected,'broke':broke,
            'unchanged_correct':stable_correct,'unchanged_wrong':stable_wrong,'extra_calls':extra_calls}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-root', required=True)
    ap.add_argument('--data', required=True)
    ap.add_argument('--artifact-root', required=True)
    args = ap.parse_args()
    root = Path(args.run_root)
    data = Path(args.data)
    artifact = Path(args.artifact_root)
    tables = artifact / 'tables'
    tables.mkdir(parents=True, exist_ok=True)
    labels = {r['case_id']:r['label'] for r in read_jsonl(data / '_gold/labels.jsonl')}
    all_labels = sorted(set(labels.values()))
    selection = json.loads((root / 'development_selection_private.json').read_text(encoding='utf-8'))
    selected_rows = selection['e04_mtb_cases']
    selected = [r['case_id'] for r in selected_rows]
    assert len(selected) == 20 and len(set(selected)) == 20
    assert all(cid in labels for cid in selected)
    result_root = root / 'E04_mtb_robustness_fix2'
    e04_rows = read_jsonl(result_root / 'variant_results_private.jsonl')
    assert len(e04_rows) == 160, len(e04_rows)
    e04 = {(r['condition'],r['case_id'],r['arm']):r for r in e04_rows}
    conditions = ['R0','R1','R2','R3','R4']
    methods = ['B0','P-K no arbitration','V3']
    records = {}
    r0 = root / 'E05a_mtb30_base'
    arm_paths = {
        'B0': r0 / 'b0_common_single/0',
        'P-K no arbitration': r0 / 'p_k_specialists/0',
        'V3': r0 / 'v3/p_k_specialists/0',
    }
    for method, folder in arm_paths.items():
        records[('R0', method)] = {}
        for cid in selected:
            path = folder / (cid + '.json')
            if path.exists():
                records[('R0', method)][cid] = json.loads(path.read_text(encoding='utf-8'))
        assert len(records[('R0', method)]) == 20, (method, len(records[('R0', method)]))
    for condition in ['R1','R2','R3','R4']:
        for method, arm in [('B0','b0_common_single'),('P-K no arbitration','p_k_specialists')]:
            records[(condition, method)] = {cid:e04[(condition,cid,arm)] for cid in selected}
    v3_records = {condition:{} for condition in ['R1','R2','R3','R4']}
    chunk_summaries = []
    for chunk in sorted(root.glob('E04_mtb_robustness_v3chunk*')):
        if chunk.name.endswith('_source') or not chunk.is_dir():
            continue
        summary_path = chunk / 'arbitration.json'
        if summary_path.exists():
            chunk_summaries.append(json.loads(summary_path.read_text(encoding='utf-8')))
        for condition in ['R1','R2','R3','R4']:
            folder = chunk / condition / 'p_k_specialists/0'
            if not folder.exists():
                continue
            for path in folder.glob('*.json'):
                if path.name == 'summary.json' or path.name.endswith('.failed.json'):
                    continue
                rec = json.loads(path.read_text(encoding='utf-8'))
                v3_records[condition][rec['case_id']] = rec
    for condition in ['R1','R2','R3','R4']:
        assert len(v3_records[condition]) == 20, (condition, len(v3_records[condition]))
        records[(condition,'V3')] = v3_records[condition]
    summary_rows=[]; per_rows=[]
    metric_cache={}
    for condition in conditions:
        for method in methods:
            recs=records[(condition,method)]
            mm=compute_metrics(selected,labels,recs,all_labels)
            costs=usage_totals(selected,recs)
            metric_cache[(condition,method)]=mm
            arb={'triggered':0,'arbitrated_completed':0,'arbitrated_failed':0,'changed_labels':0,'corrected':0,'broke':0,'unchanged_correct':0,'unchanged_wrong':0,'extra_calls':0}
            if method=='V3':
                pk=records[(condition,'P-K no arbitration')]
                arb=v3_arb_stats(selected,recs,pk,labels)
            summary_rows.append({'condition':condition,'method':method,**{k:v for k,v in mm.items() if k not in {'per_class','confusion'}},**costs,**arb})
            for lab in all_labels:
                per_rows.append({'condition':condition,'method':method,'label':lab,**mm['per_class'][lab]})
    write_csv(tables/'robustness_summary.csv',summary_rows)
    write_csv(tables/'robustness_per_class.csv',per_rows)
    paired=[]
    for condition in conditions:
        for candidate in ['P-K no arbitration','V3']:
            a=records[('R0','B0')]; b=records[(condition,candidate)]
            both=[]; fixed=broke=recovered=lost=0
            for cid in selected:
                pa=normalize_record(a[cid])['prediction']; pb=normalize_record(b[cid])['prediction']; y=labels[cid]
                if pa is not None and pb is not None:
                    both.append(cid)
                    if pa!=y and pb==y: fixed+=1
                    if pa==y and pb!=y: broke+=1
                if pa is None and pb==y: recovered+=1
                if pa==y and pb is None: lost+=1
            paired.append({'baseline':'R0 B0','condition':condition,'candidate':candidate,'n':20,
                           'candidate_accuracy':metric_cache[(condition,candidate)]['accuracy'],
                           'baseline_accuracy':metric_cache[('R0','B0')]['accuracy'],
                           'both_valid_n':len(both),'fixed':fixed,'broke':broke,
                           'baseline_failed_candidate_correct':recovered,'baseline_correct_candidate_failed':lost})
        pk=records[(condition,'P-K no arbitration')]; v3=records[(condition,'V3')]
        both=[]; fixed=broke=0
        for cid in selected:
            p=normalize_record(pk[cid])['prediction']; v=normalize_record(v3[cid])['prediction']; y=labels[cid]
            if p is not None and v is not None:
                both.append(cid)
                fixed += int(p!=y and v==y)
                broke += int(p==y and v!=y)
        paired.append({'baseline':condition+' P-K no arbitration','condition':condition,'candidate':'V3','n':20,
                       'candidate_accuracy':metric_cache[(condition,'V3')]['accuracy'],
                       'baseline_accuracy':metric_cache[(condition,'P-K no arbitration')]['accuracy'],
                       'both_valid_n':len(both),'fixed':fixed,'broke':broke,
                       'baseline_failed_candidate_correct':sum(normalize_record(pk[c])['prediction'] is None and normalize_record(v3[c])['prediction']==labels[c] for c in selected),
                       'baseline_correct_candidate_failed':sum(normalize_record(pk[c])['prediction']==labels[c] and normalize_record(v3[c])['prediction'] is None for c in selected)})
    write_csv(tables/'robustness_paired.csv',paired)
    descriptions={
      'R0':'Unmodified evidence; results reused from the same 20 cases in the fresh E05a MTB development run.',
      'R1':'Remove genomic/molecular evidence documents and repeated molecular content, including corresponding case/document molecular fields.',
      'R2':'Remove pathology evidence documents and repeated pathology content, including corresponding case/document pathology fields.',
      'R3':'Deterministically remove approximately 25% of non-empty clinical event lines while keeping at least one event line; remove overlapping duplicate summary lines.',
      'R4':'Deterministically mask approximately 25% of the fragmented evidence items, while keeping at least one item.'}
    manifest_conditions=[]
    for condition in ['R1','R2','R3','R4']:
        per_case={}
        for r in e04_rows:
            if r['condition']!=condition or r['arm']!='b0_common_single': continue
            per_case[r['case_id']]=r
        assert len(per_case)==20,(condition,len(per_case))
        manifest_conditions.append({'condition':condition,'description':descriptions[condition],'planned_cases':20,
             'unique_cases_with_variant_metadata':len(per_case),
             'removed_document_count':sum(len(r.get('removed_document_ids') or []) for r in per_case.values()),
             'removed_line_count':sum(int(r.get('removed_line_count') or 0) for r in per_case.values()),
             'masked_fragment_count':sum(len(r.get('masked_ids') or []) for r in per_case.values()),
             'mean_retained_evidence_fragments':sum(len(r.get('evidence_ids') or []) for r in per_case.values())/20,
             'mean_retained_evidence_characters':sum(int(r.get('evidence_chars') or 0) for r in per_case.values())/20})
    arb_totals={'total_derived_cases':0,'triggered':0,'arbitrated_completed':0,'arbitrated_failed':0,'changed':0,'extra_calls':0,'peak_in_flight_max_within_chunk':0}
    for s in chunk_summaries:
        for key in ['total_cases','triggered','arbitrated_completed','arbitrated_failed','changed','extra_calls']:
            target={'total_cases':'total_derived_cases','changed':'changed'} .get(key,key)
            arb_totals[target]=arb_totals.get(target,0)+int(s.get(key,0) or 0)
        arb_totals['peak_in_flight_max_within_chunk']=max(arb_totals['peak_in_flight_max_within_chunk'],int((s.get('concurrency') or {}).get('peak_in_flight',0)))
    manifest={'benchmark':'MTBBench','experiment':'E04 evidence robustness','baseline':'R0 unmodified evidence reused from E05a, same selected cases',
      'sample_size_per_condition':20,'conditions':[{'condition':'R0','description':descriptions['R0']},*manifest_conditions],
      'arms':['B0 common single agent','P-K specialist pool (initial vote, no arbitration)','V3 derived from the exact same P-K ballots'],
      'derivation':{'v3_cases':arb_totals,'no_base_ballots_regenerated':True},
      'aggregate_call_or_token_cap':None,'global_concurrency_cap':20}
    (artifact/'missing_evidence_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    metrics={'conditions':{c:{m:metric_cache[(c,m)] for m in methods} for c in conditions},'v3_derived':arb_totals,
             'selected_case_count':20,'labels':all_labels}
    (tables/'robustness_metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'rows':len(summary_rows),'per_class_rows':len(per_rows),'paired_rows':len(paired),'v3_cases':arb_totals},ensure_ascii=False))
if __name__=='__main__': main()
