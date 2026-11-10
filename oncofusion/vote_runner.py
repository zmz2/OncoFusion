"""Independent professional ballots with deterministic aggregation and one optional arbitration."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .agent_design import duty as specialist_duty
from .engine import BudgetExceeded, TASK_FRAMING, run_fingerprint
from .evidence import fragment_documents, resolve_fragment_citations, visible_case
from .providers import Provider, ProviderError
from .schemas import (
    AgentReport,
    AnalysisOutput,
    Ballot,
    BallotFinding,
    CaseInput,
    Citation,
    DecisionOutput,
    Finding,
    FragmentCitation,
    RunConfig,
    RunResult,
    TraceEvent,
    Usage,
    VoteAdjudicationOutput,
    VoteArbitration,
    VoteBallotOutput,
)
from .voting import (
    aggregate_ballots,
    arbitration_required,
    eligible_vote_roles,
    vote_role_applicability,
)


STANCE_TO_RELATION = {"supports": "SUPPORTS", "contradicts": "NEI", "unmentioned": "NEI"}


def build_vote_decision(
    case: CaseInput,
    config: RunConfig,
    vote_result,
    ballots: list[Ballot],
    evidence_index: dict,
) -> DecisionOutput | None:
    if vote_result.completion_status == "failed" or vote_result.label is None:
        return None
    supporting = [
        ballot for ballot in ballots
        if ballot.status == "vote" and ballot.label == vote_result.label
    ]
    citations = []
    seen = set()
    for ballot in supporting:
        for finding in ballot.findings:
            for citation in finding.citations:
                key = (citation.document_id, citation.start, citation.end, citation.quote)
                if key not in seen:
                    seen.add(key)
                    citations.append(citation)
    for evidence_id in (
            vote_result.arbitration.evidence_ids
            if vote_result.arbitration.status == "completed" else []):
        for citation in resolve_fragment_citations(
                [FragmentCitation(evidence_id=evidence_id)], evidence_index):
            key = (citation.document_id, citation.start, citation.end, citation.quote)
            if key not in seen:
                seen.add(key)
                citations.append(citation)
    unresolved = []
    if vote_result.failed_votes:
        unresolved.append(
            f"{vote_result.failed_votes} of {vote_result.planned_votes} members failed.")
    if vote_result.abstain_votes:
        unresolved.append(
            f"{vote_result.abstain_votes} of {vote_result.planned_votes} members abstained.")
    if vote_result.tied:
        unresolved.append(
            "The vote was tied; a deterministic case-id hash selected the displayed label.")
    if vote_result.arbitration.status == "failed":
        unresolved.append(
            "Low-consensus arbitration failed; the initial aggregate was retained.")
    if vote_result.arbitration.status == "completed":
        unresolved.extend(vote_result.arbitration.unresolved)
    if config.vote_rule != "v3":
        unresolved.append(
            "Semantic evidence review was not executed for this pure vote.")
    if not citations and vote_result.label != "NEI":
        unresolved.append(
            "The selected label has no resolved supporting citation in the ballot pool.")
    explanation = (
        f"Rule {config.vote_rule}: selected {vote_result.label}. "
        f"Valid ballots {vote_result.valid_votes}/{vote_result.planned_votes}; "
        f"counts {json.dumps(vote_result.counts, sort_keys=True)}; "
        f"scores {json.dumps(vote_result.scores, sort_keys=True)}."
    )
    if (vote_result.arbitration.status == "completed"
            and vote_result.arbitration.explanation):
        explanation += " Arbitration: " + vote_result.arbitration.explanation
    return DecisionOutput(
        answer=vote_result.label,
        explanation=explanation,
        citations=citations[:30],
        unresolved=unresolved,
        confidence=None,
    )


class VoteEngine:
    def __init__(self, provider: Provider):
        self.provider = provider

    def run(self, case: CaseInput, config: RunConfig,
            on_event: Callable[[TraceEvent], None] | None = None) -> RunResult:
        if config.execution_model != "vote" or config.interaction_protocol != "vote-v1":
            raise ValueError("VoteEngine requires execution_model=vote and interaction_protocol=vote-v1")
        if not self.provider.simulated and case.data_class == "unreviewed":
            raise ValueError("review/deidentify the case before remote model processing")

        visible = visible_case(case)
        documents = visible.documents
        if not documents:
            raise ValueError("vote-v1 requires at least one visible document")
        query = " ".join(filter(None, [
            visible.question,
            *[str(value) for value in visible.entities.model_dump().values() if value],
        ]))
        evidence, evidence_index, coverage = fragment_documents(
            documents,
            config.fragment_chars,
            config.max_fragments_per_document,
            query,
            config.fragment_budget,
            role="decision",
        )
        if not evidence:
            raise ValueError("vote-v1 evidence planner supplied no evidence")
        labels = (list(visible.verification_labels)
                  if visible.task == "verification" else sorted(visible.options))
        specialist_roles = eligible_vote_roles(visible, config.vote_members)
        role_applicability = vote_role_applicability(
            visible, config.vote_members)
        if not specialist_roles:
            raise ValueError("vote-v1 has no applicable professional voters")
        planned_roles = (
            specialist_roles if config.vote_pool == "specialist"
            else [
                f"generalist-{index:02d}"
                for index in range(1, min(config.vote_members, len(specialist_roles)) + 1)
            ]
        )

        started = time.monotonic()
        usage = Usage()
        trace: list[TraceEvent] = []
        reports: list[AgentReport] = []
        ballots: list[Ballot] = []
        ledger = threading.RLock()
        reserved_inflight_tokens = 0
        budget_failures = 0
        fingerprint = run_fingerprint(visible, config, self.provider)
        source_roster = [
            {key: value for key, value in document.model_dump(mode="json").items() if key != "text"}
            for document in documents
        ]

        def emit(kind: str, role: str = "", **details):
            with ledger:
                event = TraceEvent(sequence=len(trace), kind=kind, role=role, details=details)
                trace.append(event)
                if on_event:
                    on_event(event)

        def member_payload(prompt_role: str, source_instruction: str) -> dict:
            payload = {
                "role": prompt_role,
                "task": visible.task,
                "question": visible.question,
                "verification_scheme": visible.verification_scheme,
                "verification_labels": labels if visible.task == "verification" else [],
                "options": visible.options,
                "entities": visible.entities.model_dump(),
                "stage": visible.stage,
                "as_of_day": visible.as_of_day,
                "sources": source_roster,
                "signals": {},
                "evidence": evidence,
                "evidence_ids": [entry["evidence_id"] for entry in evidence],
                "evidence_coverage": coverage,
                "instruction": source_instruction,
            }
            return payload

        def member_system(prompt_role: str) -> str:
            instruction = (
                specialist_duty(prompt_role)
                if config.vote_pool == "specialist"
                else "Act as an independent generalist biomedical analyst."
            )
            ballot_schema = VoteBallotOutput.model_json_schema()
            ballot_schema["properties"]["label"] = {
                "anyOf": [
                    {"type": "string", "enum": labels},
                    {"type": "null"},
                ]
            }
            system = (
                "You are one independent member of a research-only evidence vote. "
                "You receive the same complete question and evidence packet as every other "
                "member, and you do not see their answers. Use only the supplied evidence. "
                + instruction + " "
                + TASK_FRAMING[visible.task] + " "
                "First record at most two short, checkable professional findings with visible "
                "evidence ids. Then answer the same full task independently. A local absence "
                "or not-applicable observation is not automatically a global NEI vote. "
                "ABSTAIN only when your professional responsibility is completely inapplicable "
                "or you cannot form any task-level judgement. For a non-NEI answer, cite at "
                "least one visible evidence id. Do not invent labels, evidence ids, PMIDs, "
                "patient history, or outside facts. Confidence is an uncalibrated self-rating "
                "of whether your own full answer is correct. Return JSON only conforming to this schema: "
                + json.dumps(ballot_schema, ensure_ascii=False)
            )
            if visible.task == "verification":
                system += (
                    " Legal labels are " + ", ".join(labels) + ". "
                    "SUPPORTS means the claim is evidenced as written; REVISIONS means a "
                    "specific correction is required; NEI means irrelevant, missing, or "
                    "insufficient evidence.")
            if visible.task == "mcq":
                system += (
                    " The label must be one option key from "
                    + ", ".join(visible.options) + ".")
            return system

        def reserve_call(prompt_role: str, payload: dict, system: str) -> tuple[int, str]:
            nonlocal reserved_inflight_tokens, budget_failures
            reservation = len((system + json.dumps(payload, ensure_ascii=False)).encode()) + config.max_output_tokens
            with ledger:
                if usage.calls >= config.max_calls:
                    budget_failures += 1
                    raise BudgetExceeded("model-call budget exhausted")
                if (usage.input_tokens + usage.output_tokens + reserved_inflight_tokens
                        + reservation > config.max_total_tokens):
                    budget_failures += 1
                    raise BudgetExceeded("token preflight budget exhausted")
                usage.calls += 1
                reserved_inflight_tokens += reservation
            emit(
                "agent_started",
                prompt_role,
                executor=prompt_role,
                payload_sha256=hashlib.sha256(
                    json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                source_ids=[entry["id"] for entry in source_roster],
                evidence_ids=[entry["evidence_id"] for entry in evidence],
                evidence_coverage=coverage,
                token_reservation=reservation,
            )
            return reservation, system

        def invoke_with_repair(
                member: str,
                payload: dict,
                system: str,
                sample_seed: int,
        ) -> tuple[VoteBallotOutput, Usage]:
            nonlocal reserved_inflight_tokens, budget_failures
            ballot_usage = Usage()
            repair = None
            for attempt in range(config.schema_retries + 1):
                current_payload = dict(payload)
                current_system = system
                if repair is not None:
                    current_payload["repair"] = repair
                    current_system += (
                        " The previous response failed validation. Return a complete corrected "
                        "JSON object. Validation errors: "
                        + "; ".join(
                            f"{'.'.join(map(str, error.get('loc', [])))}: {error.get('msg', '')}"
                            if error.get("loc") else str(error.get("msg", ""))
                            for error in repair.get("validation_errors", [])))
                reservation, current_system = reserve_call(member, current_payload, current_system)
                ballot_usage.calls += 1
                call_started = time.monotonic()
                try:
                    reply = self.provider.complete(
                        current_system,
                        current_payload,
                        config.max_output_tokens,
                        config.temperature,
                        sample_seed + attempt,
                    )
                except ProviderError as exc:
                    with ledger:
                        reserved_inflight_tokens -= reservation
                    if exc.observed_reply is not None:
                        observed = exc.observed_reply
                        with ledger:
                            usage.input_tokens += observed.input_tokens
                            usage.output_tokens += observed.output_tokens
                            usage.http_attempts += observed.attempts
                            usage.estimated_tokens |= observed.estimated
                            ballot_usage.http_attempts += observed.attempts
                            ballot_usage.input_tokens += observed.input_tokens
                            ballot_usage.output_tokens += observed.output_tokens
                            ballot_usage.estimated_tokens |= observed.estimated
                        emit(
                            "model_usage",
                            member,
                            input_tokens=observed.input_tokens,
                            output_tokens=observed.output_tokens,
                            attempts=observed.attempts,
                            estimated=observed.estimated,
                            seconds=round(time.monotonic() - call_started, 3),
                            evidence_fragments=len(evidence),
                        )
                    raise
                with ledger:
                    reserved_inflight_tokens -= reservation
                    usage.input_tokens += reply.input_tokens
                    usage.output_tokens += reply.output_tokens
                    usage.http_attempts += reply.attempts
                    usage.estimated_tokens |= reply.estimated
                    ballot_usage.http_attempts += reply.attempts
                    ballot_usage.input_tokens += reply.input_tokens
                    ballot_usage.output_tokens += reply.output_tokens
                    ballot_usage.estimated_tokens |= reply.estimated
                emit(
                    "model_usage",
                    member,
                    input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens,
                    attempts=reply.attempts,
                    estimated=reply.estimated,
                    seconds=round(time.monotonic() - call_started, 3),
                    evidence_fragments=len(evidence),
                )
                if usage.input_tokens + usage.output_tokens > config.max_total_tokens:
                    budget_failures += 1
                    raise BudgetExceeded("reported token usage exceeded budget")
                try:
                    wire = VoteBallotOutput.model_validate_json(reply.content)
                    if wire.status == "vote" and wire.label not in labels:
                        raise ValueError("ballot label outside the current task vocabulary")
                    ids = [
                        citation.evidence_id
                        for citation in wire.evidence_ids
                    ] + [
                        citation.evidence_id
                        for finding in wire.findings
                        for citation in finding.evidence_ids
                    ]
                    unknown = sorted(set(ids) - set(evidence_index))
                    if unknown:
                        raise ValueError(
                            "ballot cites evidence ids not visible to this member: "
                            + ", ".join(unknown))
                    if wire.status == "vote" and not ids and wire.label != "NEI":
                        raise ValueError("a non-NEI vote requires visible evidence")
                    return wire, ballot_usage
                except (ValueError, TypeError) as exc:
                    repair = {
                        "previous_output": reply.content[:65536],
                        "validation_errors": [{"msg": str(exc)}],
                        "valid_evidence_ids": sorted(evidence_index),
                        "legal_labels": labels,
                    }
                    emit(
                        "vote_invalid_output",
                        member,
                        error_type=type(exc).__name__,
                        **repair,
                    )
                    if attempt >= config.schema_retries:
                        raise ProviderError(
                            "vote output failed schema or source-integrity validation") from exc
                    emit("vote_repair_requested", member, attempt=attempt + 1)
            raise AssertionError("repair loop must return or raise")

        def make_ballot(
                member: str,
                prompt_role: str,
                source_instruction: str,
                sample_seed: int,
        ) -> Ballot:
            payload = member_payload(prompt_role, source_instruction)
            system = member_system(prompt_role)
            ballot_started = time.monotonic()
            input_fingerprint = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            try:
                wire, ballot_usage = invoke_with_repair(
                    member, payload, system, sample_seed)
            except BudgetExceeded as exc:
                ballot = Ballot(
                    ballot_id=member,
                    case_id=visible.id,
                    role=prompt_role,
                    model=self.provider.model,
                    seed=sample_seed,
                    input_fingerprint=input_fingerprint,
                    status="failed",
                    duration_seconds=round(time.monotonic() - ballot_started, 6),
                    error=str(exc),
                )
                emit("vote_member_failed", member, professional_role=prompt_role, reason=str(exc))
                return ballot
            except ProviderError as exc:
                ballot = Ballot(
                    ballot_id=member,
                    case_id=visible.id,
                    role=prompt_role,
                    model=self.provider.model,
                    seed=sample_seed,
                    input_fingerprint=input_fingerprint,
                    status="failed",
                    duration_seconds=round(time.monotonic() - ballot_started, 6),
                    error=str(exc),
                )
                emit("vote_member_failed", member, professional_role=prompt_role, reason=str(exc))
                return ballot

            if wire.status == "abstain":
                ballot = Ballot(
                    ballot_id=member,
                    case_id=visible.id,
                    role=prompt_role,
                    model=self.provider.model,
                    seed=sample_seed,
                    input_fingerprint=input_fingerprint,
                    status="abstain",
                    confidence=wire.confidence,
                    brief_reason=wire.brief_reason,
                    evidence_ids=list(dict.fromkeys(c.evidence_id for c in wire.evidence_ids)),
                    usage=ballot_usage,
                    duration_seconds=round(time.monotonic() - ballot_started, 6),
                )
            else:
                finding_rows = []
                for finding in wire.findings:
                    citations = resolve_fragment_citations(finding.evidence_ids, evidence_index)
                    finding_rows.append(BallotFinding(
                        statement=finding.statement,
                        stance=finding.stance,
                        citations=citations,
                    ))
                ballot = Ballot(
                    ballot_id=member,
                    case_id=visible.id,
                    role=prompt_role,
                    model=self.provider.model,
                    seed=sample_seed,
                    input_fingerprint=input_fingerprint,
                    status="vote",
                    label=wire.label,
                    confidence=wire.confidence,
                    brief_reason=wire.brief_reason,
                    evidence_ids=list(dict.fromkeys(c.evidence_id for c in wire.evidence_ids)),
                    findings=finding_rows,
                    usage=ballot_usage,
                    duration_seconds=round(time.monotonic() - ballot_started, 6),
                )
            output = AnalysisOutput(
                findings=[
                    Finding(
                        statement=finding.statement,
                        relation=STANCE_TO_RELATION[finding.stance],
                        citations=finding.citations,
                    )
                    for finding in ballot.findings
                ],
                unresolved=([ballot.brief_reason] if ballot.status == "abstain" else []),
            )
            if config.vote_pool == "specialist":
                with ledger:
                    reports.append(AgentReport(
                        role=prompt_role,
                        executor="vote-specialist",
                        output=output,
                    ))
            emit(
                "agent_reported",
                member,
                output=output.model_dump(mode="json"),
                ballot=ballot.model_dump(mode="json"),
            )
            emit("vote_member_completed", member, ballot=ballot.model_dump(mode="json"))
            return ballot

        emit(
            "run_started",
            visible_ids=[document.id for document in documents],
            fingerprint=fingerprint,
            simulated=self.provider.simulated,
            execution_model="vote",
            vote_pool=config.vote_pool,
            vote_rule=config.vote_rule,
            planned_roles=planned_roles,
            role_applicability=role_applicability,
        )
        with ThreadPoolExecutor(max_workers=max(
                1, min(config.vote_workers, len(planned_roles)))) as pool:
            items = [
                (
                    member,
                    member if config.vote_pool == "specialist" else "generalist",
                    "Answer the full task after your professional findings."
                    if config.vote_pool == "specialist"
                    else "Do not use a professional shortlist; answer the full task directly.",
                    config.seed + index,
                )
                for index, (member, _) in enumerate(
                    zip(planned_roles, specialist_roles))
            ]
            ballots = list(pool.map(
                lambda item: make_ballot(*item),
                items,
            ))

        initial_rule = "v0" if config.vote_rule == "v3" else config.vote_rule
        vote_result = aggregate_ballots(
            case_id=visible.id,
            ballots=ballots,
            labels=labels,
            planned_roles=planned_roles,
            pool=config.vote_pool,
            rule=initial_rule,
            role_weights=config.vote_role_weights,
            calibration=config.vote_calibration,
            tie_seed=config.vote_tie_seed,
            min_share=config.vote_arbitration_min_share,
            min_margin=config.vote_arbitration_margin,
        )

        arbitration = VoteArbitration(
            triggered=False,
            status="not_triggered",
            initial_label=vote_result.label,
            final_label=vote_result.label,
        )
        if (config.vote_rule == "v3"
                and vote_result.completion_status != "failed"
                and arbitration_required(
                    vote_result,
                    config.vote_arbitration_min_share,
                    config.vote_arbitration_margin)):
            arbitration = self._adjudicate(
                visible,
                labels,
                ballots,
                evidence,
                evidence_index,
                config,
                vote_result.label,
                usage,
                trace,
                ledger,
                on_event,
            )
        vote_result = aggregate_ballots(
            case_id=visible.id,
            ballots=ballots,
            labels=labels,
            planned_roles=planned_roles,
            pool=config.vote_pool,
            rule=config.vote_rule,
            role_weights=config.vote_role_weights,
            calibration=config.vote_calibration,
            tie_seed=config.vote_tie_seed,
            arbitration=arbitration,
            min_share=config.vote_arbitration_min_share,
            min_margin=config.vote_arbitration_margin,
        )
        emit("vote_aggregated", vote=vote_result.model_dump(mode="json"))

        decision = build_vote_decision(
            visible, config, vote_result, ballots, evidence_index)
        status = "failed" if decision is None else "completed"
        if decision is not None:
            emit(
                "agent_reported",
                "decision",
                output=decision.model_dump(mode="json"),
                aggregate_rule=config.vote_rule,
            )
        if self.provider.input_price is not None and self.provider.output_price is not None:
            usage.cost_usd = (
                usage.input_tokens * self.provider.input_price
                + usage.output_tokens * self.provider.output_price
            ) / 1_000_000
        emit(
            "run_completed",
            status=status,
            completion_status=vote_result.completion_status,
            vote=vote_result.model_dump(mode="json"),
        )
        return RunResult(
            case_id=case.id,
            patient_id=case.patient_id,
            status=status,
            provider=self.provider.name,
            model=self.provider.model,
            simulated=self.provider.simulated,
            fingerprint=fingerprint,
            config=config,
            decision=decision,
            reports=reports,
            usage=usage,
            trace=trace,
            visible_document_ids=[document.id for document in documents],
            duration_seconds=round(time.monotonic() - started, 6),
            ballots=ballots,
            vote_result=vote_result,
        )

    def _adjudicate(
        self,
        case: CaseInput,
        labels: list[str],
        ballots: list[Ballot],
        evidence: list[dict],
        evidence_index: dict,
        config: RunConfig,
        initial_label: str | None,
        usage: Usage,
        trace: list[TraceEvent],
        ledger: threading.RLock,
        on_event: Callable[[TraceEvent], None] | None,
    ) -> VoteArbitration:
        def emit(kind: str, role: str = "", **details):
            with ledger:
                event = TraceEvent(sequence=len(trace), kind=kind, role=role, details=details)
                trace.append(event)
                if on_event:
                    on_event(event)

        payload = {
            "role": "verifier",
            "task": case.task,
            "question": case.question,
            "verification_labels": labels if case.task == "verification" else [],
            "options": case.options,
            "entities": case.entities.model_dump(),
            "evidence": evidence,
            "evidence_ids": [entry["evidence_id"] for entry in evidence],
            "initial_label": initial_label,
            "multiclass_votes": [
                {
                    "member": f"member-{index:02d}",
                    "status": ballot.status,
                    "label": ballot.label,
                    "brief_reason": ballot.brief_reason,
                    "findings": [
                        {
                            "statement": finding.statement,
                            "stance": finding.stance,
                        }
                        for finding in ballot.findings
                    ],
                }
                for index, ballot in enumerate(ballots, 1)
                if ballot.status != "failed"
            ],
        }
        adjudication_schema = VoteAdjudicationOutput.model_json_schema()
        adjudication_schema["properties"]["label"]["enum"] = labels
        system = (
            "You are the single bounded semantic arbiter for a low-consensus evidence "
            "vote. Role names and self-reported confidence have been removed. Decide the "
            "same task answer from the original question and complete visible evidence. "
            "Use the supplied ballot reasons only as hypotheses to check. A missing local "
            "modality is not global NEI. Do not invent outside evidence. Return JSON only "
            "conforming to this schema: " + json.dumps(
                adjudication_schema, ensure_ascii=False)
        )
        if case.task == "verification":
            system += " Legal labels are " + ", ".join(labels) + "."
        else:
            system += " The label must be an option key from " + ", ".join(case.options) + "."
        emit("vote_arbitration_started", "verifier", initial_label=initial_label)

        arbitration = VoteArbitration(
            triggered=True,
            status="failed",
            initial_label=initial_label,
            final_label=initial_label,
        )
        repair = None
        try:
            for attempt in range(config.schema_retries + 1):
                current_payload = dict(payload)
                current_system = system
                if repair is not None:
                    current_payload["repair"] = repair
                    current_system += (
                        " The previous response failed validation. Return a complete corrected JSON "
                        "object. Validation errors: "
                        + "; ".join(error.get("msg", "") for error in repair["validation_errors"]))
                with ledger:
                    reservation = (
                        len((current_system + json.dumps(
                            current_payload, ensure_ascii=False)).encode())
                        + config.max_output_tokens)
                    if usage.calls >= config.max_calls:
                        raise BudgetExceeded("model-call budget exhausted")
                    if (usage.input_tokens + usage.output_tokens + reservation
                            > config.max_total_tokens):
                        raise BudgetExceeded("token preflight budget exhausted")
                    usage.calls += 1
                emit(
                    "agent_started",
                    "verifier",
                    executor="vote-arbiter",
                    payload_sha256=hashlib.sha256(
                        json.dumps(current_payload, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest(),
                    evidence_ids=[entry["evidence_id"] for entry in evidence],
                    token_reservation=reservation,
                )
                call_started = time.monotonic()
                try:
                    reply = self.provider.complete(
                        current_system,
                        current_payload,
                        config.max_output_tokens,
                        config.temperature,
                        config.seed + attempt,
                    )
                except ProviderError as exc:
                    if exc.observed_reply is not None:
                        observed = exc.observed_reply
                        with ledger:
                            usage.input_tokens += observed.input_tokens
                            usage.output_tokens += observed.output_tokens
                            usage.http_attempts += observed.attempts
                            usage.estimated_tokens |= observed.estimated
                        emit(
                            "model_usage",
                            "verifier",
                            input_tokens=observed.input_tokens,
                            output_tokens=observed.output_tokens,
                            attempts=observed.attempts,
                            estimated=observed.estimated,
                            seconds=round(time.monotonic() - call_started, 3),
                            evidence_fragments=len(evidence),
                        )
                    raise
                with ledger:
                    usage.input_tokens += reply.input_tokens
                    usage.output_tokens += reply.output_tokens
                    usage.http_attempts += reply.attempts
                    usage.estimated_tokens |= reply.estimated
                emit(
                    "model_usage",
                    "verifier",
                    input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens,
                    attempts=reply.attempts,
                    estimated=reply.estimated,
                    seconds=round(time.monotonic() - call_started, 3),
                    evidence_fragments=len(evidence),
                )
                try:
                    wire = VoteAdjudicationOutput.model_validate_json(reply.content)
                    if wire.label not in labels:
                        raise ValueError("arbiter label outside the current task vocabulary")
                    unknown = sorted({
                        citation.evidence_id for citation in wire.evidence_ids
                    } - set(evidence_index))
                    if unknown:
                        raise ValueError(
                            "arbiter cites evidence ids not visible to it: "
                            + ", ".join(unknown))
                    if wire.label != "NEI" and not wire.evidence_ids:
                        raise ValueError("non-NEI arbitration requires visible evidence")
                    arbitration = VoteArbitration(
                        triggered=True,
                        status="completed",
                        initial_label=initial_label,
                        final_label=wire.label,
                        explanation=wire.explanation,
                        evidence_ids=list(dict.fromkeys(
                            citation.evidence_id for citation in wire.evidence_ids)),
                        unresolved=wire.unresolved,
                    )
                    emit(
                        "vote_arbitration_completed",
                        "verifier",
                        **arbitration.model_dump(mode="json"),
                    )
                    return arbitration
                except (ValueError, TypeError) as exc:
                    repair = {
                        "previous_output": reply.content[:65536],
                        "validation_errors": [{"msg": str(exc)}],
                        "valid_evidence_ids": sorted(evidence_index),
                        "legal_labels": labels,
                    }
                    emit(
                        "vote_invalid_output",
                        "verifier",
                        error_type=type(exc).__name__,
                        **repair,
                    )
                    if attempt >= config.schema_retries:
                        raise ProviderError(
                            "vote arbitration failed schema or source-integrity validation") from exc
                    emit("vote_repair_requested", "verifier", attempt=attempt + 1)
        except (ProviderError, BudgetExceeded) as exc:
            arbitration.error = str(exc)
            emit("vote_arbitration_failed", "verifier", reason=str(exc))
            return arbitration
        raise AssertionError("arbitration loop must return")
