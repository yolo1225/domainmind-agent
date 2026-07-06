from abc import ABC, abstractmethod
from typing import Any

from app.agents.contracts import AgentMessage, AgentName


class BaseAgent(ABC):
    name: AgentName
    system_prompt_path: str

    @abstractmethod
    async def run(self, message: AgentMessage) -> dict[str, Any]:
        """Execute one structured agent turn."""
