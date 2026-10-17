# Third-party source and runtime notices

## Copied PaperQA prompts

`oncofusion/vendor/paperqa_prompts.py` contains two verbatim string templates from
Future-House/paper-qa, `src/paperqa/prompts.py`, commit
`57e89f7223b0960d5ee5ea048c69e3c47e088572`.
Copyright FutureHouse / PaperQA contributors. Licensed under Apache-2.0.
The complete license is included in `third_party/paperqa.LICENSE` and wheel license metadata.
Only the selected constants are copied; OncoFusion supplies provider, schema, usage
accounting, bounded context selection and source isolation.

## Adapted GeneAgent source

`oncofusion/vendor/geneagent_enrichment.py` adapts
ncbi-nlp/GeneAgent `apis/get_pathway_for_gene_set.py`, commit
`88fd1adb40dce9545bde5b904ef3a628c09d747c`.
The original is a United States Government work from NLM. Its full public-domain
notice is included in `third_party/geneagent.LICENSE` and wheel license metadata.
Credit: Zhizheng Wang, Qiao Jin, Chih-Hsuan Wei, Shubo Tian, Po-Ting Lai,
Qingqing Zhu, Chi-Ping Day, Christina Ross, Robert Leaman, Zhiyong Lu.
GeneAgent: Self-verification Language Agent for Gene Set Analysis using Domain Databases.
Changes: HTTPS, timeouts, validation, bounded libraries/output, explicit failures,
adjusted p-values and structured provenance. The original algorithm's two-step
Enrichr workflow is retained; upstream LLM runtime and datasets are not copied.

## Runtime dependencies

LangGraph 1.0.10 (MIT) is imported for actual graph orchestration. ToolUniverse 1.5.7
(Apache-2.0) is an optional dependency, imported for a six-tool biomedical allowlist.
These packages retain their own distribution notices and dependency licenses.
Individual databases, services and papers retain their own access and reuse terms;
a software toolkit license does not license retrieved data or scientific claims.

## Design references, not copied source

TxAgent, GeneAgent's verification architecture, MDAgents and Biomni inform the
comparative design described in docs/AGENT_DESIGN.md. MDAgents source is not
copied: no LICENSE file was found in the audited tree. No TxAgent/Biomni model
weights or full agent runtimes are distributed. No endorsement is implied.
