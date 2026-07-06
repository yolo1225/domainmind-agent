from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage


class KnowledgeRetrievalAgent(BaseAgent):
    name = "knowledge_retrieval_agent"
    system_prompt_path = "app/agents/prompts/retrieval_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "retrieved_chunks": [
                {
                    "knowledge_id": "rag_chunking",
                    "title": "RAG 文档切片策略",
                    "source_title": "自建 AI 应用开发实训知识库",
                    "similarity": 0.91,
                }
            ]
        }
