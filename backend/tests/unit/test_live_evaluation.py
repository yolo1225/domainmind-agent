import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("evaluation_script", ROOT / "test_script" / "evaluate.py")
assert SPEC and SPEC.loader
evaluation_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation_script)


def test_live_result_merge_keeps_gold_and_replaces_only_observation() -> None:
    cases = [
        {
            "case_id": "EVAL-001",
            "expected_review_conclusion": "passed",
            "expected_profile_decision": "no_change",
            "observed_result": {"determinable": True, "latency_ms": 1},
        }
    ]
    run = {
        "run_id": "live-test",
        "results": [
            {
                "case_id": "EVAL-001",
                "observed_result": {
                    "determinable": True,
                    "generated_fact_count": 2,
                    "hallucinated_fact_count": 0,
                    "difficulty_matched": True,
                    "covered_core_knowledge_count": 1,
                    "target_core_knowledge_count": 1,
                    "review_conclusion": "passed",
                    "profile_decision": "no_change",
                    "latency_ms": 200,
                    "agent_latency_ms": {"review_resource": 80},
                },
            }
        ],
    }

    merged = evaluation_script.merge_live_results(cases, run)
    result = evaluation_script.evaluate(
        merged,
        {"kb-test"},
        run_mode="live",
        run_metadata=run,
    )

    assert cases[0]["observed_result"]["latency_ms"] == 1
    assert merged[0]["observed_result"]["latency_ms"] == 200
    assert result["run_mode"] == "live"
    assert result["metrics"]["hallucination_rate"]["ratio"] == 0
    assert result["metrics"]["agent_latency_ms"]["review_resource"] == {
        "p50": 80,
        "p95": 80,
    }
