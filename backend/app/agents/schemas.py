"""Structured LLM output schemas for every agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class _Base(BaseModel):
    model_config = {"extra": "ignore"}


class KeyFact(_Base):
    name: str = Field(max_length=60)
    value: str = Field(max_length=400)


def _facts_to_dict(facts: list[KeyFact]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in facts[:15]:
        k = " ".join(f.name.split())[:60]
        if k and f.value.strip():
            out[k] = f.value.strip()[:400]
    return out


# ---------------- evaluation ----------------
class TriageOut(_Base):
    plausibly_relevant: bool
    reason: str = Field(default="", max_length=300)


class JudgeOut(_Base):
    condition_met: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=600)
    evidence_quote: str = Field(default="", max_length=600)
    title: str = Field(default="", max_length=140)
    summary: str = Field(default="", max_length=800)
    key_facts: list[KeyFact] = Field(default_factory=list, max_length=15)
    event_key: str = Field(default="", max_length=200)
    is_repeat_of_known_event: bool = False

    def facts_dict(self) -> dict[str, str]:
        return _facts_to_dict(self.key_facts)


# ---------------- intake ----------------
class SuggestedPredicate(_Base):
    type: Literal["contains_any", "contains_all", "not_contains", "price_below", "price_above", "new_items",
                  "in_stock", "number_below", "number_above", "regex", "text_changed"]
    values: list[str] = Field(default_factory=list, max_length=15)
    threshold: float | None = None
    label: str | None = None
    pattern: str | None = None
    scope: Literal["page", "added", "new_items"] = "page"


class ClarifyingQuestion(_Base):
    id: str = Field(max_length=32)
    question: str = Field(max_length=300)
    options: list[str] = Field(default_factory=list, max_length=6)


class IntakeAnalysis(_Base):
    safety: Literal["allowed", "refuse"]
    safety_category: Literal["none", "stalking_private_person", "doxxing", "illegal", "harassment", "malware_or_hacking",
                             "adult", "self_harm", "spam_or_abuse", "other"] = "none"
    safety_reason: str = Field(default="", max_length=400)
    feasibility: Literal["ok", "vague", "impossible", "contradictory", "past_event", "not_web_observable",
                         "needs_login", "too_broad"]
    feasibility_reason: str = Field(default="", max_length=500)
    alternatives: list[str] = Field(default_factory=list, max_length=4)
    questions: list[ClarifyingQuestion] = Field(default_factory=list, max_length=3)
    title: str = Field(default="", max_length=120)
    kind: Literal["job", "exam_result", "exam_notification", "admission", "scholarship", "ipo", "price_drop",
                  "restock", "release", "news", "event", "generic"] = "generic"
    category: str = Field(default="other", max_length=48)
    condition: str = Field(default="", max_length=600)
    entities: list[str] = Field(default_factory=list, max_length=8)
    company: str | None = Field(default=None, max_length=80)
    search_queries: list[str] = Field(default_factory=list, max_length=4)
    predicates: list[SuggestedPredicate] = Field(default_factory=list, max_length=6)
    predicate_mode: Literal["decide", "prefilter", "none"] = "none"
    keywords: list[str] = Field(default_factory=list, max_length=15)
    extract_fields: list[str] = Field(default_factory=list, max_length=10)
    act_tasks: list[Literal["extract_details", "deadlines", "compare", "checklist", "draft_message"]] = Field(
        default_factory=list, max_length=5
    )
    suggested_interval_minutes: int = Field(default=360, ge=5, le=10080)
    fire_once: bool = False
    expires_on: str | None = Field(default=None, max_length=32)

    @field_validator("search_queries", "keywords", "entities", "alternatives", "extract_fields")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return [" ".join(x.split())[:200] for x in v if x and x.strip()]


class SourceRanking(_Base):
    class Choice(_Base):
        index: int = Field(ge=0, le=20)
        relevance: float = Field(ge=0, le=1)
        why: str = Field(default="", max_length=200)
        kind: Literal["page", "json", "feed"] = "page"

    choices: list[Choice] = Field(default_factory=list, max_length=6)
    note: str = Field(default="", max_length=300)


class DryRunOut(_Base):
    already_met: bool
    reason: str = Field(max_length=400)
    evidence_quote: str = Field(default="", max_length=400)


# ---------------- act ----------------
class Deadline(_Base):
    label: str = Field(max_length=120)
    date: str = Field(max_length=40, description="ISO date or datetime, e.g. 2026-11-05 or 2026-11-05T17:00")
    evidence_quote: str = Field(default="", max_length=300)


class ActOut(_Base):
    headline: str = Field(max_length=160)
    what_happened: str = Field(max_length=700)
    key_details: list[KeyFact] = Field(default_factory=list, max_length=15)
    deadlines: list[Deadline] = Field(default_factory=list, max_length=6)
    important_links: list[KeyFact] = Field(default_factory=list, max_length=6, description="name=label, value=URL")
    comparison: str = Field(default="", max_length=800)
    checklist: list[str] = Field(default_factory=list, max_length=10)
    draft_message: str = Field(default="", max_length=1500)
    followup_watch_suggestion: str = Field(default="", max_length=200)

    def details_dict(self) -> dict[str, str]:
        return _facts_to_dict(self.key_details)


# ---------------- refinement ----------------
class RefineOut(_Base):
    new_condition: str = Field(max_length=600)
    add_negative_examples: list[str] = Field(default_factory=list, max_length=5)
    add_positive_examples: list[str] = Field(default_factory=list, max_length=5)
    add_exclude_terms: list[str] = Field(default_factory=list, max_length=8)
    add_require_terms: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(max_length=800)


class BacktestJudgeOut(_Base):
    condition_met: bool
    confidence: float = Field(ge=0, le=1)


# ---------------- moderation ----------------
class ModerationOut(_Base):
    decision: Literal["approve", "reject", "review"]
    category: Literal["ok", "spam", "scam", "adult", "harassment", "privacy", "illegal", "low_quality", "other"]
    reason: str = Field(max_length=300)
