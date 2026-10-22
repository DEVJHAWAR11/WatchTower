"""Public API request/response models (what the frontend consumes)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, time
from typing import Any, Literal, TypeVar
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")
_TZS = available_timezones()
HANDLE_RE = re.compile(r"^[a-z0-9_]{3,32}$")
Channel = Literal["email", "push", "telegram", "webhook"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


# ------------------------------------------------------------------ auth
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)
    redirect_to: str | None = Field(default=None, max_length=500)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
        if classes < 2 or v.lower() in {"password", "password123", "12345678", "qwertyuiop"}:
            raise ValueError("Use a stronger password (mix letters, numbers or symbols).")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4096)


class EmailIn(BaseModel):
    email: EmailStr
    redirect_to: str | None = Field(default=None, max_length=500)


class VerifyOtpIn(BaseModel):
    email: EmailStr
    token: str = Field(min_length=6, max_length=10)
    type: Literal["email", "magiclink", "signup", "recovery"] = "email"


class PasswordUpdateIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class SessionOut(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str | None = None
    user: dict[str, Any] | None = None
    message: str | None = None


# ------------------------------------------------------------------ me / settings
class ProfileOut(Out):
    id: uuid.UUID
    email: str | None
    email_verified: bool
    display_name: str | None
    handle: str | None
    timezone: str
    locale: str
    plan_id: str
    plan_expires_at: datetime | None
    role: str
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    digest_time: time
    default_channels: list[str]
    default_delivery_mode: str
    max_alerts_per_hour: int
    auto_tune: bool
    email_alerts_enabled: bool
    marketing_opt_in: bool
    created_at: datetime


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=80)
    handle: str | None = Field(default=None, max_length=32)
    timezone: str | None = None
    locale: Literal["en-IN", "hi-IN", "en-US", "en-GB"] | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    clear_quiet_hours: bool = False
    digest_time: time | None = None
    default_channels: list[Channel] | None = Field(default=None, min_length=1, max_length=4)
    default_delivery_mode: Literal["instant", "digest"] | None = None
    max_alerts_per_hour: int | None = Field(default=None, ge=1, le=60)
    auto_tune: bool | None = None
    email_alerts_enabled: bool | None = None
    marketing_opt_in: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None and v not in _TZS:
            raise ValueError("Unknown timezone")
        return v

    @field_validator("handle")
    @classmethod
    def _handle(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.lower()
        if not HANDLE_RE.match(v) or v in {"admin", "watchtower", "community", "support", "root", "system"}:
            raise ValueError("Handle must be 3-32 chars: a-z, 0-9, underscore (and not reserved)")
        return v


class PlanOut(BaseModel):
    id: str
    name: str
    price_usd_month: float
    price_usd_year: float
    price_inr_month: float = 0
    price_inr_year: float = 0
    limits: dict[str, Any]
    features: dict[str, Any]


class UsageOut(BaseModel):
    plan: PlanOut
    watches: int
    subscriptions: int
    acts_this_month: int
    intake_today: int
    run_now_today: int
    llm_tokens_today: int
    checks_this_month: int = 0


class CheckoutIn(BaseModel):
    plan_id: Literal["plus", "pro"]
    interval: Literal["month", "year"] = "month"
    currency: Literal["usd", "inr"] = "usd"


class BillingOut(BaseModel):
    enabled: bool
    mode: str
    plan_id: str
    interval: str | None = None
    status: str | None = None
    renews_at: datetime | None = None
    cancel_at_period_end: bool = False
    has_subscription: bool = False


class PlanRequestIn(BaseModel):
    plan_id: Literal["free", "plus", "pro"]
    note: str | None = Field(default=None, max_length=500)


class ApiTokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    expires_in_days: int | None = Field(default=90, ge=1, le=365)


class ApiTokenOut(Out):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


# ------------------------------------------------------------------ intake
class IntakeStartIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class IntakeAnswerIn(BaseModel):
    answers: dict[str, str] = Field(max_length=5)

    @field_validator("answers")
    @classmethod
    def _cap(cls, v: dict[str, str]) -> dict[str, str]:
        return {str(k)[:32]: str(val)[:500] for k, val in v.items()}


class IntakeEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=140)
    condition: str | None = Field(default=None, min_length=3, max_length=600)
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    visibility: Literal["private", "unlisted", "public"] | None = None
    delivery_mode: Literal["instant", "digest"] | None = None
    fire_once: bool | None = None


class IntakeConfirmIn(BaseModel):
    confirm: bool
    edits: IntakeEdits | None = None


class IntakeOut(Out):
    id: uuid.UUID
    query: str
    status: str
    stage: str | None
    view: dict[str, Any]
    rounds: int
    watch_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ watches
class WatchCreateIn(BaseModel):
    """Power-user path: create directly from a spec (the intake agent is the normal path)."""
    title: str = Field(min_length=1, max_length=140)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=48)
    visibility: Literal["private", "unlisted", "public"] = "private"
    delivery_mode: Literal["instant", "digest"] | None = None
    spec: dict[str, Any]


class WatchUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=140)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=48)
    visibility: Literal["private", "unlisted", "public"] | None = None
    default_delivery_mode: Literal["instant", "digest"] | None = None
    auto_tune: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=10)


class SpecUpdateIn(BaseModel):
    spec: dict[str, Any]
    changelog: str = Field(default="Edited by owner", max_length=500)


class SubscriptionPrefsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery_mode: Literal["instant", "digest"] | None = None
    channels: list[Channel] | None = Field(default=None, max_length=4)
    muted: bool | None = None


class OwnerOut(BaseModel):
    handle: str | None
    display_name: str | None
    is_community: bool = False


class WatchOut(Out):
    id: uuid.UUID
    title: str
    description: str | None
    query_text: str
    category_slug: str | None
    kind: str
    tags: list[str]
    visibility: str
    status: str
    status_reason: str | None
    slug: str
    subscriber_count: int
    alert_count: int
    last_alert_at: datetime | None
    moderation_status: str
    auto_tune: bool = True
    default_delivery_mode: str = "instant"
    created_at: datetime
    updated_at: datetime
    is_owner: bool = False
    is_subscribed: bool = False
    owner: OwnerOut | None = None


class PublicWatchOut(Out):
    id: uuid.UUID
    title: str
    description: str | None
    category_slug: str | None
    kind: str
    tags: list[str]
    slug: str
    subscriber_count: int
    alert_count: int
    last_alert_at: datetime | None
    status: str
    created_at: datetime


class VersionOut(Out):
    id: uuid.UUID
    version: int
    spec: dict[str, Any]
    created_by: str
    changelog: str | None
    backtest: dict[str, Any] | None
    created_at: datetime


class RunOut(Out):
    id: uuid.UUID
    trigger: str
    status: str
    outcome: str | None
    decided_by: str | None
    llm_called: bool
    llm_tokens: int
    confidence: float | None
    reason: str | None
    diff_summary: str | None
    error_code: str | None
    alert_id: uuid.UUID | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None


class RunDetailOut(RunOut):
    steps: list[dict[str, Any]]


class ActionOut(Out):
    id: uuid.UUID
    kind: str
    title: str
    description: str | None
    payload: dict[str, Any]
    owner_only: bool
    expires_at: datetime | None
    decision: str | None = None
    result: dict[str, Any] | None = None


class AlertOut(Out):
    id: uuid.UUID
    watch_id: uuid.UUID
    title: str
    summary: str
    key_facts: dict[str, Any]
    evidence: str | None
    source_url: str
    confidence: float | None
    decided_by: str
    act_status: str
    act_result: dict[str, Any]
    created_at: datetime
    my_feedback: bool | None = None
    actions: list[ActionOut] = []


class WatchStateOut(BaseModel):
    watch: WatchOut
    current_version: VersionOut | None
    schedule: dict[str, Any]
    last_run: RunDetailOut | None
    last_alert: AlertOut | None
    stats: dict[str, Any]
    sources: list[dict[str, Any]]
    pending_refinement: dict[str, Any] | None
    my_subscription: dict[str, Any] | None = None


class FeedbackIn(BaseModel):
    relevant: bool
    reason: str | None = Field(default=None, max_length=500)


class RefinementOut(Out):
    id: uuid.UUID
    rationale: str
    changes: list[Any]
    backtest: dict[str, Any]
    status: str
    created_at: datetime
    proposed_spec: dict[str, Any]


class ReportIn(BaseModel):
    reason: Literal["spam", "scam", "harmful", "privacy", "broken", "other"]
    detail: str | None = Field(default=None, max_length=1000)


# ------------------------------------------------------------------ notifications
class PushSubscribeIn(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: dict[str, str]
    user_agent: str | None = Field(default=None, max_length=256)

    @field_validator("keys")
    @classmethod
    def _keys(cls, v: dict[str, str]) -> dict[str, str]:
        if not v.get("p256dh") or not v.get("auth") or len(v["p256dh"]) > 256 or len(v["auth"]) > 64:
            raise ValueError("keys.p256dh and keys.auth are required")
        return {"p256dh": v["p256dh"], "auth": v["auth"]}


class WebhookIn(BaseModel):
    url: str = Field(max_length=2048)


class ChannelsOut(BaseModel):
    email: dict[str, Any]
    push: dict[str, Any]
    telegram: dict[str, Any]
    webhook: dict[str, Any]


class DeliveryOut(Out):
    id: uuid.UUID
    alert_id: uuid.UUID | None
    channel: str
    kind: str
    mode: str
    status: str
    status_reason: str | None
    attempts: int
    created_at: datetime
    sent_at: datetime | None


# ------------------------------------------------------------------ admin
class AdminPlanChangeIn(BaseModel):
    plan_id: Literal["free", "plus", "pro"]
    expires_at: datetime | None = None
    reason: str = Field(max_length=300)


class AdminSuspendIn(BaseModel):
    suspend: bool
    reason: str = Field(max_length=300)


class AdminModerationIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(max_length=300)


class DomainPolicyIn(BaseModel):
    denylisted: bool | None = None
    min_interval_seconds: float | None = Field(default=None, ge=0.5, le=3600)
    needs_render: bool | None = None
    clear_block: bool = False
    notes: str | None = Field(default=None, max_length=500)


class PlanLimitsIn(BaseModel):
    limits: dict[str, int] | None = None
    features: dict[str, Any] | None = None
