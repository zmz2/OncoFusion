"""Versioned boundaries. Gold labels never belong to CaseInput or model payloads."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Label = Literal["SUPPORTS", "REFUTES", "REVISIONS", "NEI"]
VerificationScheme = Literal["refutes", "revisions"]
VERIFICATION_LABELS = {
    "refutes": ("SUPPORTS", "REFUTES", "NEI"),
    "revisions": ("SUPPORTS", "REVISIONS", "NEI"),
}
Role = Literal["timeline", "genomics", "pathology", "drug", "literature", "verifier", "decision"]
ROLES = ("timeline", "genomics", "pathology", "drug", "literature", "verifier", "decision")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Entities(StrictModel):
    gene: str = Field(default="", max_length=120)
    variant: str = Field(default="", max_length=240)
    disease: str = Field(default="", max_length=240)
    drug: str = Field(default="", max_length=240)


class Document(StrictModel):
    id: Identifier
    origin_id: Identifier
    kind: Literal["genomics", "pathology", "therapy", "literature", "clinical"]
    text: str = Field(min_length=1, max_length=100_000)
    title: str = Field(default="", max_length=500)
    entities: Entities = Field(default_factory=Entities)
    available_stage: int = Field(default=0, ge=0)
    event_day: int | None = None
    url: str = Field(default="", max_length=2000)
    license: str = Field(default="", max_length=500)


class CaseInput(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    patient_id: Identifier
    task: Literal["verification", "mcq", "synthesis"]
    question: str = Field(min_length=1, max_length=20_000)
    verification_scheme: VerificationScheme = "refutes"
    options: dict[str, str] = Field(default_factory=dict, max_length=30)
    entities: Entities = Field(default_factory=Entities)
    stage: int = Field(default=0, ge=0)
    as_of_day: int | None = None
    documents: list[Document] = Field(default_factory=list, max_length=500)
    data_class: Literal["synthetic", "deidentified", "unreviewed"] = "unreviewed"

    @property
    def verification_labels(self) -> tuple[str, ...]:
        return VERIFICATION_LABELS[self.verification_scheme]

    @model_validator(mode="after")
    def consistent(self):
        if not self.question.strip():
            raise ValueError("question must contain visible text")
        ids = [d.id for d in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document IDs must be unique within a case")
        if self.task == "mcq" and len(self.options) < 2:
            raise ValueError("mcq requires at least two options")
        if self.task != "mcq" and self.options:
            raise ValueError("options are only valid for mcq")
        if any(not k.strip() or not v.strip() or len(v) > 10_000 for k, v in self.options.items()):
            raise ValueError("invalid option key or text")
        if sum(len(d.text.encode()) for d in self.documents) > 1_000_000:
            raise ValueError("case source text exceeds 1 MB")
        return self


class Ablations(StrictModel):
    variant_normalization: bool = True
    disease_matching: bool = True
    drug_polarity: bool = True
    retrieval_reranking: bool = True
    timeline_structure: bool = True
    external_verification: bool = True
    source_deduplication: bool = True
    structured_board: bool = True
    targeted_requery: bool = True


ROUTE_SPECIALIST_ROLES = ("literature", "timeline", "genomics", "pathology", "drug")


class VoteCalibration(StrictModel):
    """Pooled Platt calibration for a member's self-reported confidence."""
    platt_a: float = 1.0
    platt_b: float = 0.0
    epsilon: float = Field(default=1e-6, gt=0, lt=.5)


