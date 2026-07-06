from app.agents.state import AgentGraphState
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


def load_profile(state: AgentGraphState) -> AgentGraphState:
    state["contract_version"] = AGENT_CONTRACT_VERSION
    state.setdefault("profile", {})
    append_trace(
        state,
        "profile_analysis_agent",
        "completed",
        {
            "profile_id": state.get("profile_id"),
            "profile_type": state.get("profile", {}).get("profile_type", "beginner"),
        },
    )
    return state


def retrieve_knowledge(state: AgentGraphState) -> AgentGraphState:
    weak_items = state.get("profile", {}).get("weak_knowledge", [])
    query_text = " ".join(
        [
            state.get("learning_goal", ""),
            *[
                f"{item.get('name', '')} {item.get('category', '')} {item.get('knowledge_id', '')}"
                for item in weak_items
            ],
        ]
    ).strip()
    if not query_text:
        query_text = "人工智能应用开发 个性化学习 诊断薄弱知识"

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
            "name": metadata.get("name"),
            "category": metadata.get("category"),
            "difficulty": metadata.get("difficulty", 1),
            "content": documents[index],
            "source_title": metadata.get("source_title", ""),
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
        f"- {item['name']}（{item['knowledge_id']}）：{item.get('content', '')}" for item in sources
    )
    main_title = sources[0]["name"] if sources else "AI 应用开发"
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
                "1. 阅读来源知识。\n"
                "2. 复述输入、处理、输出和验证方式。\n"
                "3. 在项目中找到对应 API 或脚本做一次运行。\n\n"
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
                        "name": item["name"],
                        "source_title": item.get("source_title", ""),
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
