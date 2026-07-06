from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeItem(TimestampMixin, Base):
    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai_app_dev", index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64))
    difficulty: Mapped[int] = mapped_column(default=1)
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    content_md: Mapped[str] = mapped_column(Text)
    source_title: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    license_note: Mapped[str] = mapped_column(String(255), default="")
    needs_reembedding: Mapped[bool] = mapped_column(default=True)


class KnowledgeRelation(TimestampMixin, Base):
    __tablename__ = "knowledge_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    target_item_id: Mapped[int] = mapped_column(ForeignKey("knowledge_items.id"))
    relation_type: Mapped[str] = mapped_column(String(32))