class RunConfig(StrictModel):
    mode: Literal["multi", "fixed_five", "single_direct", "single_tools", "single_iterative"] = "multi"
    execution_model: Literal["engine", "route", "vote"] = "engine"
    route: str = ""
    route_rounds: int = Field(default=2, ge=1, le=2)
    route_workers: int = Field(default=13, ge=1, le=20)
    ablations: Ablations = Field(default_factory=Ablations)
    delegated_roles: list[Role] = Field(default_factory=list, max_length=7)
    routing: Literal["fixed", "adaptive"] = "fixed"
    workflow_backend: Literal["native", "langgraph"] = "native"
    evidence_first: bool = False
    specialist_contracts: bool = False
    latest_role_board: bool = False
    max_calls: int = Field(default=12, ge=1, le=50)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    max_total_tokens: int = Field(default=120_000, ge=100, le=2_000_000)
    max_output_tokens: int = Field(default=1500, ge=64, le=8000)
    # Review and specialist nodes return compact JSON. Giving them the answer-sized
    # ceiling makes verbose reviewers fill it and hit provider truncation.
    route_node_output_tokens: int = Field(default=1500, ge=64, le=8000)
    citation_mode: Literal["quote", "fragment"] = "quote"
    fragment_chars: int = Field(default=600, ge=120, le=4000)
    max_fragments_per_document: int = Field(default=8, ge=1, le=50)
    # Characters of fragment text a single stage may receive; the planner spends this on the
    # question-selected spans, so a long record no longer gets cut off the tail of a document.
    fragment_budget: int = Field(default=24_000, ge=2_000, le=400_000)
    findings_limit: int = Field(default=5, ge=1, le=30)
    # claims-v1 adds claim ids, per-claim verifier verdicts and decision adoption/exclusion.
    # "legacy" keeps the byte-identical protocol behind every result recorded before 2026-10-19.
    interaction_protocol: Literal["legacy", "claims-v1", "vote-v1"] = "legacy"
    schema_retries: int = Field(default=0, ge=0, le=2)
    top_k: int = Field(default=6, ge=1, le=30)
    candidate_k: int = Field(default=20, ge=1, le=100)
    seed: int = Field(default=0, ge=0)
    temperature: float = Field(default=0, ge=0, le=2)
    # Verification-only mechanism. It stays outside the legacy ablation namespace,
    # so historical presets and the old 41-treatment plan remain unchanged.
    claim_revision_gate: bool = False
    # vote-v1 is a separate execution path. Its ballots can be aggregated offline under
    # several rules without regenerating model outputs.
    vote_pool: Literal["specialist", "generalist"] = "specialist"
    vote_rule: Literal["v0", "v1", "v2", "v3"] = "v0"
    vote_members: int = Field(default=5, ge=1, le=8)
    vote_workers: int = Field(default=5, ge=1, le=20)
    vote_role_weights: dict[str, float] = Field(default_factory=dict)
    vote_calibration: VoteCalibration | None = None
    vote_tie_seed: int = Field(default=0, ge=0)
    vote_arbitration_min_share: float = Field(default=.75, gt=0, le=1)
    vote_arbitration_margin: float = Field(default=.25, ge=0, le=1)

    @model_validator(mode="after")
    def valid_config(self):
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be at least top_k")
        if self.execution_model == "route" and not self.route:
            raise ValueError("route execution requires a route name")
        if self.execution_model != "route" and self.route:
            raise ValueError("only route execution can name a route")
        if self.execution_model == "vote" and self.interaction_protocol != "vote-v1":
            raise ValueError("vote execution requires interaction_protocol=vote-v1")
        if self.execution_model != "vote" and self.interaction_protocol == "vote-v1":
            raise ValueError("vote-v1 protocol requires vote execution")
        if self.vote_rule == "v1" and not self.vote_role_weights:
            raise ValueError("v1 voting requires calibrated role weights")
        if self.vote_rule == "v2" and self.vote_calibration is None:
            raise ValueError("v2 voting requires a confidence calibrator")
        if any(weight <= 0 for weight in self.vote_role_weights.values()):
            raise ValueError("vote role weights must be positive")
        if len(self.delegated_roles) != len(set(self.delegated_roles)):
            raise ValueError("delegated_roles must be unique")
        return self


