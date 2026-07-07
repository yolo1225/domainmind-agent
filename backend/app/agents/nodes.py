from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import AgentGraphState
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.models import DiagnosticQuestion, Learner, LearnerProfile
from app.rag.embeddings import embed_texts
from app.rag.vector_store import VectorStore
from app.services.profile_service import (
    generate_profile_from_diagnostic,
    latest_path_for_profile,
)

PROFILE_AGENT_NAME = "profile_analysis_agent"


def append_trace(state: AgentGraphState, agent_name: str, status: str, output: dict) -> None:
    state.setdefault("agent_trace", [])
    state["agent_trace"].append(
        {
            "agent_name": agent_name,
            "status": status,
            "output": output,
        }
    )


def _display_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if repaired else value


def _profile_payload_from_result(result: dict[str, Any], profile_source: str) -> dict[str, Any]:
    return {
        **result,
        "session_id": result.get("session_id"),
        "learner_id": result.get("learner_id"),
        "profile_id": result.get("profile_id"),
        "profile_type": result.get("profile_type"),
        "score": result.get("score"),
        "ability_profile": result.get("ability_profile", {}),
        "weak_knowledge": result.get("weak_knowledge", []),
        "learning_path_id": result.get("learning_path_id"),
        "learning_path": result.get("learning_path"),
        "profile_source": profile_source,
    }


def _profile_payload_from_model(
    db: Session,
    learner: Learner,
    profile: LearnerProfile,
) -> dict[str, Any]:
    ability_profile = dict(profile.ability_profile_json or {})
    path = latest_path_for_profile(db, profile)
    return {
        "learner_id": learner.public_id,
        "profile_id": profile.public_id,
        "profile_type": ability_profile.get("profile_type", "beginner"),
        "ability_profile": ability_profile,
        "weak_knowledge": profile.weak_knowledge_json or [],
        "learning_path_id": path.public_id if path else None,
        "learning_path": path.path_json if path else None,
        "profile_source": "existing_profile",
    }


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


def _load_existing_profile(state: AgentGraphState, db: Session | None) -> dict[str, Any]:
    if db is None:
        ability_profile = dict(state.get("profile", {}))
        return {
            "learner_id": state.get("learner_id"),
            "profile_id": state.get("profile_id"),
            "profile_type": ability_profile.get("profile_type", "beginner"),
            "ability_profile": ability_profile,
            "weak_knowledge": ability_profile.get("weak_knowledge", []),
            "learning_path_id": ability_profile.get("learning_path_id"),
            "learning_path": None,
            "profile_source": "existing_profile",
        }

    learner = db.scalar(select(Learner).where(Learner.public_id == state.get("learner_id")))
    if learner is None:
        raise ValueError(f"learner not found: {state.get('learner_id')}")

    profile = None
    if state.get("profile_id"):
        profile = db.scalar(
            select(LearnerProfile).where(LearnerProfile.public_id == state["profile_id"])
        )
    if profile is None:
        profile = db.scalar(
            select(LearnerProfile)
            .where(LearnerProfile.learner_id == learner.id)
            .where(LearnerProfile.domain_code == state.get("domain_code", learner.target_domain))
            .order_by(LearnerProfile.id.desc())
        )
    if profile is None:
        raise ValueError(f"profile not found for learner: {learner.public_id}")
    return _profile_payload_from_model(db, learner, profile)


def _analyze_diagnostic_profile(state: AgentGraphState, db: Session | None) -> dict[str, Any]:
    if db is None:
        raise ValueError("db_session is required for diagnostic profile analysis")

    learner = db.scalar(select(Learner).where(Learner.public_id == state.get("learner_id")))
    if learner is None:
        raise ValueError(f"learner not found: {state.get('learner_id')}")

    answer_by_question_id = dict(state.get("answer_by_question_id") or {})
    if not answer_by_question_id:
        answer_by_question_id = {
            item["question_id"]: item.get("answer")
            for item in state.get("answers", [])
            if item.get("question_id")
        }
    question_ids = state.get("question_ids") or list(answer_by_question_id.keys())
    questions = list(
        db.scalars(select(DiagnosticQuestion).where(DiagnosticQuestion.public_id.in_(question_ids)))
    )
    if not questions:
        raise ValueError("diagnostic questions not found")

    result = generate_profile_from_diagnostic(
        db,
        learner=learner,
        domain_code=state.get("domain_code", learner.target_domain),
        session_id=state.get("session_id", ""),
        questions=questions,
        answer_by_question_id=answer_by_question_id,
    )
    return _profile_payload_from_result(result, "diagnostic_analysis")


def load_profile(state: AgentGraphState) -> AgentGraphState:
    state["contract_version"] = AGENT_CONTRACT_VERSION
    mode = state.get("profile_mode")
    if mode is None:
        mode = "analyze_diagnostic" if state.get("answers") or state.get("session_id") else "load_existing_profile"
    db = state.get("db_session")
    payload = (
        _analyze_diagnostic_profile(state, db)
        if mode == "analyze_diagnostic"
        else _load_existing_profile(state, db)
    )
    _apply_profile_payload(state, payload)
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
        },
    )
    return state


def _weak_item_text(item: Any) -> str:
    if isinstance(item, dict):
        return f"{item.get('name', '')} {item.get('category', '')} {item.get('knowledge_id', '')}"
    return str(item)


