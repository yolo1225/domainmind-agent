from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage


class ContentGenerationAgent(BaseAgent):
    name = "content_generation_agent"
    system_prompt_path = "app/agents/prompts/generation_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        resource_types = message.payload.get(
            "resource_types", ["lecture", "practice_guide", "graded_quiz"]
        )
        return {
            "draft_resources": [
                {
                    "resource_type": resource_type,
                    "title": f"demo {resource_type}",
                    "sources": message.payload.get("source_ids", []),
                }
                for resource_type in resource_types
            ]
        }
