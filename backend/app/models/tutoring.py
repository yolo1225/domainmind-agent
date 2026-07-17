from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TutoringSession(TimestampMixin, Base):
    __tablename__ = "tutoring_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("learning_resources.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    turn_count: Mapped[int] = mapped_column(default=0)


class TutoringMessage(TimestampMixin, Base):
    __tablename__ = "tutoring_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("tutoring_sessions.id"))
    sender: Mapped[str] = mapped_column(String(32))
    message_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    feedback_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_feedback.id", use_alter=True), nullable=True
    )


class ManualReviewTask(TimestampMixin, Base):
    __tablename__ = "manual_review_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("generation_tasks.id"))
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("learning_resources.id"), nullable=True)
    review_report_id: Mapped[int | None] = mapped_column(ForeignKey("review_reports.id"), nullable=True)
    trigger_reason: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