def retrieve_knowledge(state: AgentGraphState) -> AgentGraphState:
    weak_items = state.get("profile", {}).get("weak_knowledge", [])
    query_text = " ".join(
        [
            state.get("learning_goal", ""),
            *[_weak_item_text(item) for item in weak_items],
        ]
    ).strip()
    if not query_text:
        query_text = "人工智能应用开发 个性化学习 诊断 薄弱知识"

    vector_store = VectorStore()
    result = vector_store.query(
        domain_code=state.get("domain_code", "ai_app_dev"),
        query_embeddings=embed_texts([query_text]),
        n_results=5,
    )
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    state["retrieved_chunks"] = [
        {
            "chunk_id": ids[index],
            "knowledge_id": metadata.get("knowledge_id"),
            "name": _display_text(metadata.get("name")),
            "category": _display_text(metadata.get("category")),
            "difficulty": metadata.get("difficulty", 1),
            "content": _display_text(documents[index]),
            "source_title": _display_text(metadata.get("source_title", "")),
            "source_url": metadata.get("source_url", ""),
            "distance": distances[index],
            "similarity": round(1 / (1 + distances[index]), 4),
            "selection_reason": "chroma_vector_search",
        }
        for index, metadata in enumerate(metadatas)
    ]
    append_trace(
        state,
        "knowledge_retrieval_agent",
        "completed",
        {
            "query": query_text,
            "retrieved": [item["knowledge_id"] for item in state["retrieved_chunks"]],
        },
    )
    return state


def generate_resource(state: AgentGraphState) -> AgentGraphState:
    sources = state.get("retrieved_chunks", [])
    source_lines = "\n".join(
        f"- {_display_text(item['name'])}（{item['knowledge_id']}）：{_display_text(item.get('content', ''))}"
        for item in sources
    )
    main_title = _display_text(sources[0]["name"]) if sources else "AI 应用开发"
    profile_type = state.get("profile", {}).get("profile_type", "beginner")
    drafts = []
    for resource_type in state.get("resource_types", []):
        if resource_type == "lecture":
            content = (
                f"# 个性化讲义：{main_title}\n\n"
                f"画像类型：{profile_type}。\n\n"
                "## 学习目标\n"
                "- 理解薄弱知识点的核心概念。\n"
                "- 能说明它在 AI 应用开发闭环中的作用。\n\n"
                f"## 来源知识\n{source_lines}\n"
            )
        elif resource_type == "practice_guide":
            content = (
                "# 实操指南\n\n"
                "1. 阅读来源知识，标出输入、处理、输出和验证方式。\n"
                "2. 在项目中找到对应 API、脚本或配置文件。\n"
                "3. 完成一次最小运行，并记录可复现的验证结果。\n\n"
                f"## 来源知识\n{source_lines}\n"
            )
        else:
            content = (
                "# 分级测验\n\n"
                f"围绕“{main_title}”，最应该关注什么？\n\n"
                "A. 页面装饰\nB. 任务、来源、验证和反馈\nC. 随机输出\nD. 跳过评审\n\n"
                "答案：B\n\n"
                f"## 来源知识\n{source_lines}\n"
            )
        drafts.append(
            {
                "resource_type": resource_type,
                "title": f"{main_title}个性化{resource_type}",
                "content": content,
                "difficulty": max([item.get("difficulty", 1) for item in sources] or [1]),
                "sources": [
                    {
                        "knowledge_id": item["knowledge_id"],
                        "name": _display_text(item["name"]),
                        "source_title": _display_text(item.get("source_title", "")),
                    }
                    for item in sources
                ],
            }
        )
    state["draft_resources"] = drafts
    append_trace(
        state,
        "content_generation_agent",
        "completed",
        {"resource_count": len(drafts), "resource_types": state.get("resource_types", [])},
    )
    return state


def review_resource(state: AgentGraphState) -> AgentGraphState:
    reports = []
    for draft in state.get("draft_resources", []):
        has_sources = bool(draft.get("sources"))
        has_content = len(draft.get("content", "")) > 80
        passed = has_sources and has_content
        reports.append(
            {
                "resource_type": draft.get("resource_type"),
                "facts_score": 90 if has_sources else 55,
                "source_traceability_score": 100 if has_sources else 40,
                "difficulty_match_score": 84,
                "coverage_score": 88 if has_content else 50,
                "passed": passed,
            }
        )
    state["review_reports"] = reports or [
        {
            "facts_score": 0,
            "source_traceability_score": 0,
            "difficulty_match_score": 0,
            "coverage_score": 0,
            "passed": False,
        }
    ]
    append_trace(
        state,
        "review_validation_agent",
        "completed",
        {
            "passed": all(report.get("passed") for report in state["review_reports"]),
            "report_count": len(state["review_reports"]),
        },
    )
    return state


def decide_next_step(state: AgentGraphState) -> AgentGraphState:
    reports = state.get("review_reports", [])
    if reports and all(report.get("passed") for report in reports):
        state["decision"] = "passed"
    elif state.get("revision_count", 0) < 2:
        state["decision"] = "revision_required"
        state["revision_count"] = state.get("revision_count", 0) + 1
    else:
        state["decision"] = "failed"
    append_trace(
        state,
        "orchestrator_agent",
        "completed",
        {"decision": state["decision"], "revision_count": state.get("revision_count", 0)},
    )
    return state


def persist_resource(state: AgentGraphState) -> AgentGraphState:
    append_trace(
        state,
        "orchestrator_agent",
        "completed",
        {"next_step": "persist_resource", "resource_count": len(state.get("draft_resources", []))},
    )
    return state


def route_after_decision(state: AgentGraphState) -> str:
    if state["decision"] == "passed":
        return "persist_resource"
    if state["decision"] == "revision_required" and state["revision_count"] < 2:
        return "retrieve_knowledge"
    return "end"
