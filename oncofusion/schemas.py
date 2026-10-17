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


class RunConfig(StrictModel):
    mode: Literal["multi", "fixed_five", "single_direct", "single_tools", "single_iterative"] = "multi"
    ablations: Ablations = Field(default_factory=Ablations)
    delegated_roles: list[Role] = Field(default_factory=list, max_length=7)
    routing: Literal["fixed", "adaptive"] = "fixed"
    max_calls: int = Field(default=12, ge=1, le=50)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    max_total_tokens: int = Field(default=120_000, ge=100, le=2_000_000)
    max_output_tokens: int = Field(default=1500, ge=64, le=8000)
    schema_retries: int = Field(default=0, ge=0, le=2)
    top_k: int = Field(default=6, ge=1, le=30)
    candidate_k: int = Field(default=20, ge=1, le=100)
    seed: int = Field(default=0, ge=0)
    temperature: float = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def valid_config(self):
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be at least top_k")
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


class AnalysisOutput(StrictModel):
    findings: list[Finding] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    requery: str = Field(default="", max_length=1000)


class DecisionOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)
    explanation: str = Field(min_length=1, max_length=8000)
    citations: list[Citation] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)


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


class TraceEvent(StrictModel):
    sequence: int
    kind: str
    role: str
    details: dict = Field(default_factory=dict)


class RunResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    patient_id: str
    status: Literal["completed", "budget_exhausted"]
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
