from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.agents.legacy_contracts import AgentMessage
from app.agents.legacy_state import AgentGraphState
from app.models import DiagnosticQuestion, Learner, LearnerProfile
from app.services.profile_service import (
    generate_profile_from_diagnostic,
    latest_path_for_profile,
    profile_source,
)

PROFILE_AGENT_NAME = "profile_analysis_agent"


class ProfileAnalysisAgent(BaseAgent):
    name = PROFILE_AGENT_NAME
    system_prompt_path = "app/agents/prompts/profile_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "agent_name": self.name,
            "profile_mode": message.payload.get("profile_mode", "load_existing_profile"),
            "status": "ready_for_stateful_execution",
        }

    def execute(self, state: AgentGraphState) -> dict[str, Any]:
        mode = state.get("profile_mode")
        if mode is None:
            mode = (
                "analyze_diagnostic"
                if state.get("answers") or state.get("session_id")
                else "load_existing_profile"
            )

        db = state.get("db_session")
        if mode == "analyze_diagnostic":
            return self.analyze_diagnostic(state, db)
        return self.load_existing_profile(state, db)

    def analyze_diagnostic(
        self,
        state: AgentGraphState,
        db: Session | None,
    ) -> dict[str, Any]:
        if db is None:
            raise ValueError("db_session is required for diagnostic profile analysis")

        learner = db.scalar(select(Learner).where(Learner.public_id == state.get("learner_id")))
        if learner is None:
            raise ValueError(f"learner not found: {state.get('learner_id')}")

        answer_by_question_id = dict(state.get("answer_by_question_id") or {})
        if not answer_by_question_id:
            answer_by_question_id = {
                item["question_id"]: item.get("answer")
                for item in state.get("answers", [])
                if item.get("question_id")
            }
        question_ids = state.get("question_ids") or list(answer_by_question_id.keys())
        questions = list(
            db.scalars(
                select(DiagnosticQuestion).where(DiagnosticQuestion.public_id.in_(question_ids))
            )
        )
        if not questions:
            raise ValueError("diagnostic questions not found")

        result = generate_profile_from_diagnostic(
            db,
            learner=learner,
            domain_code=state.get("domain_code", learner.target_domain),
            session_id=state.get("session_id", ""),
            questions=questions,
            answer_by_question_id=answer_by_question_id,
        )
        return self._profile_payload_from_result(result, "diagnostic_analysis")

    def load_existing_profile(
        self,
        state: AgentGraphState,
        db: Session | None,
    ) -> dict[str, Any]:
        if db is None:
            ability_profile = dict(state.get("profile", {}))
            return {
                "learner_id": state.get("learner_id"),
                "profile_id": state.get("profile_id"),
                "profile_type": ability_profile.get("profile_type", "beginner"),
                "ability_profile": ability_profile,
                "weak_knowledge": ability_profile.get("weak_knowledge", []),
                "learning_path_id": ability_profile.get("learning_path_id"),
                "learning_path": None,
                "profile_source": "existing_profile",
            }

        learner = db.scalar(select(Learner).where(Learner.public_id == state.get("learner_id")))
        if learner is None:
            raise ValueError(f"learner not found: {state.get('learner_id')}")

        profile = None
        if state.get("profile_id"):
            profile = db.scalar(
                select(LearnerProfile).where(LearnerProfile.public_id == state["profile_id"])
            )
        if profile is None:
            profile = db.scalar(
                select(LearnerProfile)
                .where(LearnerProfile.learner_id == learner.id)
                .where(LearnerProfile.domain_code == state.get("domain_code", learner.target_domain))
                .order_by(LearnerProfile.id.desc())
            )
        if profile is None:
            raise ValueError(f"profile not found for learner: {learner.public_id}")
        return self._profile_payload_from_model(db, learner, profile)

    def _profile_payload_from_result(
        self,
        result: dict[str, Any],
        profile_source: str,
    ) -> dict[str, Any]:
        return {
            **result,
            "session_id": result.get("session_id"),
            "learner_id": result.get("learner_id"),
            "profile_id": result.get("profile_id"),
            "profile_type": result.get("profile_type"),
            "score": result.get("score"),
            "ability_profile": result.get("ability_profile", {}),
            "weak_knowledge": result.get("weak_knowledge", []),
            "learning_path_id": result.get("learning_path_id"),
            "learning_path": result.get("learning_path"),
            "profile_source": profile_source,
        }

    def _profile_payload_from_model(
        self,
        db: Session,
        learner: Learner,
        profile: LearnerProfile,
    ) -> dict[str, Any]:
        ability_profile = dict(profile.ability_profile_json or {})
        path = latest_path_for_profile(db, profile)
        return {
            "learner_id": learner.public_id,
            "profile_id": profile.public_id,
            "profile_type": ability_profile.get("profile_type", "beginner"),
            "ability_profile": ability_profile,
            "weak_knowledge": profile.weak_knowledge_json or [],
            "learning_path_id": path.public_id if path else None,
            "learning_path": path.path_json if path else None,
            "profile_version": profile.profile_version,
            "profile_changed_dimensions": profile.changed_dimensions_json or [],
            "profile_source": "existing_profile",
            "profile_origin": profile_source(profile),
            "previous_profile_id": profile.previous_profile_id,
        }
