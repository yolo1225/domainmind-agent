from app.agents.legacy_contracts import AgentName


AGENT_TOOL_WHITELIST: dict[AgentName, set[str]] = {
    "orchestrator_agent": {"task_state", "checkpoint", "manual_review"},
    "profile_analysis_agent": {"diagnostic_aggregate", "knowledge_relations", "profile_evidence"},
    "knowledge_retrieval_agent": {"chroma_search", "knowledge_relations"},
    "content_generation_agent": {"resource_template", "citation_precheck"},
    "review_validation_agent": {"primary_review", "secondary_review", "citation_verify"},
    "tutoring_agent": {"session_messages", "intent_classify", "hint_ladder"},
}


def ensure_tool_allowed(agent_name: AgentName, tool_name: str) -> None:
    if tool_name not in AGENT_TOOL_WHITELIST[agent_name]:
        raise PermissionError(f"{agent_name} is not allowed to use tool {tool_name}")
