from typing import Any, TypedDict


class AgentGraphState(TypedDict, total=False):
    contract_version: str
    task_id: str
    trigger_type: str
    execution_mode: str
    resume_node: str | None
    session_id: str
    learner_id: str
    profile_id: str
    profile_mode: str
    domain_code: str
    resource_types: list[str]
    learning_goal: str
    resource_id: str | None
    feedback_id: str | None
    tutoring_session_id: str | None
    tutoring_message_id: str | None
    feedback_intent: str | None
    recommended_action: str | None
    profile_update_required: bool
    profile_change_evidence: list[dict[str, Any]]
    affected_knowledge_ids: list[str]
    affected_path_node_ids: list[str]
    affected_resource_ids: list[str]
    manual_review_required: bool
    manual_review_task_id: str | None
    human_review_decision: str | None
    decision_reason: str
    agent_contexts: dict[str, dict[str, Any]]
    answers: list[dict[str, Any]]
    question_ids: list[str]
    answer_by_question_id: dict[str, Any]
    profile: dict[str, Any]
    profile_result: dict[str, Any]
    retrieval_plan: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]
    generation_context: dict[str, Any]
    draft_resources: list[dict[str, Any]]
    review_reports: list[dict[str, Any]]
    revision_plan: dict[str, Any]
    passed_resources: list[dict[str, Any]]
    agent_trace: list[dict[str, Any]]
    revision_count: int
    decision: str
    error_message: str | None
    db_session: Any
