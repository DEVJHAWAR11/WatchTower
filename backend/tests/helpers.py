from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select

from app.core.db import session_scope
from app.models import Alert, Check, Profile, Run, Watch
from app.schemas.spec import WatchSpec
from app.services.plans import plan_for
from app.services.watches import create_watch


async def make_watch(owner: Profile, spec: dict[str, Any], title: str = "Test watch", **kw: Any) -> uuid.UUID:
    async with session_scope() as s:
        prof = await s.get(Profile, owner.id)
        plan = await plan_for(s, prof)
        w = await create_watch(s, owner=prof, plan=plan, spec=WatchSpec.model_validate(spec), title=title,
                               query_text=kw.pop("query_text", title), **kw)
        return w.id


async def runs_of(watch_id: uuid.UUID) -> list[Run]:
    async with session_scope() as s:
        return list((await s.execute(select(Run).where(Run.watch_id == watch_id).order_by(Run.started_at))).scalars())


async def alerts_of(watch_id: uuid.UUID) -> list[Alert]:
    async with session_scope() as s:
        return list((await s.execute(select(Alert).where(Alert.watch_id == watch_id).order_by(Alert.created_at))).scalars())


async def get_watch(watch_id: uuid.UUID) -> Watch:
    async with session_scope() as s:
        w = await s.get(Watch, watch_id)
        s.expunge(w)
        return w


async def get_check(watch_id: uuid.UUID) -> Check:
    async with session_scope() as s:
        c = (await s.execute(select(Check).where(Check.watch_id == watch_id))).scalar_one()
        s.expunge(c)
        return c


def section(user_prompt: str, label: str) -> str:
    """Extract a fenced untrusted block (e.g. DIFF/PAGE) from a prompt built by app.agents.prompts."""
    m = re.search(rf"<<<BEGIN_UNTRUSTED_{label}_[0-9A-F]+>>>\n(.*?)\n<<<END_UNTRUSTED_{label}_", user_prompt, re.S)
    return m.group(1) if m else ""


def keyword_judge(keyword: str, *, title: str = "Match found", event_key: str | None = None,
                  confidence: float = 0.9):  # noqa: ANN201
    """A deterministic judge: condition met iff `keyword` appears in the DIFF/ITEMS/PAGE sections."""

    def handler(system: str, user: str) -> dict[str, Any]:
        text = "\n".join(section(user, lab) for lab in ("DIFF", "ITEMS", "PAGE"))
        for line in text.splitlines():
            if keyword.lower() in line.lower():
                quote = line.lstrip("+- ").strip()[:150]
                return {"condition_met": True, "confidence": confidence, "reason": f"found {keyword}",
                        "evidence_quote": quote, "title": title, "summary": f"{keyword} appeared",
                        "key_facts": [{"name": "line", "value": quote}], "event_key": event_key or quote}
        return {"condition_met": False, "confidence": 0.9, "reason": "keyword absent", "evidence_quote": "",
                "title": "", "summary": "", "key_facts": [], "event_key": ""}

    return handler
