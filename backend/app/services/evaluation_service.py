def target_metrics() -> dict:
    return {
        "hallucination_rate": "< 5%",
        "difficulty_match_accuracy": ">= 85%",
        "knowledge_coverage": ">= 90%",
        "case_count": ">= 50",
    }
