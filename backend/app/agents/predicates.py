"""Deterministic predicate evaluation: decides many checks without any LLM call."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.fetch.diff import TextDiff
from app.fetch.extract import find_prices, parse_price
from app.schemas.spec import Predicate

MAX_REGEX_INPUT = 100_000


@dataclass
class ViewContext:
    text: str
    diff: TextDiff | None
    new_items: list[dict[str, str]]
    structured: dict[str, Any]
    changed: bool


@dataclass
class PredicateOutcome:
    passed: bool
    explanations: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    evidence: str | None = None


def _scope_text(p: Predicate, ctx: ViewContext) -> str:
    if p.scope == "added":
        return "\n".join(ctx.diff.added) if ctx.diff else ""
    if p.scope == "new_items":
        return "\n".join(i.get("text", "") for i in ctx.new_items)
    return ctx.text


def _find_line(text: str, needle: str) -> str | None:
    low = needle.lower()
    for line in text.splitlines():
        if low in line.lower():
            return line.strip()[:300]
    return None


def current_price(ctx: ViewContext) -> tuple[float | None, str]:
    for prod in ctx.structured.get("products", []) or []:
        if isinstance(prod, dict) and prod.get("price"):
            return float(prod["price"]), "structured product data"
    meta = ctx.structured.get("meta") or {}
    for k in ("product:price:amount", "og:price:amount", "price"):
        if meta.get(k):
            v = parse_price(str(meta[k]))
            if v:
                return v, f"page metadata ({k})"
    prices = find_prices(ctx.text, limit=5)
    if prices:
        return prices[0], "first price on the page"
    return None, "no price found"


def availability(ctx: ViewContext) -> str | None:
    for prod in ctx.structured.get("products", []) or []:
        if isinstance(prod, dict) and prod.get("availability"):
            return str(prod["availability"])
    meta = ctx.structured.get("meta") or {}
    return meta.get("product:availability") or meta.get("og:availability")


_OOS = re.compile(r"\b(out of stock|sold out|currently unavailable|notify me|coming soon|not available)\b", re.I)
_INSTOCK = re.compile(r"\b(add to cart|buy now|in stock|add to bag|available now)\b", re.I)


def _number_near(label: str, text: str) -> float | None:
    rx = re.compile(re.escape(label) + r"[^\d\n]{0,25}([\d,]+(?:\.\d+)?)", re.I)
    m = rx.search(text[:MAX_REGEX_INPUT])
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def eval_predicate(p: Predicate, ctx: ViewContext) -> PredicateOutcome:
    text = _scope_text(p, ctx)
    low = text.lower()
    if p.type == "contains_any":
        hits = [v for v in p.values if v.lower() in low]
        if hits:
            return PredicateOutcome(True, [f"found '{hits[0]}'"], {"matched_terms": hits}, _find_line(text, hits[0]))
        return PredicateOutcome(False, [f"none of {p.values[:5]} found in {p.scope}"])
    if p.type == "contains_all":
        missing = [v for v in p.values if v.lower() not in low]
        if not missing:
            return PredicateOutcome(True, ["all terms present"], {"matched_terms": p.values},
                                    _find_line(text, p.values[0]))
        return PredicateOutcome(False, [f"missing {missing[:5]}"])
    if p.type == "not_contains":
        hits = [v for v in p.values if v.lower() in low]
        if hits:
            return PredicateOutcome(False, [f"excluded term '{hits[0]}' present"])
        return PredicateOutcome(True, ["no excluded terms"])
    if p.type == "regex":
        assert p.pattern
        m = re.search(p.pattern, text[:MAX_REGEX_INPUT], re.I | re.M)
        if m:
            return PredicateOutcome(True, [f"pattern matched '{m.group(0)[:80]}'"], {"match": m.group(0)[:200]},
                                    _find_line(text, m.group(0)) or m.group(0)[:300])
        return PredicateOutcome(False, ["pattern not found"])
    if p.type in ("price_below", "price_above"):
        price, how = current_price(ctx)
        if price is None:
            return PredicateOutcome(False, ["could not find a price on the page"], {"price": None})
        assert p.threshold is not None
        ok = price < p.threshold if p.type == "price_below" else price > p.threshold
        rel = "below" if p.type == "price_below" else "above"
        facts = {"price": price, "price_source": how, "threshold": p.threshold}
        ev = _find_line(ctx.text, f"{int(price):,}") or _find_line(ctx.text, str(int(price)))
        return PredicateOutcome(
            ok, [f"current price ₹{price:,.0f} ({how}) is {'' if ok else 'not '}{rel} ₹{p.threshold:,.0f}"],
            facts, ev,
        )
    if p.type in ("number_below", "number_above"):
        assert p.label and p.threshold is not None
        val = _number_near(p.label, text)
        if val is None:
            return PredicateOutcome(False, [f"no number found next to '{p.label}'"])
        ok = val < p.threshold if p.type == "number_below" else val > p.threshold
        return PredicateOutcome(ok, [f"{p.label} = {val:g} vs threshold {p.threshold:g}"],
                                {"value": val, "label": p.label}, _find_line(text, p.label))
    if p.type == "new_items":
        items = ctx.new_items
        if p.values:
            items = [i for i in items if any(v.lower() in i.get("text", "").lower() for v in p.values)]
        if items:
            return PredicateOutcome(True, [f"{len(items)} new item(s): '{items[0].get('text', '')[:80]}'"],
                                    {"new_items": items[:20]}, items[0].get("text", "")[:300])
        return PredicateOutcome(False, ["no new matching items"])
    if p.type == "text_changed":
        if ctx.changed and ctx.diff and not ctx.diff.is_empty:
            first = (ctx.diff.added or ctx.diff.removed)[0]
            return PredicateOutcome(True, ["page content changed"], {}, first[:300])
        return PredicateOutcome(False, ["no change"])
    if p.type == "in_stock":
        av = availability(ctx)
        if av:
            ok = av.lower() in ("instock", "in_stock", "limitedavailability", "onlineonly", "presale", "in stock")
            return PredicateOutcome(ok, [f"availability: {av}"], {"availability": av})
        if _INSTOCK.search(ctx.text) and not _OOS.search(ctx.text):
            m = _INSTOCK.search(ctx.text)
            return PredicateOutcome(True, ["buy/add-to-cart text present"], {"availability": "InStock"},
                                    _find_line(ctx.text, m.group(0)) if m else None)
        return PredicateOutcome(False, ["appears out of stock"], {"availability": "OutOfStock"})
    return PredicateOutcome(False, [f"unknown predicate {p.type}"])


def eval_all(preds: list[Predicate], ctx: ViewContext) -> PredicateOutcome:
    """All predicates must pass (AND). Facts/explanations are merged for the live view and alert."""
    if not preds:
        return PredicateOutcome(True, ["no rules"])
    out = PredicateOutcome(True)
    for p in preds:
        r = eval_predicate(p, ctx)
        out.explanations.extend(r.explanations)
        out.facts.update(r.facts)
        if r.evidence and not out.evidence and p.type != "not_contains":
            out.evidence = r.evidence
        if not r.passed:
            out.passed = False
            break
    return out
