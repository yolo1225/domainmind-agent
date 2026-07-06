from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DiagnosticQuestion(TimestampMixin, Base):
    __tablename__ = "diagnostic_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev")
    knowledge_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    question_type: Mapped[str] = mapped_column(String(32))
    stem: Mapped[str] = mapped_column(Text)
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    answer_key_json: Mapped[dict] = mapped_column(JSON, default=dict)
    difficulty: Mapped[int] = mapped_column(default=1)


class AnswerRecord(TimestampMixin, Base):
    __tablename__ = "answer_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_questions.id"))
    knowledge_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    score: Mapped[float] = mapped_column(default=0)
    is_correct: Mapped[bool] = mapped_column(default=False)
    answer_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
