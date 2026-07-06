from app.agents.graphs import build_generation_graph
from app.agents.state import AgentGraphState
from app.core.compatibility import AGENT_CONTRACT_VERSION


def create_initial_state(
    task_id: str,
    learner_id: str,
    profile_id: str,
    learning_goal: str,
) -> AgentGraphState:
    return {
        "contract_version": AGENT_CONTRACT_VERSION,
        "task_id": task_id,
        "learner_id": learner_id,
        "profile_id": profile_id,
        "domain_code": "ai_app_dev",
        "resource_types": ["lecture", "practice_guide", "graded_quiz"],
        "learning_goal": learning_goal,
        "profile": {},
        "retrieved_chunks": [],
        "draft_resources": [],
        "review_reports": [],
        "revision_count": 0,
        "decision": "pending",
        "error_message": None,
    }


def get_generation_graph():
    return build_generation_graph()
