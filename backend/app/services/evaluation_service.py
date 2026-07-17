import json
from pathlib import Path
from typing import Literal


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = PROJECT_ROOT / "reports" / "evaluation"


def target_metrics() -> dict:
    return {
        "hallucination_rate": "< 5%",
        "difficulty_match_accuracy": ">= 85%",
        "knowledge_coverage": ">= 90%",
        "case_count": ">= 50",
    }


def load_evaluation_summary(mode: Literal["live", "baseline"]) -> dict:
    candidates = (
        [REPORT_DIR / "latest-live.json"]
        if mode == "live"
        else [REPORT_DIR / "latest-baseline.json", REPORT_DIR / "latest.json"]
    )
    report = next((path for path in candidates if path.is_file()), None)
    if report is None:
        return {
            "status": "not_run",
            "run_mode": mode,
            "case_count": 0,
            "mvp_target_case_count": 50,
            "metrics": {},
            "evaluated_at": None,
        }
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload.setdefault("run_mode", mode)
    return payload
