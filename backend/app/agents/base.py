from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.agents.legacy_contracts import AgentMessage, AgentName


class BaseAgent(ABC):
    name: AgentName
    system_prompt_path: str

    @abstractmethod
    async def run(self, message: AgentMessage) -> dict[str, Any]:
        """Execute one structured agent turn."""

    def system_prompt(self) -> str:
        path = Path(__file__).resolve().parents[2] / self.system_prompt_path
        return path.read_text(encoding="utf-8")


class PromptBudget:
    """Small deterministic guard used before all model calls."""

    def __init__(self, max_input_tokens: int, max_output_tokens: int) -> None:
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens

    def validate(self, text: str) -> dict[str, int | bool]:
        estimated = max(1, len(text) // 2)
        if estimated > self.max_input_tokens:
            raise ValueError(
                f"prompt budget exceeded: {estimated}>{self.max_input_tokens} estimated tokens"
            )
        return {
            "estimated_input_tokens": estimated,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "within_budget": True,
        }
