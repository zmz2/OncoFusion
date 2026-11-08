# Direct upstream references for this iteration

Checked 2026-11-09. These notes distinguish code actually run from methods adapted.

## CIViC-Fact: label semantics and evidence construction

- Repository: https://github.com/creisle/civicfact
- Reviewed commit: `1a767d889b015a836f0f4331afcac5cef165ec7f`
- Files: `data_builder/src/nli/set_labels_and_reasoning.py`,
  `experiments/src/api/create_explanation_prompts.py`

The builder defines SUPPORTS as the claim supported as-is; REVISIONS as evidence
relevant to the claim while the claim as-is is unsupported, with a revision that
better represents the evidence; NEI as no matching claim or insufficient evidence.
This motivates separating global evidence relevance from the truth of the original
structured claim.

We adapt the label mapping in OncoFusion. We do not copy the builder pipeline or use
gold revisions at inference. The local evidence texts and labels remain governed by
the already prepared 2026.06.09 snapshot.

## GeneAgent: generate, source-check, revise

- Repository: https://github.com/ncbi-nlp/GeneAgent
- Method reference: gene-set task with claim generation, source checking and revision.

OncoFusion already has server claim IDs, per-claim verdicts, exact citations and
bounded schema repair. This iteration adds a global revision assessment to the
Decision input and keeps professional local relations separate. It does not copy
GeneAgent weights or its runner.

## TxAgent and ToolUniverse: drug evidence qualification

- TxAgent README: https://github.com/mims-harvard/TxAgent
- ToolUniverse: https://github.com/mims-harvard/ToolUniverse

The relevant reusable mechanisms are evidence-qualified drug reasoning and typed
tool access. This project already reuses the ToolUniverse SDK for an allowlist of
read-only source tools. Standard CIViC verification remains closed-corpus; no live
database lookup or TxAgent model weight is used.

## PaperQA2: balanced evidence organization

- Repository: https://github.com/Future-House/paper-qa

Relevant ideas are evidence gathering, source-grounded synthesis and contradiction
handling. The full package, embedding models and retrieval planner are not copied.
The CIViC slice has one supplied evidence item per case, so retrieval ranking is not
evaluated here.

## LangGraph: modular state and bounded branching

- Documentation: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- Runtime version: `langgraph==1.2.16`

The project actually runs LangGraph StateGraph nodes. This iteration keeps the fixed
roles and bounded repair/requery rather than introducing free-form agent chat.

## Experimental implication

The first controlled hypothesis is narrow: global revision assessment should recover
REVISIONS cases where evidence is relevant and only a claim field is wrong, without
changing evidence access or adding roles. It is compared against the unchanged
multi-agent pipeline and a strong single-agent baseline on a predeclared 60-case dev
set. The mechanism is retained only if paired outcomes and protocol audits support it.
