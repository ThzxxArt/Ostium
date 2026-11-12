"""Database models for Ostium v1 schema.

The schema is intentionally a single SQLite database for both roles.  Client-only
tables (``profiles``) are unused on servers; server-only tables are unused on
clients, which keeps migrations and backups identical across roles.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ostium.db.base import Base, TimestampMixin
from ostium.util.ids import new_id
from ostium.util.time import utcnow


class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    recovery_codes_hash: Mapped[list[str]] = mapped_column(default=list)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    admin_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProxyUser(TimestampMixin, Base):
    __tablename__ = "proxy_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    ss_password_enc: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quota_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quota_cycle: Mapped[str] = mapped_column(String(16), default="total", nullable=False)
    cycle_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subscription_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    subscription_token_enc: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(String(100))


class TrafficDaily(Base):
    __tablename__ = "traffic_user_daily"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_traffic_user_day"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("proxy_users.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    uplink: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    downlink: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StatsEpoch(Base):
    __tablename__ = "stats_epochs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("proxy_users.id", ondelete="CASCADE"), index=True
    )
    epoch: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_up: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_down: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Profile(TimestampMixin, Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    config_enc: Mapped[str] = mapped_column(Text, nullable=False)
    subscription_url_enc: Mapped[str | None] = mapped_column(Text)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_error: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selected_endpoint: Mapped[str | None] = mapped_column(String(100))


class Rule(TimestampMixin, Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    action: Mapped[str] = mapped_column(String(16), default="proxy", nullable=False)
    match_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    note: Mapped[str] = mapped_column(String(300), default="", nullable=False)


class RuleSet(TimestampMixin, Base):
    __tablename__ = "rule_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    format: Mapped[str] = mapped_column(String(16), default="srs", nullable=False)
    path: Mapped[str | None] = mapped_column(String(500))
    etag: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class Certificate(TimestampMixin, Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    cert_path: Mapped[str] = mapped_column(String(500), nullable=False)
    key_path: Mapped[str] = mapped_column(String(500), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="acme", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class Inbound(TimestampMixin, Base):
    """A server-side proxy line."""

    __tablename__ = "inbounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    listen: Mapped[str] = mapped_column(String(64), default="0.0.0.0", nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    params_enc: Mapped[str | None] = mapped_column(Text)
    certificate_id: Mapped[str | None] = mapped_column(
        ForeignKey("certificates.id", ondelete="SET NULL")
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(100), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    target: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    detail_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    level: Mapped[str] = mapped_column(String(16), default="warning", nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Backup(Base):
    __tablename__ = "backups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
