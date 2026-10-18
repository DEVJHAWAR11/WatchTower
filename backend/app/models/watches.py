from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, pk_uuid, updated_at_col


class Category(Base):
    __tablename__ = "categories"
    slug: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(32))
    sort: Mapped[int] = mapped_column(SmallInteger, default=0)


class Watch(Base):
    __tablename__ = "watches"
    id: Mapped[uuid.UUID] = pk_uuid()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str | None] = mapped_column(Text)
    query_text: Mapped[str] = mapped_column(Text)
    category_slug: Mapped[str | None] = mapped_column(ForeignKey("categories.slug"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="generic")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    region: Mapped[str] = mapped_column(String(8), default="IN")
    visibility: Mapped[str] = mapped_column(String(16), default="private")  # private | unlisted | public
    # draft | active | paused | error | completed | expired | archived
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watch_versions.id", use_alter=True, ondelete="SET NULL")
    )
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    default_delivery_mode: Mapped[str] = mapped_column(String(16), default="instant")
    auto_tune: Mapped[bool] = mapped_column(Boolean, default=True)
    subscriber_count: Mapped[int] = mapped_column(Integer, default=0)
    alert_count: Mapped[int] = mapped_column(Integer, default=0)
    trending_score: Mapped[float] = mapped_column(Float, default=0.0)
    popularity_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # none | pending | approved | rejected
    moderation_status: Mapped[str] = mapped_column(String(16), default="none")
    moderation_reason: Mapped[str | None] = mapped_column(Text)
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    forked_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="SET NULL")
    )
    noise_signatures: Mapped[list[Any]] = mapped_column(JSONB, default=list)  # learned no-op diff lines
    eval_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # rule episodes, last verdicts
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('simple', coalesce(description, '')), 'B') || "
            "setweight(to_tsvector('simple', coalesce(query_text, '')), 'C')",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_watches_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_watches_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
        Index("ix_watches_public_trending", "visibility", "trending_score"),
    )


class WatchVersion(Base):
    __tablename__ = "watch_versions"
    id: Mapped[uuid.UUID] = pk_uuid()
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    spec_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(16))  # intake | user | refinement | rollback | repair
    changelog: Mapped[str | None] = mapped_column(Text)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    backtest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (UniqueConstraint("watch_id", "version"),)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="subscriber")  # owner | subscriber
    delivery_mode: Mapped[str | None] = mapped_column(String(16))  # None -> watch/user default
    channels: Mapped[list[Any] | None] = mapped_column(JSONB)  # None -> user default
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (UniqueConstraint("user_id", "watch_id"),)


class Source(Base):
    """A canonical fetchable URL, shared by every watch that points at it."""

    __tablename__ = "sources"
    id: Mapped[uuid.UUID] = pk_uuid()
    url: Mapped[str] = mapped_column(Text, unique=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="page")  # page | json | feed
    fetch_mode: Mapped[str] = mapped_column(String(16), default="http")  # http | render
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | blocked | gone | error
    status_reason: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(String(256))
    last_modified: Mapped[str | None] = mapped_column(String(64))
    last_status_code: Mapped[int | None] = mapped_column(SmallInteger)
    last_content_hash: Mapped[str | None] = mapped_column(String(64))
    last_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = created_at_col()


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    id: Mapped[uuid.UUID] = pk_uuid()
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"))
    fetched_at: Mapped[datetime] = created_at_col()
    status_code: Mapped[int] = mapped_column(SmallInteger)
    final_url: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64))
    simhash: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    links: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    structured: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # prices, json-ld, meta
    raw_z: Mapped[bytes | None] = mapped_column(LargeBinary)  # zlib-compressed body, pruned over time
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    fetch_ms: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("ix_source_snapshots_source_fetched", "source_id", "fetched_at"),)


class DomainPolicy(Base):
    __tablename__ = "domain_policies"
    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    robots_txt: Mapped[str | None] = mapped_column(Text)
    robots_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crawl_delay: Mapped[float | None] = mapped_column(Float)
    min_interval_seconds: Mapped[float | None] = mapped_column(Float)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    block_reason: Mapped[str | None] = mapped_column(Text)
    block_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_render: Mapped[bool] = mapped_column(Boolean, default=False)
    denylisted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = updated_at_col()


class WatchSourceState(Base):
    """What a given watch last saw on a given source (its own view, after selectors/normalisation)."""

    __tablename__ = "watch_source_state"
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), primary_key=True
    )
    source_url: Mapped[str] = mapped_column(Text, primary_key=True)
    view_hash: Mapped[str] = mapped_column(String(64))
    view_text: Mapped[str] = mapped_column(Text)
    items: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    numbers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = updated_at_col()


class Check(Base):
    """Scheduling unit. Kept narrow because the scheduler scans it constantly."""

    __tablename__ = "checks"
    id: Mapped[uuid.UUID] = pk_uuid()
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), unique=True
    )
    interval_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(32))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    consecutive_failures: Mapped[int] = mapped_column(SmallInteger, default=0)
    priority: Mapped[int] = mapped_column(SmallInteger, default=0)
    __table_args__ = (
        Index("ix_checks_due", "next_run_at", postgresql_where=text("enabled")),
    )
