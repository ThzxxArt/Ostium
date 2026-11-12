"""SQLAlchemy declarative base and shared column types."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ostium.util.time import utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, list[dict[str, Any]]: JSON}  # noqa: RUF012


class TimestampMixin:
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


def utc_column() -> Any:
    return mapped_column(DateTime(timezone=True), nullable=True)
