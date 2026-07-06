def decide_feedback_action(feedback_type: str) -> str:
    mapping = {
        "too_hard": "remedial_explanation",
        "too_easy": "challenge_task",
        "has_error": "review_correction",
        "helpful": "profile_update",
    }
    return mapping.get(feedback_type, "profile_update")
