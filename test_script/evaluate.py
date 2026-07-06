from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "data" / "evaluation_cases"


def main() -> None:
    case_files = sorted(CASES_DIR.glob("*.json"))
    result = {
        "case_count": len(case_files),
        "mvp_target_case_count": 50,
        "hallucination_rate": None,
        "difficulty_match_accuracy": None,
        "knowledge_coverage": None,
        "status": "not_enough_cases" if len(case_files) < 50 else "ready",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
