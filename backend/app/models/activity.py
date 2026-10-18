from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, pk_uuid, updated_at_col


class Run(Base):
    """One execution of a watch's check. `steps` is the per-node trace shown in the live view."""

    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = pk_uuid()
    watch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")  # schedule | manual | dry_run
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | completed | failed
    # skipped_unchanged | no_match | matched | duplicate | error | blocked | deferred
    outcome: Mapped[str | None] = mapped_column(String(24))
    # hash | noise | rule | triage | llm | cache | none
    decided_by: Mapped[str | None] = mapped_column(String(16))
    llm_called: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    diff_summary: Mapped[str | None] = mapped_column(Text)
    snapshot_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    steps: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_detail: Mapped[str | None] = mapped_column(Text)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = created_at_col()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (Index("ix_runs_watch_started", "watch_id", "started_at"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = pk_uuid()
    watch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    fingerprint: Mapped[str] = mapped_column(String(64))
    event_key: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    key_facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence: Mapped[str | None] = mapped_column(Text)
    context_excerpt: Mapped[str | None] = mapped_column(Text)  # what the judge saw; used for backtests
    source_url: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    decided_by: Mapped[str] = mapped_column(String(16), default="llm")
    act_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|completed|failed|skipped|timeout
    act_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notify_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|fanned_out
    created_at: Mapped[datetime] = created_at_col()
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("watch_id", "fingerprint"),
        Index("ix_alerts_watch_created", "watch_id", "created_at"),
    )


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    id: Mapped[uuid.UUID] = pk_uuid()
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16))  # email | push | telegram | webhook
    kind: Mapped[str] = mapped_column(String(16), default="alert")  # alert | digest | reminder | system
    mode: Mapped[str] = mapped_column(String(16), default="instant")  # instant | digest
    # pending | held | sending | sent | failed | skipped | digested
    status: Mapped[str] = mapped_column(String(16), default="pending")
    status_reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # for system/reminder/digest kinds
    dedup_key: Mapped[str] = mapped_column(String(128))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (
        UniqueConstraint("dedup_key", "channel", name="uq_alert_deliveries_dedup_channel"),
        Index("ix_deliveries_user_status", "user_id", "status"),
        Index("ix_deliveries_held", "scheduled_for", postgresql_where=text("status = 'held'")),
    )


class ProposedAction(Base):
    __tablename__ = "proposed_actions"
    id: Mapped[uuid.UUID] = pk_uuid()
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    # add_to_calendar | set_reminder | open_link | draft_email | create_followup_watch | adjust_threshold
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    owner_only: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class ActionDecision(Base):
    __tablename__ = "action_decisions"
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposed_actions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16))  # approved | rejected | executed | failed
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    decided_at: Mapped[datetime] = created_at_col()


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"))
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"))
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | sent | cancelled
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (Index("ix_reminders_due", "remind_at", postgresql_where=text("status = 'pending'")),)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[uuid.UUID] = pk_uuid()
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"))
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"))
    relevant: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    __table_args__ = (UniqueConstraint("alert_id", "user_id"),)


class RefinementProposal(Base):
    __tablename__ = "refinement_proposals"
    id: Mapped[uuid.UUID] = pk_uuid()
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), index=True
    )
    from_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    proposed_spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rationale: Mapped[str] = mapped_column(Text)
    changes: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    backtest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|applied|rejected|superseded
    applied_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = created_at_col()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AbuseReport(Base):
    __tablename__ = "abuse_reports"
    id: Mapped[uuid.UUID] = pk_uuid()
    reporter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"))
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(32))  # spam | scam | harmful | privacy | broken | other
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | actioned | dismissed
    created_at: Mapped[datetime] = created_at_col()
    __table_args__ = (UniqueConstraint("reporter_id", "watch_id"),)


class IntakeSession(Base):
    """API-facing mirror of a LangGraph intake thread (the graph state lives in the checkpointer)."""

    __tablename__ = "intake_sessions"
    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    # queued | running | awaiting_user | proposed | creating | created | refused | rejected | failed | expired
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str | None] = mapped_column(String(32))
    view: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # what the frontend renders
    rounds: Mapped[int] = mapped_column(SmallInteger, default=0)
    watch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
