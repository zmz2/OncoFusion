"""Exercise genuine installed libraries while keeping LLM responses explicitly simulated."""
from __future__ import annotations
import argparse
import json
from importlib.metadata import version
from pathlib import Path

from oncofusion.config import presets
from oncofusion.engine import Engine
from oncofusion.examples import examples
from oncofusion.providers import MockProvider
from oncofusion.schemas import RunConfig
from oncofusion.upstream_tools import SourcePlan, ToolRequest, ToolUniverseSources, attach_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live-database", action="store_true", help="one public MyGene BRAF query; no patient input")
    args = parser.parse_args()
    configurations = list(presets().values()) + [RunConfig(evidence_first=True, specialist_contracts=True,
                                                          latest_role_board=True)]
    comparisons = 0
    for config in configurations:
        for case in examples().values():
            native = Engine(MockProvider()).run(case, config)
            graph = Engine(MockProvider()).run(case, config.model_copy(update={"workflow_backend": "langgraph"}))
            assert native.status == graph.status == "completed"
            assert native.decision == graph.decision and native.reports == graph.reports
            assert native.usage == graph.usage
            assert "FUTURE_CANARY" not in graph.model_dump_json()
            comparisons += 1
    sdk = ToolUniverseSources.installed()
    requests = [
        ToolRequest(name="MyGene_query_genes", arguments={"query": "BRAF", "species": "human", "fields": "symbol,entrezgene"}),
        ToolRequest(name="UniProt_get_function_by_accession", arguments={"accession": "P15056"}),
        ToolRequest(name="DGIdb_get_drug_gene_interactions", arguments={"genes": ["BRAF"]}),
        ToolRequest(name="OpenTargets_get_associated_drugs_by_target_ensemblID", arguments={"ensemblId": "ENSG00000157764"}),
        ToolRequest(name="PubMed_search_articles", arguments={"query": "BRAF melanoma", "limit": 2}),
        ToolRequest(name="Reactome_map_uniprot_to_pathways", arguments={"uniprot_id": "P15056"}),
        ToolRequest(name="Reactome_get_pathway", arguments={"stId": "R-HSA-5673001"}),
    ]
    for request in requests:
        sdk.validate(request)
    report = {"status": "passed", "libraries": {n: version(n) for n in ("langgraph", "tooluniverse")},
              "graph_native_comparisons": comparisons, "registered_tools": sorted(sdk.specs),
              "validated_tool_schemas": len(requests), "llm_simulated": True,
              "commercial_llm_calls": 0, "live_database_calls": 0}
    if args.live_database:
        snapshot = sdk.collect(SourcePlan(requests=[requests[0]], public_queries_reviewed=True, source_terms_accepted=True))
        assert "BRAF" in json.dumps(snapshot["records"][0]["response"])
        report["live_database_calls"] = snapshot["tool_calls"]
        report["database_response_sha256"] = snapshot["records"][0]["response_sha256"]
        report["database_query"] = requests[0].model_dump()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
