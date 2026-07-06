from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("learning_resources.id"))
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    rating: Mapped[int] = mapped_column(default=0)
    feedback_type: Mapped[str] = mapped_column(String(32))
    feedback_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    triggered_action: Mapped[str] = mapped_column(String(64), default="")
