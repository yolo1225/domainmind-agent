from typing import Any

from app.agents.generation_agent import ContentGenerationAgent, GENERATION_AGENT_NAME
from app.agents.orchestrator import ORCHESTRATOR_AGENT_NAME, OrchestratorAgent
from app.agents.profile_agent import PROFILE_AGENT_NAME, ProfileAnalysisAgent
from app.agents.retrieval_agent import KnowledgeRetrievalAgent, RETRIEVAL_AGENT_NAME
from app.agents.review_agent import REVIEW_AGENT_NAME, ReviewValidationAgent
from app.agents.state import AgentGraphState
from app.core.compatibility import AGENT_CONTRACT_VERSION


def append_trace(state: AgentGraphState, agent_name: str, status: str, output: dict) -> None:
    state.setdefault("agent_trace", [])
    state["agent_trace"].append(
        {
            "agent_name": agent_name,
            "status": status,
            "output": output,
        }
    )


def _apply_profile_payload(state: AgentGraphState, payload: dict[str, Any]) -> None:
    state["profile_id"] = payload.get("profile_id") or state.get("profile_id", "")
    state["profile_result"] = payload
    state["profile"] = {
        **(payload.get("ability_profile") or {}),
        "profile_id": payload.get("profile_id"),
        "profile_type": payload.get("profile_type", "beginner"),
        "weak_knowledge": payload.get("weak_knowledge", []),
        "learning_path_id": payload.get("learning_path_id"),
    }


def _unique_non_empty(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _weakness_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    evidence = item.get("evidence") or {}
    return (
        -int(item.get("weakness_level") or 0),
        -int(evidence.get("wrong_count") or 0),
        str(item.get("name") or ""),
    )


def _target_difficulty(profile_type: str) -> int:
    if profile_type == "advanced":
        return 4
    if profile_type in {"intermediate", "practice_oriented"}:
        return 3
    return 2


def _retrieval_strategy(profile_type: str, weak_items: list[dict[str, Any]]) -> str:
    if weak_items:
        max_weakness_level = max(int(item.get("weakness_level") or 0) for item in weak_items)
        if profile_type == "beginner" or max_weakness_level >= 4:
            return "remedial"
        return "consolidation"
    if profile_type == "advanced":
        return "challenge"
    return "consolidation"


def build_retrieval_plan(payload: dict[str, Any], learning_goal: str) -> dict[str, Any]:
    profile_type = payload.get("profile_type") or "beginner"
    weak_items = sorted(
        [item for item in payload.get("weak_knowledge", []) if isinstance(item, dict)],
        key=_weakness_sort_key,
    )
    strategy = _retrieval_strategy(profile_type, weak_items)
    priority_knowledge_ids = _unique_non_empty(
        [item.get("knowledge_id") for item in weak_items[:8]]
    )
    prerequisite_knowledge_ids = _unique_non_empty(
        [
            prerequisite
            for item in weak_items
            for prerequisite in (item.get("prerequisites") or [])
        ]
    )
    weakness_summary = [
        {
            "knowledge_id": item.get("knowledge_id"),
            "name": item.get("name"),
            "category": item.get("category"),
            "weakness_level": item.get("weakness_level"),
            "weakness_type": item.get("weakness_type"),
            "suggested_action": item.get("suggested_action"),
        }
        for item in weak_items[:8]
    ]
    strategy_terms = {
        "remedial": "补救讲解",
        "consolidation": "巩固练习",
        "challenge": "挑战任务",
    }
    query_terms = _unique_non_empty(
        [
            learning_goal,
            strategy_terms[strategy],
            *[
                part
                for item in weak_items[:8]
                for part in (item.get("name"), item.get("category"), item.get("knowledge_id"))
            ],
            *prerequisite_knowledge_ids,
        ]
    )
    return {
        "profile_id": payload.get("profile_id"),
        "profile_type": profile_type,
        "strategy": strategy,
        "target_difficulty": _target_difficulty(profile_type),
        "priority_knowledge_ids": priority_knowledge_ids,
        "prerequisite_knowledge_ids": prerequisite_knowledge_ids,
        "query_terms": query_terms,
        "weakness_summary": weakness_summary,
        "n_results": 8 if strategy == "remedial" else 5,
    }


def load_profile(state: AgentGraphState) -> AgentGraphState:
    state["contract_version"] = AGENT_CONTRACT_VERSION
    payload = ProfileAnalysisAgent().execute(state)
    _apply_profile_payload(state, payload)
    retrieval_plan = build_retrieval_plan(payload, state.get("learning_goal", ""))
    state["retrieval_plan"] = retrieval_plan
    append_trace(
        state,
        PROFILE_AGENT_NAME,
        "completed",
        {
            "profile_id": payload.get("profile_id"),
            "profile_type": payload.get("profile_type", "beginner"),
            "learning_path_id": payload.get("learning_path_id"),
            "profile_source": payload.get("profile_source"),
            "weak_knowledge_count": len(payload.get("weak_knowledge", [])),
            "strategy": retrieval_plan["strategy"],
            "target_difficulty": retrieval_plan["target_difficulty"],
            "priority_knowledge_count": len(retrieval_plan["priority_knowledge_ids"]),
            "prerequisite_count": len(retrieval_plan["prerequisite_knowledge_ids"]),
        },
    )
    return state


def retrieve_knowledge(state: AgentGraphState) -> AgentGraphState:
    output = KnowledgeRetrievalAgent().execute(state)
    state["retrieved_chunks"] = output["retrieved_chunks"]
    append_trace(state, RETRIEVAL_AGENT_NAME, "completed", output["trace"])
    return state


def generate_resource(state: AgentGraphState) -> AgentGraphState:
    output = ContentGenerationAgent().execute(state)
    state["generation_context"] = output["generation_context"]
    state["draft_resources"] = output["draft_resources"]
    append_trace(state, GENERATION_AGENT_NAME, "completed", output["trace"])
    return state


def review_resource(state: AgentGraphState) -> AgentGraphState:
    output = ReviewValidationAgent().execute(state)
    state["review_reports"] = output["review_reports"]
    append_trace(state, REVIEW_AGENT_NAME, "completed", output["trace"])
    return state


def decide_next_step(state: AgentGraphState) -> AgentGraphState:
    output = OrchestratorAgent().decide(state)
    state["decision"] = output["decision"]
    state["revision_count"] = output["revision_count"]
    state["revision_plan"] = output["revision_plan"]
    state["passed_resources"] = output["passed_resources"]
    append_trace(state, ORCHESTRATOR_AGENT_NAME, "completed", output["trace"])
    return state


def persist_resource(state: AgentGraphState) -> AgentGraphState:
    output = OrchestratorAgent().persist_summary(state)
    append_trace(state, ORCHESTRATOR_AGENT_NAME, "completed", output)
    return state


def route_after_decision(state: AgentGraphState) -> str:
    if state["decision"] == "passed":
        return "persist_resource"
    if state["decision"] == "revision_required" and state["revision_count"] <= 2:
        return "retrieve_knowledge"
    return "end"