class Citation(StrictModel):
    document_id: Identifier
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)
    quote: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def ordered(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("provide both offsets or omit both")
        if self.start is not None and self.end <= self.start:
            raise ValueError("citation end must exceed start")
        return self


class Finding(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    relation: Label = "NEI"
    citations: list[Citation] = Field(default_factory=list, max_length=30)
    # Assigned by the engine, never by the model, so a claim id means the same thing in every run
    # record. Empty on results written before the claims-v1 protocol existed.
    claim_id: str = ""
    author_role: str = ""
    used_claim_ids: list[str] = Field(default_factory=list, max_length=30)
    scope: str = ""
    evidence_level: str = ""
    material_status: str = ""
    # Assigned by the server, never by the model: for a claim that reports missing material this
    # says whether the visible record carries no such modality at all ("not_recorded") or the
    # stage's selected spans simply did not cover it ("selection_not_covered").
    material_basis: str = ""


class ClaimVerdict(StrictModel):
    """One claim's review result, with the source spans that carry it.

    Every role may review earlier claims, so the reviewing role is recorded by the server: a list of
    verdicts says which roles gave feedback, not how often the verifier ran.
    """
    target_claim_id: Identifier
    verdict: Literal["confirmed", "corrected", "rejected", "insufficient"]
    note: str = Field(default="", max_length=2000)
    citations: list[Citation] = Field(default_factory=list, max_length=30)
    reviewer_role: str = ""


class AnalysisOutput(StrictModel):
    findings: list[Finding] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    requery: str = Field(default="", max_length=1000)
    verdicts: list[ClaimVerdict] = Field(default_factory=list, max_length=60)


class DecisionOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)
    explanation: str = Field(min_length=1, max_length=8000)
    citations: list[Citation] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    adopted_claim_ids: list[str] = Field(default_factory=list, max_length=60)
    rejected_claim_ids: list[str] = Field(default_factory=list, max_length=60)


class FragmentCitation(StrictModel):
    evidence_id: Identifier


class FragmentFinding(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    relation: Label = "NEI"
    citations: list[FragmentCitation] = Field(default_factory=list, max_length=30)
    used_claim_ids: list[Identifier] = Field(default_factory=list, max_length=30)


class FragmentAnalysisOutput(StrictModel):
    findings: list[FragmentFinding] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    requery: str = Field(default="", max_length=1000)


class VoteFindingOutput(StrictModel):
    statement: str = Field(min_length=1, max_length=1500)
    stance: Literal["supports", "contradicts", "unmentioned"]
    evidence_ids: list[FragmentCitation] = Field(default_factory=list, max_length=4)


class VoteBallotOutput(StrictModel):
    status: Literal["vote", "abstain"]
    label: str | None = Field(default=None, max_length=120)
    confidence: float | None = Field(default=None, ge=0, le=1)
    brief_reason: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[FragmentCitation] = Field(default_factory=list, max_length=4)
    findings: list[VoteFindingOutput] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def ballot_fields(self):
        if self.status == "vote":
            if not self.label:
                raise ValueError("a vote requires a label")
            if self.confidence is None:
                raise ValueError("a vote requires confidence")
        elif self.label is not None:
            raise ValueError("an abstention must not carry a vote label")
        if any(not finding.evidence_ids for finding in self.findings):
            raise ValueError("each local finding requires at least one evidence id")
        return self


class VoteAdjudicationOutput(StrictModel):
    label: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=3000)
    evidence_ids: list[FragmentCitation] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=10)


class FragmentDecisionOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)
    explanation: str = Field(min_length=1, max_length=8000)
    citations: list[FragmentCitation] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    adopted_claim_ids: list[Identifier] = Field(default_factory=list, max_length=60)
    rejected_claim_ids: list[Identifier] = Field(default_factory=list, max_length=60)


class RevisionAssessment(StrictModel):
    """Global stance assessment, kept separate from each professional claim's local relation."""
    evidence_relevance: Literal["relevant", "irrelevant", "insufficient"]
    claim_conformance: Literal["as_written", "requires_revision", "no_supported_revision", "unclear"]
    revision_fields: list[Literal["disease", "evidenceDirection", "evidenceType", "molecularProfile",
                                  "significance", "therapies", "variantOrigin"]] = Field(
        default_factory=list, max_length=7)
    minimal_revision: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def revision_fields_match_conformance(self):
        revision_text = self.minimal_revision.strip()
        if self.claim_conformance == "requires_revision" and not self.revision_fields:
            raise ValueError("requires_revision must name at least one claim field")
        if self.claim_conformance == "requires_revision" and not revision_text:
            raise ValueError("requires_revision must provide a minimal revision")
        if self.claim_conformance != "requires_revision" and (self.revision_fields or revision_text):
            raise ValueError(
                "revision fields and minimal revision require claim_conformance=requires_revision")
        return self


class RevisionDecisionOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)
    explanation: str = Field(min_length=1, max_length=8000)
    citations: list[FragmentCitation] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    adopted_claim_ids: list[Identifier] = Field(default_factory=list, max_length=60)
    rejected_claim_ids: list[Identifier] = Field(default_factory=list, max_length=60)
    assessment: RevisionAssessment


# claims-v1 findings declare which layer they speak from, so a genomics role cannot answer the
# survival question and a drug role cannot hide that the patient was never exposed to the drug.
CLAIM_SCOPE = Literal["temporal", "molecular", "pathologic", "exposure", "relationship", "source",
                      "verification", "outcome_prediction"]
EVIDENCE_LEVEL = Literal["measured", "curated", "literature", "inferred", "absent"]
MATERIAL_STATUS = Literal["present", "not_applicable", "unknown"]


