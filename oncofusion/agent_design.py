"""Source-attributed role contracts; mechanisms are adapted, not upstream model weights.

The runtime dependencies actually reused are recorded in upstream_manifest.json.
These research instructions intentionally contain no fixed treatment recommendations.
"""
from __future__ import annotations

from .schemas import Role

CONTRACTS: dict[str, dict] = {
    "timeline": {
        "basis": ["MTBBench staged visibility", "medspaCy context distinctions (design only)"],
        "purpose": "Build the patient's current state from visible historical observations.",
        "steps": [
            "Keep event time, recording order, and current information availability distinct.",
            "Distinguish observed events, negated events, planned treatments, family history, and uncertain events.",
            "Link treatment exposure and subsequent observations by dates when supplied; a later event alone does not establish causation.",
            "Keep unknown dates and unresolved ordering explicit. Every event assertion cites original text.",
        ],
    },
    "genomics": {
        "basis": ["GeneAgent generate-verify-revise", "ToolUniverse molecular profile validation"],
        "purpose": "Interpret exact molecular observations in their disease and assay context.",
        "steps": [
            "Resolve the supplied gene and exact variant spelling; retain transcript, assay and germline/somatic ambiguity where relevant.",
            "Separate gene-pathway membership, variant functional consequence, and measured pathway activity into distinct assertions.",
            "Check each mechanistic hypothesis against retrieved original evidence or explicitly marked database records.",
            "Assign functional direction only when supported at the appropriate variant level. Record missing functional evidence as unresolved.",
        ],
    },
    "pathology": {
        "basis": ["OncoFusion structured specimen adapter", "medspaCy assertion context (design only)"],
        "purpose": "Determine where molecular and therapeutic evidence is applicable.",
        "steps": [
            "Extract supplied cancer type, histology, primary site, sampled site, stage, and assay biomarkers with citations.",
            "Keep primary and metastatic specimens distinct. Distinguish patient findings from family history or hypothetical descriptions.",
            "Evaluate whether external evidence concerns the same disease, specimen and biomarker definition; label missing context.",
            "Text-only records support text interpretation. Image findings require an actual image-analysis tool result.",
        ],
    },
    "drug": {
        "basis": ["TxAgent therapeutic reasoning", "ToolUniverse precision-oncology workflow"],
        "purpose": "Build evidence-qualified molecular and drug relationships for the research question.",
        "steps": [
            "Connect each candidate drug to its target and the exact molecular and disease context supported by the sources.",
            "Separate sensitivity, primary resistance, acquired resistance, and prior exposure. Treat lexical polarity as a retrieval hint.",
            "Identify whether evidence comes from cell assays, animal studies, case reports, trials, labels, or curated records.",
            "Check stated contraindications or co-medications only when the question and supplied data make them relevant. Keep unavailable safety evidence explicit.",
            "Record approval jurisdiction and date only from an applicable source; keep experimental mechanisms separate from a patient treatment recommendation.",
        ],
    },
    "literature": {
        "basis": ["PaperQA2 search-gather evidence-answer", "GeneAgent source-based verification"],
        "purpose": "Assemble a compact, balanced evidence packet from the permitted corpus.",
        "steps": [
            "Select passages addressing the actual claim, including its molecular, disease, drug and temporal qualifiers.",
            "For each finding retain an exact quote, original source identity, applicability and what the evidence directly measures.",
            "Retain relevant opposing results alongside supporting evidence; repeated copies of a paper remain one source.",
            "Separate a search hit, a curated database statement and a primary experimental finding. Preserve uncertainty and missing evidence.",
            "A follow-up query targets one unresolved claim. Use only the corpus exposed for this task.",
        ],
    },
    "verifier": {
        "basis": ["GeneAgent independent source checking", "PaperQA2 contradiction analysis"],
        "purpose": "Audit candidate assertions against sources and identify a bounded correction target.",
        "steps": [
            "Treat the candidate board as claims to examine, rather than evidence or votes.",
            "Independently compare important claims with exact original passages, checking variant, disease, drug, time and experimental endpoint.",
            "Keep quote integrity distinct from semantic support. A literal quote can still fail to support the attached claim.",
            "For each finding explicitly state what survives verification and what needs correction. Preserve unresolved conflicts.",
            "Request at most one focused literature query for a missing, material piece of evidence. Stop when the permitted corpus cannot answer it.",
        ],
    },
    "decision": {
        "basis": ["MDAgents moderator synthesis (design only)", "OncoFusion evidence/provenance contract"],
        "purpose": "Answer the benchmark question from the current verified evidence state.",
        "steps": [
            "Use the requested answer vocabulary, option keys or synthesis format. Respect the task's exact label definitions.",
            "Weight evidence by applicability, source quality and endpoint, not by the number of agents repeating it.",
            "Resolve discrepancies from primary evidence where possible; retain remaining uncertainty and disagreement in unresolved.",
            "Distinguish observed outcomes, mechanistic plausibility, and predictions. Supply original-source citations for substantive conclusions.",
            "A model's self-reported confidence is uncalibrated until assessed on held-out development data.",
        ],
    },
}


def duty(role: Role) -> str:
    contract = CONTRACTS[role]
    return contract["purpose"] + " Procedure: " + " ".join(
        f"{i}. {step}" for i, step in enumerate(contract["steps"], 1)
    )


def catalog() -> dict:
    return {"version": "2.0", "roles": CONTRACTS,
            "reuse": {"langgraph": "runtime dependency", "tooluniverse": "optional SDK for approved source snapshots",
                      "GeneAgent": "mechanism adaptation", "PaperQA2": "mechanism adaptation",
                      "MDAgents": "design reference", "medspaCy": "design reference"}}
