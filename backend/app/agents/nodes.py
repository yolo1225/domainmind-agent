from typing import Any

from langgraph.types import interrupt

from app.agents.generation_agent import ContentGenerationAgent, GENERATION_AGENT_NAME
from app.agents.orchestrator import ORCHESTRATOR_AGENT_NAME, OrchestratorAgent
from app.agents.profile_agent import PROFILE_AGENT_NAME, ProfileAnalysisAgent
from app.agents.retrieval_agent import KnowledgeRetrievalAgent, RETRIEVAL_AGENT_NAME
from app.agents.review_agent import REVIEW_AGENT_NAME, ReviewValidationAgent
from app.agents.legacy_state import AgentGraphState
from app.agents.tutoring_agent import TutoringAgent
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.rag.embeddings import embed_texts
from app.rag.vector_store import VectorStore


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


def prepare_task(state: AgentGraphState) -> AgentGraphState:
    state["contract_version"] = AGENT_CONTRACT_VERSION
    state.setdefault("trigger_type", "initial_generation")
    state.setdefault("execution_mode", "auto")
    state.setdefault("profile_change_evidence", [])
    state.setdefault("affected_knowledge_ids", [])
    state.setdefault("affected_path_node_ids", [])
    state.setdefault("affected_resource_ids", [])
    state.setdefault("agent_contexts", {})
    state.setdefault("manual_review_required", False)
    state.setdefault("revision_count", 0)
    state.setdefault("decision", "pending")
    append_trace(
        state,
        ORCHESTRATOR_AGENT_NAME,
        "completed",
        {
            "step": "prepare_task",
            "trigger_type": state["trigger_type"],
            "execution_mode": state["execution_mode"],
            "resume_node": state.get("resume_node"),
        },
    )
    return state


def interpret_feedback(state: AgentGraphState) -> AgentGraphState:
    output = TutoringAgent().execute(state)
    state["feedback_intent"] = output["feedback_intent"]
    state["recommended_action"] = output["recommended_action"]
    state["profile_change_evidence"] = [
        *state.get("profile_change_evidence", []),
        *output.get("evidence", []),
    ]
    state["decision_reason"] = output["decision_reason"]
    state.setdefault("agent_contexts", {})["tutoring"] = {
        "reply": output["reply"],
        "feedback_intent": output["feedback_intent"],
    }
    append_trace(
        state,
        "tutoring_agent",
        "completed",
        {"step": "interpret_feedback", **output},
    )
    return state


def _evidence_supports_profile_update(evidence: list[dict[str, Any]]) -> bool:
    scored = [
        item
        for item in evidence
        if item.get("type") in {"scored_quiz", "diagnostic_result", "validated_behavior"}
        and float(item.get("confidence", 0)) >= 0.7
    ]
    confirmed = [item for item in evidence if item.get("confirmed") is True]
    return bool(scored) or len(confirmed) >= 2


def analyze_profile(state: AgentGraphState) -> AgentGraphState:
    if state.get("trigger_type") != "resource_feedback":
        return load_profile(state)

    state.setdefault("affected_knowledge_ids", [])
    state.setdefault("affected_path_node_ids", [])
    state.setdefault("affected_resource_ids", [])

    payload = ProfileAnalysisAgent().execute(state)
    _apply_profile_payload(state, payload)
    retrieval_plan = build_retrieval_plan(payload, state.get("learning_goal", ""))
    if state.get("recommended_action") == "challenge":
        retrieval_plan["strategy"] = "challenge"
        retrieval_plan["target_difficulty"] = min(
            5, int(retrieval_plan.get("target_difficulty", 3)) + 1
        )
    elif state.get("recommended_action") == "explain":
        retrieval_plan["strategy"] = "remedial"
        retrieval_plan["target_difficulty"] = max(
            1, int(retrieval_plan.get("target_difficulty", 2)) - 1
        )
    state["retrieval_plan"] = retrieval_plan
    evidence = state.get("profile_change_evidence", [])
    update_required = _evidence_supports_profile_update(evidence)
    state["profile_update_required"] = update_required
    if update_required:
        knowledge_ids = _unique_non_empty(
            [item.get("knowledge_id") for item in evidence if isinstance(item, dict)]
        )
        state["affected_knowledge_ids"] = knowledge_ids
        state["affected_path_node_ids"] = [f"path:{item}" for item in knowledge_ids]
        state["affected_resource_ids"] = list(state.get("affected_resource_ids", []))
        state["decision_reason"] = "计分或多轮一致证据足以支持画像变化"
    else:
        state["decision_reason"] = state.get("decision_reason") or "证据不足，保留当前画像"

    action = state.get("recommended_action")
    turn_count = int(state.get("tutoring_turn_count") or 1)
    needs_generation = update_required or action in {"challenge", "review", "regenerate"}
    if action == "explain" and turn_count >= 2:
        needs_generation = True
    state["needs_generation"] = needs_generation
    append_trace(
        state,
        PROFILE_AGENT_NAME,
        "completed",
        {
            "step": "analyze_profile",
            "profile_update_required": update_required,
            "decision_reason": state["decision_reason"],
            "affected_knowledge_ids": state["affected_knowledge_ids"],
            "needs_generation": needs_generation,
        },
    )
    return state


