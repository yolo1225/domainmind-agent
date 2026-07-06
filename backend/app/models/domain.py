from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Domain(TimestampMixin, Base):
    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[str] = mapped_column(String(32), default="1.0")
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
