from __future__ import annotations
import csv, html
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'artifacts/vote_extensions_20261125'
FIG=ROOT/'figures'
FIG.mkdir(parents=True,exist_ok=True)
COLORS=['#236da5','#ee9a3c','#4a9f78','#9b7bbe','#d65d5d']
FONT="Arial, 'Noto Sans CJK SC', sans-serif"
def rows(name):
    with (ROOT/'tables'/name).open(encoding='utf-8',newline='') as f: return list(csv.DictReader(f))
def esc(x): return html.escape(str(x),quote=True)
def chart(filename,title,subtitle,cats,series,minv=0,maxv=1,percent=True):
    W,H=1600,900; left,right,top,bottom=130,70,155,185; pw,ph=W-left-right,H-top-bottom
    bits=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
          '<rect width="100%" height="100%" fill="#fbfdff"/>',
          f'<text x="{left}" y="72" font-family="{FONT}" font-size="44" font-weight="700" fill="#183b56">{esc(title)}</text>',
          f'<text x="{left}" y="116" font-family="{FONT}" font-size="23" fill="#62798a">{esc(subtitle)}</text>']
    ticks=5
    for i in range(ticks+1):
        val=minv+(maxv-minv)*i/ticks
        y=top+ph*(ticks-i)/ticks
        stroke='#dce5ec' if abs(val)>1e-9 else '#748b9a'
        bits.append(f'<line x1="{left}" y1="{y:.1f}" x2="{W-right}" y2="{y:.1f}" stroke="{stroke}" stroke-width="2"/>')
        label=f'{val*100:.0f}%' if percent else f'{val:.1f}'
        bits.append(f'<text x="{left-20}" y="{y+7:.1f}" text-anchor="end" font-family="{FONT}" font-size="19" fill="#536c7e">{label}</text>')
    groupw=pw/max(1,len(cats)); nser=max(1,len(series)); barw=min(74,groupw/(nser+1.4))
    for ci,cat in enumerate(cats):
        center=left+groupw*(ci+.5)
        for si,(name,values) in enumerate(series):
            val=values[ci]
            if val is None: continue
            val=max(minv,min(maxv,val)); x=center+(si-(nser-1)/2)*barw*1.2-barw/2
            yv=top+ph*(maxv-val)/(maxv-minv)
            y0=top+ph*(maxv-max(0,minv))/(maxv-minv)
            rect_y=min(yv,y0); rect_h=max(2,abs(y0-yv))
            bits.append(f'<rect x="{x:.1f}" y="{rect_y:.1f}" width="{barw:.1f}" height="{rect_h:.1f}" rx="6" fill="{COLORS[si%len(COLORS)]}"/>')
            lab=f'{val*100:.1f}%' if percent else f'{val:.1f}'
            labely=yv-10 if val>=0 else yv+25
            bits.append(f'<text x="{x+barw/2:.1f}" y="{labely:.1f}" text-anchor="middle" font-family="{FONT}" font-size="16" fill="#253e50">{lab}</text>')
        bits.append(f'<text x="{center:.1f}" y="{top+ph+42}" text-anchor="middle" font-family="{FONT}" font-size="20" fill="#304c60">{esc(cat)}</text>')
    legend_y=H-78; totalw=len(series)*240; lx=(W-totalw)/2
    for i,(name,_) in enumerate(series):
        x=lx+i*240
        bits.append(f'<rect x="{x}" y="{legend_y-18}" width="22" height="22" rx="4" fill="{COLORS[i%len(COLORS)]}"/>')
        bits.append(f'<text x="{x+32}" y="{legend_y}" font-family="{FONT}" font-size="19" fill="#304c60">{esc(name)}</text>')
    bits.append('</svg>')
    (FIG/filename).write_text('\n'.join(bits)+'\n',encoding='utf-8')

# Development comparison
r=rows('development_main_table.csv')
cat=['MTB D30','CIViC D30']; arms=['b0_common_single','g_k4','p_k_specialists','v3/p_k_specialists']; labels=['B0','G-K','P-K','V3']
chart('development_comparison.svg','Fresh development comparison','Small fixed development samples; accuracy includes failures',['MTB D30','CIViC D30'],[(lab,[float(next(x['accuracy'] for x in r if x['dataset']==ds and x['arm']==arm)) for ds in ['MTB','CIViC']]) for arm,lab in zip(arms,labels)])
# Independent holdout
r=rows('mtb_holdout_main_table.csv')
chart('mtb_holdout.svg','Independent MTB confirmation','85 cases across 19 patient groups; cluster-bootstrap CI is in the report',['B0','V3'],[
 ('Accuracy',[float(next(x['accuracy'] for x in r if x['method']==m)) for m in ['Single Agent','OncoFusion V3']]),
 ('Completion',[float(next(x['valid_completion_rate'] for x in r if x['method']==m)) for m in ['Single Agent','OncoFusion V3']])])
