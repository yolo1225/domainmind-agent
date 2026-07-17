from __future__ import annotations

import json
from pathlib import Path

from app.agents.contract_examples import (
    agent_message_example,
    dump_example,
    feedback_flow_example,
    human_review_example,
    initial_generation_flow_example,
    resource_examples,
)
from app.agents.contracts import AgentContractSchema


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "docs" / "contracts" / "v2"


def _write(name: str, payload: object) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _write("agent-contract-v2.schema.json", AgentContractSchema.model_json_schema())
    _write("agent-message.example.json", dump_example(agent_message_example()))
    _write("initial-generation.example.json", dump_example(initial_generation_flow_example()))
    _write("feedback-no-change.example.json", dump_example(feedback_flow_example()))
    _write("human-review.example.json", dump_example(human_review_example()))
    _write("resource-types.example.json", dump_example(resource_examples()))
    print(json.dumps({"status": "ok", "output_dir": str(OUTPUT_DIR)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