class ClaimFinding(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    relation: Label = "NEI"
    citations: list[FragmentCitation] = Field(default_factory=list, max_length=30)
    used_claim_ids: list[Identifier] = Field(default_factory=list, max_length=30)
    scope: CLAIM_SCOPE
    evidence_level: EVIDENCE_LEVEL
    material_status: MATERIAL_STATUS


class ClaimAnalysisOutput(StrictModel):
    findings: list[ClaimFinding] = Field(default_factory=list, max_length=30)
    # A reflection verifier receives no source view and answers in this shape, so the verdict list
    # is allowed to be present and empty here as well.
    verdicts: list[ClaimVerdictEntry] = Field(default_factory=list, max_length=60)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    requery: str = Field(default="", max_length=1000)


class ClaimFindingsOnlyOutput(StrictModel):
    """First claims-v1 role: no earlier claim exists, so no verdict can be valid yet."""
    findings: list[ClaimFinding] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    requery: str = Field(default="", max_length=1000)


class ClaimVerdictEntry(StrictModel):
    target_claim_id: Identifier
    verdict: Literal["confirmed", "corrected", "rejected", "insufficient"]
    note: str = Field(default="", max_length=2000)
    # The model may over-supply supporting spans. The engine resolves every supplied id for
    # source integrity, then keeps the first four in the final verdict ledger.
    citations: list[FragmentCitation] = Field(default_factory=list, max_length=30)


class ClaimVerificationOutput(StrictModel):
    """Verifier output is a verdict ledger, never a second set of specialist claims."""
    verdicts: list[ClaimVerdictEntry] = Field(default_factory=list, max_length=60)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    requery: str = Field(default="", max_length=1000)


class ClaimDecisionOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)
    explanation: str = Field(min_length=1, max_length=8000)
    citations: list[FragmentCitation] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    adopted_claim_ids: list[Identifier] = Field(default_factory=list, max_length=60)
    rejected_claim_ids: list[Identifier] = Field(default_factory=list, max_length=60)


class AgentReport(StrictModel):
    role: Role
    executor: str
    output: AnalysisOutput


class Usage(StrictModel):
    calls: int = 0
    http_attempts: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_tokens: bool = False
    cost_usd: float | None = None


class BallotFinding(StrictModel):
    statement: str
    stance: Literal["supports", "contradicts", "unmentioned"]
    citations: list[Citation] = Field(default_factory=list, max_length=4)


class Ballot(StrictModel):
    ballot_id: Identifier
    case_id: str = ""
    role: str
    model: str = ""
    seed: int = 0
    input_fingerprint: str = ""
    status: Literal["vote", "abstain", "failed"]
    label: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    brief_reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    findings: list[BallotFinding] = Field(default_factory=list, max_length=2)
    usage: Usage = Field(default_factory=Usage)
    duration_seconds: float | None = None
    error: str = ""


class VoteArbitration(StrictModel):
    triggered: bool = False
    status: Literal["not_triggered", "completed", "failed"] = "not_triggered"
    initial_label: str | None = None
    final_label: str | None = None
    explanation: str = ""
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=10)
    error: str = ""


class VoteResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    pool: Literal["specialist", "generalist"]
    rule: Literal["v0", "v1", "v2", "v3", "c_raw"]
    planned_roles: list[str]
    planned_votes: int
    response_votes: int
    valid_votes: int
    abstain_votes: int
    failed_votes: int
    completion_status: Literal["full", "degraded", "failed"]
    label: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    raw_confidence_scores: dict[str, float] | None = None
    calibrated_confidence_scores: dict[str, float] | None = None
    runner_up_label: str | None = None
    top_share: float | None = Field(default=None, ge=0, le=1)
    margin: float | None = Field(default=None, ge=0, le=1)
    tied: bool = False
    tie_broken: bool = False
    arbitration: VoteArbitration = Field(default_factory=VoteArbitration)
    failure_reason: str = ""


class TraceEvent(StrictModel):
    sequence: int
    kind: str
    role: str
    details: dict = Field(default_factory=dict)


class RunResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    patient_id: str
    status: Literal["completed", "budget_exhausted", "failed"]
    provider: str
    model: str
    simulated: bool
    fingerprint: str
    config: RunConfig
    decision: DecisionOutput | None
    reports: list[AgentReport]
    usage: Usage
    trace: list[TraceEvent]
    visible_document_ids: list[str]
    duration_seconds: float
    ballots: list[Ballot] = Field(default_factory=list)
    vote_result: VoteResult | None = None
    research_only: Literal[True] = True


class RunRequest(StrictModel):
    case_id: Identifier | None = None
    example_id: Identifier | None = None
    case: CaseInput | None = None
    config: RunConfig = Field(default_factory=RunConfig)
    allow_remote_processing: bool = False

    @model_validator(mode="after")
    def exactly_one(self):
        if sum(x is not None for x in (self.case_id, self.example_id, self.case)) != 1:
            raise ValueError("provide exactly one of case_id, example_id, case")
        return self
