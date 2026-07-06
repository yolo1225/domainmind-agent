def classify_profile_level(score: float) -> str:
    if score < 60:
        return "beginner"
    if score < 85:
        return "intermediate"
    return "advanced"
