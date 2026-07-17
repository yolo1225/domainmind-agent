from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Feedback(TimestampMixin, Base):
    __tablename__ = "resource_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("learning_resources.id"))
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    rating: Mapped[int | None] = mapped_column(nullable=True)
    feedback_type: Mapped[str] = mapped_column(String(32))
    feedback_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    triggered_action: Mapped[str] = mapped_column(String(64), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    tutoring_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("tutoring_sessions.id", use_alter=True), nullable=True
    )
    tutoring_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("tutoring_messages.id", use_alter=True), nullable=True
    )
    feedback_intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    profile_update_required: Mapped[bool] = mapped_column(default=False)
    profile_change_evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    decision_confidence: Mapped[float] = mapped_column(Float, default=0)
    affected_knowledge_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    affected_path_node_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    affected_resource_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    decision_reason: Mapped[str] = mapped_column(Text, default="")