def retrieve_knowledge(state: AgentGraphState) -> AgentGraphState:
    import app.agents.retrieval_agent as retrieval_module

    retrieval_module.embed_texts = embed_texts
    retrieval_module.VectorStore = VectorStore
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


def finalize_task(state: AgentGraphState) -> AgentGraphState:
    # A human decision is authoritative.  Do not send an approved/rejected
    # checkpoint back through model arbitration, otherwise the same conflict
    # would immediately reopen the manual-review node.
    if state.get("human_review_decision") == "approve":
        state["decision"] = "completed"
        state["manual_review_required"] = False
        state["passed_resources"] = list(state.get("draft_resources", []))
        append_trace(
            state,
            ORCHESTRATOR_AGENT_NAME,
            "completed",
            {"step": "finalize_task", "decision": "completed", "resolved_by": "human"},
        )
        return state
    if state.get("human_review_decision") == "reject":
        state["decision"] = "rejected"
        state["manual_review_required"] = False
        append_trace(
            state,
            ORCHESTRATOR_AGENT_NAME,
            "completed",
            {"step": "finalize_task", "decision": "rejected", "resolved_by": "human"},
        )
        return state
    if state.get("trigger_type") == "resource_feedback" and not state.get("needs_generation"):
        state["decision"] = "no_change"
        append_trace(
            state,
            ORCHESTRATOR_AGENT_NAME,
            "completed",
            {
                "step": "finalize_task",
                "decision": "no_change",
                "profile_update_required": False,
                "decision_reason": state.get("decision_reason"),
            },
        )
        return state

    output = OrchestratorAgent().decide(state)
    state["decision"] = "completed" if output["decision"] == "passed" else output["decision"]
    state["revision_count"] = output["revision_count"]
    state["revision_plan"] = output["revision_plan"]
    state["passed_resources"] = output["passed_resources"]
    if state["decision"] == "manual_review_required":
        state["manual_review_required"] = True
    append_trace(
        state,
        ORCHESTRATOR_AGENT_NAME,
        "completed",
        {"step": "finalize_task", **output["trace"], "decision": state["decision"]},
    )
    return state


def human_review(state: AgentGraphState) -> AgentGraphState:
    decision = state.get("human_review_decision")
    if not decision:
        decision = interrupt(
            {
                "task_id": state.get("task_id"),
                "reason": "review_model_disagreement",
                "allowed_decisions": ["approve", "request_revision", "reject"],
            }
        )
        state["human_review_decision"] = decision
    if decision == "approve":
        state["decision"] = "completed"
        state["manual_review_required"] = False
    elif decision == "request_revision":
        state["decision"] = "revision_required"
        state["revision_count"] = int(state.get("revision_count") or 0) + 1
        state["manual_review_required"] = False
    elif decision == "reject":
        state["decision"] = "rejected"
        state["manual_review_required"] = False
    else:
        state["decision"] = "manual_review_required"
        state["manual_review_required"] = True
    append_trace(
        state,
        ORCHESTRATOR_AGENT_NAME,
        "completed",
        {"step": "human_review", "decision": state["decision"]},
    )
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


def route_after_prepare(state: AgentGraphState) -> str:
    if state.get("resume_node") == "human_review":
        return "human_review"
    if state.get("trigger_type") == "resource_feedback":
        return "interpret_feedback"
    return "analyze_profile"


def route_after_profile(state: AgentGraphState) -> str:
    return "retrieve_knowledge" if state.get("needs_generation", True) else "finalize_task"


def route_after_finalize(state: AgentGraphState) -> str:
    if state.get("decision") == "revision_required" and int(state.get("revision_count") or 0) <= 2:
        return "retrieve_knowledge"
    if state.get("decision") == "manual_review_required" or (
        state.get("execution_mode") == "assisted"
        and state.get("decision") == "completed"
        and not state.get("human_review_decision")
    ):
        return "human_review"
    return "end"


def route_after_human_review(state: AgentGraphState) -> str:
    if not state.get("human_review_decision"):
        return "end"
    if state.get("decision") == "revision_required" and int(state.get("revision_count") or 0) <= 2:
        return "retrieve_knowledge"
    return "finalize_task"
