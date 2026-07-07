from typing import Any, TypedDict


class AgentGraphState(TypedDict, total=False):
    contract_version: str
    task_id: str
    session_id: str
    learner_id: str
    profile_id: str
    profile_mode: str
    domain_code: str
    resource_types: list[str]
    learning_goal: str
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
