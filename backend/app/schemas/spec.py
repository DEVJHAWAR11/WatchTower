"""WatchSpec: the compiled, versioned definition of what a watch does."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.fetch.ssrf import SSRFBlocked, validate_url
from app.fetch.urls import canonicalize_url

WatchKind = Literal[
    "job", "exam_result", "exam_notification", "admission", "scholarship", "ipo", "price_drop", "restock",
    "release", "news", "event", "generic",
]
PredicateType = Literal[
    "contains_any", "contains_all", "not_contains", "regex", "price_below", "price_above", "number_below",
    "number_above", "new_items", "text_changed", "in_stock",
]
ActTask = Literal["extract_details", "deadlines", "compare", "checklist", "draft_message"]

_NESTED_QUANT = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)\s*[+*{]")
_BACKREF = re.compile(r"\\[1-9]|\(\?P=|\\k<")


def check_safe_regex(pattern: str) -> str:
    """Reject patterns prone to catastrophic backtracking (ReDoS). Inputs are also length-capped at match time."""
    if len(pattern) > 200:
        raise ValueError("regex too long (max 200 chars)")
    if _NESTED_QUANT.search(pattern):
        raise ValueError("regex has nested quantifiers")
    if _BACKREF.search(pattern):
        raise ValueError("regex backreferences are not allowed")
    if pattern.count("(") > 10 or pattern.count("|") > 20:
        raise ValueError("regex too complex")
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"invalid regex: {e}") from e
    return pattern


class Predicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: PredicateType
    values: list[str] = Field(default_factory=list, max_length=25)
    pattern: str | None = None
    threshold: float | None = None
    label: str | None = Field(default=None, max_length=60)
    scope: Literal["page", "added", "new_items"] = "page"

    @field_validator("values")
    @classmethod
    def _vals(cls, v: list[str]) -> list[str]:
        out = []
        for x in v:
            x = " ".join(str(x).split())[:100]
            if x:
                out.append(x)
        return out

    @field_validator("pattern")
    @classmethod
    def _pattern(cls, v: str | None) -> str | None:
        return check_safe_regex(v) if v else v

    @model_validator(mode="after")
    def _check(self) -> Predicate:
        if self.type in ("contains_any", "contains_all", "not_contains") and not self.values:
            raise ValueError(f"{self.type} needs values")
        if self.type == "regex" and not self.pattern:
            raise ValueError("regex predicate needs a pattern")
        if self.type in ("price_below", "price_above", "number_below", "number_above"):
            if self.threshold is None or not (0 <= self.threshold < 1e12):
                raise ValueError(f"{self.type} needs a sane threshold")
        if self.type in ("number_below", "number_above") and not self.label:
            raise ValueError(f"{self.type} needs a label to find the number")
        return self


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=2048)
    kind: Literal["page", "json", "feed"] = "page"
    selector: str | None = Field(default=None, max_length=300)
    fetch_mode: Literal["http", "render"] = "http"
    label: str | None = Field(default=None, max_length=120)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        canon = canonicalize_url(v)
        try:
            validate_url(canon)
        except SSRFBlocked as e:
            raise ValueError(f"URL not allowed ({e.reason})") from e
        return canon

    @field_validator("selector")
    @classmethod
    def _selector(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if any(c in v for c in ("{", "}", "<", ">>", "\\")) or "javascript" in v.lower():
            raise ValueError("invalid CSS selector")
        return v


class ActSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    tasks: list[ActTask] = Field(default_factory=lambda: ["extract_details", "deadlines"], max_length=5)
    instructions: str | None = Field(default=None, max_length=500)


class WatchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    kind: WatchKind = "generic"
    sources: list[SourceSpec] = Field(min_length=1, max_length=5)
    condition: str = Field(min_length=3, max_length=600)
    predicates: list[Predicate] = Field(default_factory=list, max_length=8)
    # decide: predicates alone decide (no LLM). prefilter: predicates must pass, then the LLM judges.
    # none: LLM judges every meaningful change.
    predicate_mode: Literal["decide", "prefilter", "none"] = "none"
    keywords: list[str] = Field(default_factory=list, max_length=20)
    extract_fields: list[str] = Field(default_factory=list, max_length=12)
    act: ActSpec = Field(default_factory=ActSpec)
    interval_seconds: int = Field(default=21600, ge=300, le=7 * 24 * 3600)
    fire_once: bool = False
    expires_at: datetime | None = None
    dedup_window_days: int = Field(default=30, ge=1, le=365)
    positive_examples: list[str] = Field(default_factory=list, max_length=10)
    negative_examples: list[str] = Field(default_factory=list, max_length=10)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("keywords", "extract_fields", "positive_examples", "negative_examples")
    @classmethod
    def _trim(cls, v: list[str]) -> list[str]:
        return [" ".join(str(x).split())[:300] for x in v if str(x).strip()]

    @model_validator(mode="after")
    def _modes(self) -> WatchSpec:
        if self.predicate_mode != "none" and not self.predicates:
            self.predicate_mode = "none"
        return self

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def spec_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()
