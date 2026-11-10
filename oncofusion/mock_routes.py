"""Deterministic plumbing simulator for route-specific output schemas."""
from __future__ import annotations

import json

from .providers import MockProvider, ModelReply, ProviderError


class MockRouteProvider(MockProvider):
    """Exercises route control flow without claiming biomedical reasoning."""

    def complete(self, system, payload, max_tokens, temperature, seed):
        if "conforming to this schema: " not in system:
            return super().complete(system, payload, max_tokens, temperature, seed)
        schema_text = system.split("conforming to this schema: ", 1)[-1]
        # Schemas are one object at the end of system text. Some call sites
        # append no instruction after it, so use the exact JSON decoder rather
        # than accepting a generic substring.
        try:
            schema = json.JSONDecoder().raw_decode(schema_text)[0]
        except json.JSONDecodeError:
            return super().complete(system, payload, max_tokens, temperature, seed)
        title = schema.get("title", "")
        ids = [entry["evidence_id"] for entry in payload.get("evidence", [])]
        first = [{"evidence_id": ids[0]}] if ids else []
        task = payload.get("task", "")
        labels = payload.get("verification_labels") or ["SUPPORTS", "REVISIONS", "NEI"]
        options = list((payload.get("options") or {}).keys())

        if title == "VoteBallotOutput":
            label = (
                labels[0] if task == "verification"
                else options[0] if options else "NEI"
            )
            body = {
                "status": "vote" if first else "abstain",
                "label": label if first else None,
                "confidence": .6 if first else None,
                "brief_reason": (
                    "SIMULATED independent ballot from a visible evidence span."
                    if first else "No visible evidence for a simulated ballot."
                ),
                "evidence_ids": first,
                "findings": [{
                    "statement": "SIMULATED local evidence check.",
                    "stance": "supports",
                    "evidence_ids": first,
                }] if first else [],
            }
        elif title == "VoteAdjudicationOutput":
            label = (
                labels[0] if task == "verification"
                else options[0] if options else "NEI"
            )
            body = {
                "label": label,
                "explanation": "SIMULATED one-shot arbitration; not a biomedical judgement.",
                "evidence_ids": first,
                "unresolved": [],
            }
        elif title == "RouteAnalysis":
            body = {
                "findings": [{
                    "statement": "SIMULATED route finding from a visible evidence span.",
                    "citations": first,
                    "relation": labels[0] if task == "verification" else "NEI",
                    "material_status": "present" if first else "not_applicable",
                }] if first else [],
                "unresolved": [] if first else ["No matching visible evidence."],
            }
        elif title == "RouteReview":
            body = {
                "agrees": True,
                "issues": [],
                "corrections": [],
                "citations": first,
            }
        elif title == "ConflictPlan":
            body = {"conflicts": []}
        elif title == "EvidencePlan":
            body = {"needs": [{
                "question": "Check the supplied evidence against the question.",
                "roles": ["literature"],
            }]}
        elif title == "LogicReview":
            body = {
                "links": [{
                    "premises": ["The supplied source is visible."],
                    "conclusion": "Only a simulated logic record is available.",
                    "valid": True,
                    "issue": "",
                    "citations": first,
                }],
                "unresolved": [],
            }
        elif title == "ComplexityOutput":
            body = {
                "level": "intermediate",
                "roles": ["literature", "genomics", "pathology", "drug"],
            }
        elif title == "ResidualReport":
            body = {
                "consistency": ["SIMULATED shared observation."],
                "conflict": [],
                "independence": ["SIMULATED independent observation."],
                "integration": "SIMULATED residual synthesis.",
            }
        elif title == "RouteDecision":
            if task == "verification":
                answer = labels[-1]
            elif task == "mcq":
                answer = options[0] if options else "?"
            else:
                answer = "SIMULATED evidence summary."
            roster = [entry["claim_id"] for entry in
                      (payload.get("shared_context", {}).get("registered_claims")
                       or payload.get("claim_roster", []))]
            body = {
                "answer": answer,
                "explanation": "SIMULATED route control-flow output; not a biomedical judgement.",
                "citations": first,
                "unresolved": [],
                "confidence": None,
                "adopted_claim_ids": roster,
                "rejected_claim_ids": [],
            }
        else:
            return super().complete(system, payload, max_tokens, temperature, seed)
        content = json.dumps(body, ensure_ascii=False)
        if len(content) // 4 > max_tokens:
            raise ProviderError("simulated route output exceeds configured token limit")
        return ModelReply(
            content,
            max(1, len(json.dumps(payload, ensure_ascii=False)) // 4),
            max(1, len(content) // 4),
            estimated=True)
