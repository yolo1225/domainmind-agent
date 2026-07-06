def build_metric_summary(hallucination_rate: float, difficulty_match: float, coverage: float) -> dict:
    return {
        "hallucination_rate": hallucination_rate,
        "difficulty_match_accuracy": difficulty_match,
        "knowledge_coverage": coverage,
    }
