from __future__ import annotations

from typing import Any

from app.agents.contracts import RetrieveKnowledgeInput, RetrieveKnowledgeOutput
from app.agents.prompt_registry import get_prompt
from app.core.config import settings
from app.core.db import SessionLocal
from app.rag.database_manifest_store import DatabaseManifestStore
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.retrieval import CandidateRetriever
from app.rag.vector_store import VectorStore


RETRIEVAL_AGENT_NAME = "knowledge_retrieval_agent_v3"
SYSTEM_PROMPT = get_prompt("retrieval")


class KnowledgeRetrievalAgent:
    """Standalone V10 retrieval boundary with no legacy base dependency."""

    name = RETRIEVAL_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(self, retriever: CandidateRetriever) -> None:
        self._retriever = retriever

    @classmethod
    def production(cls, *, mode: str = "full") -> "KnowledgeRetrievalAgent":
        return cls(
            CandidateRetriever(
                db=SessionLocal(),
                chroma_client=VectorStore().client,
                embedding_provider=OpenAICompatibleEmbeddingProvider(
                    base_url=settings.openai_api_base,
                    api_key=settings.openai_api_key,
                    model=settings.embedding_model,
                    timeout_seconds=settings.llm_timeout_seconds,
                ),
                # Keep runtime retrieval aligned with domain readiness. Active
                # index pointers are persisted in MySQL; the legacy local-file
                # manifest is only a compatibility fallback inside this store.
                manifest_store=DatabaseManifestStore(),
                mode=mode,
            )
        )

    def execute(self, request: RetrieveKnowledgeInput) -> RetrieveKnowledgeOutput:
        return self._retriever.execute(request)

    def close(self) -> None:
        self._retriever.db.close()

    def __enter__(self) -> "KnowledgeRetrievalAgent":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
