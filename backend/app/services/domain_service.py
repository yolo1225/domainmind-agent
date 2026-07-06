def validate_domain_counts(knowledge_count: int, question_count: int) -> list[dict]:
    issues = []
    if knowledge_count < 50:
        issues.append({"level": "warning", "message": "knowledge_count_below_mvp_target"})
    if question_count < 60:
        issues.append({"level": "warning", "message": "question_count_below_mvp_target"})
    return issues
