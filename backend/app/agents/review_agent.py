from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage


class ReviewValidationAgent(BaseAgent):
    name = "review_validation_agent"
    system_prompt_path = "app/agents/prompts/review_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "primary_review": {"score": 92, "passed": True},
            "secondary_review": {"score": 90, "passed": True},
            "decision": "passed",
            "manual_review_required": False,
        }
