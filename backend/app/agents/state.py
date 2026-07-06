from typing import Any, TypedDict


class AgentGraphState(TypedDict, total=False):
    contract_version: str
    task_id: str
    learner_id: str
    profile_id: str
    domain_code: str
    resource_types: list[str]
    learning_goal: str
    profile: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]
    draft_resources: list[dict[str, Any]]
    review_reports: list[dict[str, Any]]
    agent_trace: list[dict[str, Any]]
    revision_count: int
    decision: str
    error_message: str | None
