from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage


class TutoringAgent(BaseAgent):
    name = "tutoring_agent"
    system_prompt_path = "app/agents/prompts/tutoring_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        feedback_type = message.payload.get("feedback_type", "too_hard")
        action = "remedial_explanation" if feedback_type == "too_hard" else "challenge_task"
        return {"next_action": action, "status": "created"}
