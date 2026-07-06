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
