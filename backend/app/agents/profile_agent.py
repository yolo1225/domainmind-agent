from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage


class ProfileAnalysisAgent(BaseAgent):
    name = "profile_analysis_agent"
    system_prompt_path = "app/agents/prompts/profile_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "profile_id": message.payload.get("profile_id", "profile_demo_001"),
            "ability_profile": message.payload.get("ability_profile", {}),
            "weak_knowledge": message.payload.get("weak_knowledge", []),
        }
