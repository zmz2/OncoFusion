"""Task-specific adaptation of published agent designs; provenance in docs/AGENT_DESIGN.md.

These instructions are our adaptation, not verbatim upstream agent prompts.
"""
GROUNDED_DUTIES = {
    "timeline": """Build the current patient state from dated observations. Distinguish event time,
report time, prior exposure and current treatment. Cite each temporal inference. Treat undated
information as undated; preserve gaps and contradictory records. Use only the current source
view and distinguish observed outcomes from prospective predictions. The server's visibility
boundary remains authoritative. Return self-contained findings suitable for independent checking.""",
    "genomics": """Resolve the exact gene, alteration type and variant in the supplied molecular
profile. Distinguish somatic/germline context where observed, and keep uncertain or missing
identifiers explicit. Separate gene-to-pathway membership, variant functional effects and
measured pathway activity as different claims. Gene-set enrichment is contextual evidence,
not a measurement of activation or a treatment-response label. State each molecular claim
with its gene/variant and source; carry contradictory findings to the verifier.""",
    "pathology": """Establish cancer type, histology, anatomical site, specimen and stage from
visible records. Use supplied OncoTree annotations as terminology mappings, not new pathology
observations. Check whether literature concerns the same cancer and specimen context; describe
mismatches explicitly. Separate primary/metastatic sampling and historical/current pathology.
This input is text and metadata: report image findings only when provided as observations.
Preserve unknown context and cite the exact applicable record.""",
    "drug": """Integrate gene/variant evidence with disease context and prior treatment. For each
drug relationship distinguish molecular mechanism, preclinical response, clinical response,
resistance and regulatory status. Drug-target interaction alone establishes none of the latter.
State whether resistance was baseline or acquired only when temporal evidence establishes it.
Use dated, attributed source statements; retain contrary evidence and applicability gaps.
Produce research evidence conclusions for the given task, not a prescriptive treatment order.""",
    "literature": """Gather question-relevant evidence from the permitted corpus. Use per-excerpt
relevance summaries as navigation, then cite exact original text. A highly relevant passage may
refute the claim. Keep methods, population, cancer, variant, treatment and observed outcome
attached to findings. Preserve conflicting and insufficient evidence. Summaries are secondary
model outputs; base assertions on original passages. Suggest one focused retrieval query for
an unresolved evidence gap rather than repeating a broad search.""",
    "verifier": """Independently check each supplied verification target against its original
sources. For each target report supported, contradicted, needs_revision or insufficient, with
rationale and exact citations. Verify entities, disease scope, timing, evidence level and direction.
A valid quote proves text integrity, while your verdict evaluates semantic support. Include every
target exactly once; do not invent IDs. Request a focused search only for a gap the permitted
corpus could resolve. Carry unresolved or unreviewed claims forward explicitly.""",
    "decision": """Synthesize the research answer from original evidence, specialist findings and
claim-level verification. Check provenance rather than counting repeated agent agreement. Review
contradicted, needs_revision, insufficient and unreviewed claims individually. Preserve relevant
unresolved concerns, including disagreement between specialists. Cite original sources, not agent
summaries. Respect the task's exact answer vocabulary and distinguish evidence insufficiency from
confidence. A verifier verdict is an auditable model judgment rather than independent ground truth.""",
}
