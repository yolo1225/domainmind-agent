from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Learner(TimestampMixin, Base):
    __tablename__ = "learners"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    background: Mapped[str] = mapped_column(String(255), default="")
    target_domain: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    experience_years: Mapped[int] = mapped_column(default=0)
    learning_style: Mapped[str] = mapped_column(String(32), default="mixed")


class LearnerProfile(TimestampMixin, Base):
    __tablename__ = "learner_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    ability_profile_json: Mapped[dict] = mapped_column(JSON, default=dict)
    weak_knowledge_json: Mapped[list] = mapped_column(JSON, default=list)


class LearningPath(TimestampMixin, Base):
    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("learner_profiles.id"), nullable=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    status: Mapped[str] = mapped_column(String(32), default="active")
    path_json: Mapped[dict] = mapped_column(JSON, default=dict)
    needs_refresh: Mapped[bool] = mapped_column(default=False)
