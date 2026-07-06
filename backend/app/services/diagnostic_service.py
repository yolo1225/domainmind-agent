def calculate_choice_score(correct_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round(correct_count / total_count * 100, 2)
