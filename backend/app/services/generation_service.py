from app.agents.orchestrator import create_initial_state


def preview_generation_state(task_id: str, learner_id: str, profile_id: str, learning_goal: str):
    return create_initial_state(task_id, learner_id, profile_id, learning_goal)
