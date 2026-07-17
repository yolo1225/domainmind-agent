from typing import Literal, TypedDict

from app.agents.contracts import (
    AnalyzeProfileOutput,
    DiagnosticSummary,
    FeedbackContext,
    FinalizeTaskOutput,
    GenerateResourceOutput,
    HumanReviewOutput,
    InterpretFeedbackOutput,
    PrepareTaskOutput,
    ProfileSnapshot,
    RetrieveKnowledgeOutput,
    ReviewResourceOutput,
    RevisionPlan,
    TaskRequest,
)


class AgentGraphState(TypedDict, total=False):
    """Frozen V2 state shape for all new agent implementations."""

    contract_version: Literal["agent-contract-v2"]
    task_request: TaskRequest
    current_profile: ProfileSnapshot
    diagnostic_summary: DiagnosticSummary
    feedback_context: FeedbackContext
    revision_plan: RevisionPlan
    prepare_task: PrepareTaskOutput
    interpret_feedback: InterpretFeedbackOutput
    analyze_profile: AnalyzeProfileOutput
    retrieve_knowledge: RetrieveKnowledgeOutput
    generate_resource: GenerateResourceOutput
    review_resource: ReviewResourceOutput
    finalize_task: FinalizeTaskOutput
    human_review: HumanReviewOutput
    error_code: str
    error_summary: str
