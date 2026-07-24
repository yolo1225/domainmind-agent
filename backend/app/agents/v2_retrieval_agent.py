from __future__ import annotations

from typing import Any

from app.agents.contracts import RetrieveKnowledgeInput, RetrieveKnowledgeOutput
from app.core.config import Settings
from app.core.db import SessionLocal
from app.rag.candidate_manifest import CandidateManifestStore
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.v2_retrieval import V2CandidateRetriever
from app.rag.vector_store import VectorStore


RETRIEVAL_AGENT_NAME = "knowledge_retrieval_agent_v2"
SYSTEM_PROMPT = (
    "你是 V2 知识检索智能体。只返回 candidate 索引中可追溯的知识片段与来源，"
    "不生成教学内容，不编造来源，不调用语言模型；唯一允许的模型调用是查询 embedding。"
)


class V2KnowledgeRetrievalAgent:
    """Standalone V2 retrieval boundary; it deliberately does not inherit legacy BaseAgent."""

    name = RETRIEVAL_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(self, retriever: V2CandidateRetriever) -> None:
        self._retriever = retriever

    @classmethod
    def production(cls, *, mode: str = "full") -> "V2KnowledgeRetrievalAgent":
        settings = Settings()
        return cls(
            V2CandidateRetriever(
                db=SessionLocal(),
                chroma_client=VectorStore().client,
                embedding_provider=OpenAICompatibleEmbeddingProvider(
                    base_url=settings.openai_api_base,
                    api_key=settings.openai_api_key,
                    model=settings.embedding_model,
                    timeout_seconds=settings.llm_timeout_seconds,
                ),
                manifest_store=CandidateManifestStore(),
                mode=mode,
            )
        )

    def execute(self, request: RetrieveKnowledgeInput) -> RetrieveKnowledgeOutput:
        return self._retriever.execute(request)

    def close(self) -> None:
        self._retriever.db.close()

    def __enter__(self) -> "V2KnowledgeRetrievalAgent":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
