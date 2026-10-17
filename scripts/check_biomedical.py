"""Audit actual SDK availability and optional live public-identifier queries (no LLM)."""
import argparse
import json
from pathlib import Path
import time
from oncofusion.biomedical import ToolUniverseAdapter, ToolQuery, ALLOWED_TOOLS
from oncofusion.vendor.geneagent_enrichment import get_pathway_for_gene_set


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='use only built-in public identifiers')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    adapter=ToolUniverseAdapter()
    report={'tooluniverse_version':adapter.version,'catalog':sorted(adapter.sdk.all_tool_dict),
            'commercial_model_calls':0,'live_requests_requested':args.live,'checks':[]}
    queries=[
        ('MyGene_query_genes',{'query':'symbol:EGFR','species':'human','size':1}),
        ('OncoTree_get_type',{'code':'LUAD','version':'oncotree_latest_stable'}),
        ('Reactome_map_uniprot_to_pathways',{'uniprot_id':'P00533'}),
        ('ChEMBL_get_drug_mechanisms',{'drug_chembl_id':'CHEMBL941','limit':1}),
        ('OpenTargets_get_associated_drugs_by_target_ensemblID',{'ensemblId':'ENSG00000146648'}),
        ('PubMed_search_articles',{'query':'EGFR lung cancer','limit':1,'include_abstract':True,'maxdate':'2026/10/17'}),
    ]
    if args.live:
        for name,arguments in queries:
            start=time.monotonic()
            try:
                snapshot=adapter.execute(ToolQuery(name=name,arguments=arguments,purpose='public upstream availability audit'),allow_remote=True)
                record={'tool':name,'status':'passed','response_sha256':snapshot.response_sha256,
                        'response_bytes':len(snapshot.model_dump_json())}
                if name=='PubMed_search_articles':
                    record['attachable_abstracts']=len(snapshot.documents(stage=0))
            except Exception as error:
                # This is the external-service acceptance boundary; preserve failure, never mock.
                record={'tool':name,'status':'failed','error_type':type(error).__name__,'error':str(error)[:300]}
            record['seconds']=round(time.monotonic()-start,3);report['checks'].append(record)
            print(json.dumps(record),flush=True)
        try:
            hits=get_pathway_for_gene_set(['EGFR','BRAF','KRAS','MAP2K1'],allow_remote=True)
            record={'tool':'GeneAgent_Enrichr','status':'passed','returned_hits':len(hits)}
        except Exception as error:
            record={'tool':'GeneAgent_Enrichr','status':'failed','error_type':type(error).__name__,'error':str(error)[:300]}
        report['checks'].append(record)
    report['status']='failed' if any(x['status']=='failed' for x in report['checks']) else 'passed'
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 2 if report['status']=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
