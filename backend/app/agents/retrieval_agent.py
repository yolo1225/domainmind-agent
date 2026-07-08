from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage, RetrievalOutput
from app.agents.state import AgentGraphState
from app.rag.embeddings import embed_texts
from app.rag.vector_store import VectorStore


RETRIEVAL_AGENT_NAME = "knowledge_retrieval_agent"


def _display_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if repaired else value


def _weak_item_text(item: Any) -> str:
    if isinstance(item, dict):
        return f"{item.get('name', '')} {item.get('category', '')} {item.get('knowledge_id', '')}"
    return str(item)


def _used_for_strategy(strategy: str) -> str:
    if strategy == "remedial":
        return "remedial_explanation"
    if strategy == "challenge":
        return "challenge_task"
    return "consolidation_practice"


def _matched_plan(knowledge_id: Any, retrieval_plan: dict[str, Any]) -> str:
    knowledge_id_text = str(knowledge_id or "")
    if knowledge_id_text in set(retrieval_plan.get("priority_knowledge_ids") or []):
        return "priority"
    if knowledge_id_text in set(retrieval_plan.get("prerequisite_knowledge_ids") or []):
        return "prerequisite"
    return "semantic"


class KnowledgeRetrievalAgent(BaseAgent):
    name = RETRIEVAL_AGENT_NAME
    system_prompt_path = "app/agents/prompts/retrieval_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "agent_name": self.name,
            "status": "ready_for_stateful_execution",
            "payload_keys": sorted(message.payload.keys()),
        }

    def execute(self, state: AgentGraphState) -> dict[str, Any]:
        retrieval_plan = state.get("retrieval_plan") or {}
        revision_plan = state.get("revision_plan") or {}
        query_terms = retrieval_plan.get("query_terms") or []
        if revision_plan.get("revision_required"):
            query_terms = [*query_terms, *(revision_plan.get("query_terms") or [])]
        query_text = " ".join(str(term) for term in query_terms if str(term or "").strip()).strip()
        if not query_text:
            weak_items = state.get("profile", {}).get("weak_knowledge", [])
            query_text = " ".join(
                [
                    state.get("learning_goal", ""),
                    *[_weak_item_text(item) for item in weak_items],
                ]
            ).strip()
        if not query_text:
            query_text = "人工智能应用开发 个性化学习 诊断 薄弱知识"

        n_results = int(retrieval_plan.get("n_results") or 5) + int(
            revision_plan.get("n_results_boost") or 0
        )
        strategy = retrieval_plan.get("strategy") or "fallback"
        used_for = _used_for_strategy(strategy)
        result = VectorStore().query(
            domain_code=state.get("domain_code", "ai_app_dev"),
            query_embeddings=embed_texts([query_text]),
            n_results=n_results,
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        retrieved_chunks = [
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
                "selection_reason": f"retrieval_plan:{strategy}",
                "matched_plan": _matched_plan(metadata.get("knowledge_id"), retrieval_plan),
                "strategy": strategy,
                "target_difficulty": retrieval_plan.get("target_difficulty"),
                "used_for": used_for,
            }
            for index, metadata in enumerate(metadatas)
        ]
        matched_priority_count = sum(
            1 for item in retrieved_chunks if item.get("matched_plan") == "priority"
        )
        matched_prerequisite_count = sum(
            1 for item in retrieved_chunks if item.get("matched_plan") == "prerequisite"
        )
        semantic_count = sum(
            1 for item in retrieved_chunks if item.get("matched_plan") == "semantic"
        )
        return RetrievalOutput(
            retrieved_chunks=retrieved_chunks,
            trace={
                "query": query_text,
                "retrieved": [item["knowledge_id"] for item in retrieved_chunks],
                "strategy": strategy,
                "target_difficulty": retrieval_plan.get("target_difficulty"),
                "priority_knowledge_ids": retrieval_plan.get("priority_knowledge_ids", []),
                "prerequisite_knowledge_ids": retrieval_plan.get(
                    "prerequisite_knowledge_ids", []
                ),
                "matched_priority_count": matched_priority_count,
                "matched_prerequisite_count": matched_prerequisite_count,
                "semantic_count": semantic_count,
                "revision_required": bool(revision_plan.get("revision_required")),
                "revision_query_terms": revision_plan.get("query_terms", []),
            },
        ).model_dump()
