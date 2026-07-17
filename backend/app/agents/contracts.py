from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.compatibility import AGENT_CONTRACT_VERSION

AgentName = Literal[
    "orchestrator_agent",
    "profile_analysis_agent",
    "knowledge_retrieval_agent",
    "content_generation_agent",
    "review_validation_agent",
    "tutoring_agent",
]

MessageType = Literal[
    "command",
    "observation",
    "result",
    "review",
    "decision",
    "feedback",
    "error",
]


class AgentMessage(BaseModel):
    contract_version: str = AGENT_CONTRACT_VERSION
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    sender: AgentName | str
    receiver: AgentName | str
    message_type: MessageType
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str
    task_id: str | None = None


class AgentRunSummary(BaseModel):
    agent_name: AgentName
    status: str
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    llm_calls: int = 0
    tokens_used: int = 0
    duration_ms: int = 0
    error_message: str | None = None


class RetrievalOutput(BaseModel):
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class GenerationOutput(BaseModel):
    generation_context: dict[str, Any] = Field(default_factory=dict)
    draft_resources: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class GeneratedSourceRef(BaseModel):
    knowledge_id: str
    name: str = ""
    source_title: str = ""
    matched_plan: str = "semantic"
    used_for: str | None = None


class GeneratedResourceDraft(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    sources: list[GeneratedSourceRef] = Field(default_factory=list)


class ReviewOutput(BaseModel):
    review_reports: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class DecisionOutput(BaseModel):
    decision: str
    revision_count: int = 0
    revision_plan: dict[str, Any] = Field(default_factory=dict)
    passed_resources: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class ProfileAnalysisOutput(BaseModel):
    profile_id: str | None = None
    profile_update_required: bool = False
    changed_dimensions: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0
    decision_reason: str = ""
    affected_knowledge_ids: list[str] = Field(default_factory=list)
    affected_path_node_ids: list[str] = Field(default_factory=list)
    affected_resource_ids: list[str] = Field(default_factory=list)


class TutoringOutput(BaseModel):
    feedback_intent: str
    recommended_action: str
    reply: str
    profile_update_required: bool = False
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    decision_reason: str


class FactCheck(BaseModel):
    claim: str
    supported: bool | None = None
    source_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    determinable: bool = True


class ModelReview(BaseModel):
    model_role: str = ""
    factual_score: float
    source_trace_score: float
    difficulty_match_score: float
    coverage_score: float
    passed: bool
    issues: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    fact_checks: list[FactCheck] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    verified_claim_count: int = Field(default=0, ge=0)
    source_coverage: float = Field(default=0, ge=0, le=100)
    unable_to_determine: list[str] = Field(default_factory=list)
    provider_mode: str = "live"


class ManualReviewDecision(BaseModel):
    decision: Literal["approve", "request_revision", "reject"]
    review_comment: str = Field(min_length=1, max_length=2000)