# Role contribution: leave-one-out accuracy delta vs full
r=rows('role_ablation.csv'); cats=[]; vals=[]
for ds in ['MTB','CIViC']:
 for role in ['literature','timeline','genomics','pathology','drug']:
  x=next(q for q in r if q['dataset']==ds and q['role']==role)
  if x['accuracy_diff']!='': cats.append(ds+' '+role.title()); vals.append(float(x['accuracy_diff']))
chart('role_contribution.svg','Leave-one-role-out change','Difference from the full P-K result; historical role ablations',['' for _ in []],[]) if False else None
# Render an SVG with a symmetric scale for role deltas.
chart('role_contribution.svg','Leave-one-role-out change','Accuracy difference from full P-K; historical reaggregation',cats,[('Accuracy Δ',vals)],minv=-0.03,maxv=0.03,percent=True)
# Role chart max scale label will show -3% to +3%.
# Member count common K=4
r=rows('member_count.csv'); cats=[]; vals_m=[]; vals_c=[]
for k in range(1,5):
 m=next(x for x in r if x['dataset']=='MTB' and x['cohort']=='common_K4' and int(x['k'])==k)
 c=next(x for x in r if x['dataset']=='CIViC' and x['cohort']=='common_K4' and int(x['k'])==k)
 cats.append('k='+str(k)); vals_m.append(float(m['mean_case_expected_accuracy'])); vals_c.append(float(c['mean_case_expected_accuracy']))
chart('member_count.svg','Specialist pool size','Expected accuracy over member subsets on the common-K4 cohorts',cats,[('MTB n=36',vals_m),('CIViC n=82',vals_c)])
# Input length
r=rows('length_summary.csv'); cats=['MTB short','MTB medium','MTB long','CIViC short','CIViC medium','CIViC long']
series=[]
for arm,lab in [('b0_common_single','B0'),('v3/p_k_specialists','V3')]:
 series.append((lab,[float(next(x['accuracy'] for x in r if x['dataset']==ds and x['length_group']==g and x['arm']==arm)) for ds,g in [('MTB','short'),('MTB','medium'),('MTB','long'),('CIViC','short'),('CIViC','medium'),('CIViC','long')]]))
chart('length_groups.svg','Accuracy by input length','Predefined short / medium / long bins; observational comparison',cats,series)
# Evidence position
r=rows('position_summary.csv'); cats=['MTB front','MTB middle','MTB end','CIViC front','CIViC middle','CIViC end']
series=[]
for arm,lab in [('b0_common_single','B0'),('p_k_specialists','P-K'),('v3/p_k_specialists','V3')]:
 series.append((lab,[float(next(x['accuracy'] for x in r if x['dataset']==ds and x['condition']==cond and x['arm']==arm)) for ds,cond in [('MTB','front'),('MTB','middle'),('MTB','end'),('CIViC','front'),('CIViC','middle'),('CIViC','end')]]))
chart('evidence_position.svg','Evidence position sensitivity','MTB n=8 per position; CIViC n=4 per position',cats,series)
# Robustness
r=rows('robustness_summary.csv'); cats=['R0 base','R1 molecular','R2 pathology','R3 events','R4 fragments']
series=[]
for method,lab in [('B0','B0'),('P-K no arbitration','P-K'),('V3','V3')]:
 series.append((lab,[float(next(x['accuracy'] for x in r if x['condition']==c and x['method']==method)) for c in ['R0','R1','R2','R3','R4']]))
chart('robustness.svg','Evidence-missing robustness','20 cases per condition; R0 is reused unmodified evidence',cats,series)
# Threshold sweep, show accuracy only; raw calls live in CSV
r=rows('threshold_results.csv'); cats=['0.50','0.60','0.75','1.00','Always']; vals_m=[]; vals_c=[]
for ds in ['MTB','CIViC']:
 values=[]
 for pol in ['share_050','share_060','share_075','share_100','always']:
  x=next(y for y in r if y['dataset']==ds and y['policy']==pol); values.append(float(x['accuracy']))
 (vals_m if ds=='MTB' else vals_c).extend(values)
chart('thresholds.svg','Arbitration threshold sweep','No threshold changed accuracy in the fixed D30 samples',cats,[('MTB',vals_m),('CIViC',vals_c)])
# Citation review snapshot: separate offset exactness and one AI-assisted semantic review.
chart('citation_quality.svg','Citation audit snapshot','Separate denominators: exact offsets, then 24 AI-assisted claim reviews',
 ['H-MTB offsets','D-CIViC offsets','Supported','Partial','Unsupported'],[
 ('Observed rate',[1.0,1.0,10/24,14/24,0.0])])
print('created',len(list(FIG.glob('*.svg'))),'SVGs')
