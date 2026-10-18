"""Scale test: many watches on shared sources through the real scheduler + arq workers.

Default size is CI-friendly. Bigger runs:  WT_LOAD_WATCHES=5000 WT_LOAD_SOURCES=200 pytest tests/load -m slow -s
Checks: every due check runs exactly once, shared sources are fetched once per freshness window, unchanged pages
cost zero LLM calls, changed pages only trigger LLM work for the watches that point at them.
"""

import os
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update

from app.core.db import session_scope
from app.core.ids import uuid7
from app.models import Check, Profile, Run, Subscription, Watch, WatchVersion
from app.schemas.spec import WatchSpec
from app.workers.scheduler import tick
from tests.helpers import keyword_judge

pytestmark = pytest.mark.slow

N_WATCHES = int(os.environ.get("WT_LOAD_WATCHES", "240"))
N_SOURCES = int(os.environ.get("WT_LOAD_SOURCES", "24"))
N_SUBS = int(os.environ.get("WT_LOAD_SUBS_PER_WATCH", "4"))


async def seed(site, owners: list[uuid.UUID]) -> list[str]:  # noqa: ANN001
    urls = [site.set("load.test", f"/p{i}", f"<html><body><h1>Page {i}</h1><p>stable content {i}</p></body></html>")
            for i in range(N_SOURCES)]
    now = datetime.now(UTC)
    async with session_scope() as s:
        for i in range(N_WATCHES):
            url = urls[i % N_SOURCES]
            spec = WatchSpec(sources=[{"url": url}], condition=f"New notice about topic {i % N_SOURCES} appears",
                             keywords=["notice"], interval_seconds=21600)
            wid, vid = uuid7(), uuid7()
            owner = owners[i % len(owners)]
            s.add(Watch(id=wid, owner_id=owner, title=f"w{i}", query_text="q", slug=f"w-{wid.hex}", status="active",
                        visibility="public", moderation_status="approved", noise_signatures=[], eval_state={},
                        subscriber_count=1 + N_SUBS, tags=[]))
            await s.flush()
            s.add(WatchVersion(id=vid, watch_id=wid, version=1, spec=spec.model_dump(mode="json"),
                               spec_hash=spec.spec_hash(), created_by="user"))
            await s.flush()
            await s.execute(update(Watch).where(Watch.id == wid).values(current_version_id=vid))
            s.add(Subscription(user_id=owner, watch_id=wid, role="owner"))
            for k in range(N_SUBS):
                sub = owners[(i + k + 1) % len(owners)]
                if sub != owner:
                    s.add(Subscription(user_id=sub, watch_id=wid, role="subscriber"))
            s.add(Check(watch_id=wid, interval_seconds=21600, next_run_at=now - timedelta(seconds=1), enabled=True))
    return urls


async def run_all_due(max_jobs: int = 40) -> float:
    from app.workers.main import build_worker, close_worker

    t0 = time.perf_counter()
    while await tick():
        pass
    worker = build_worker("checks")
    worker.burst = True
    worker.max_jobs = max_jobs
    await worker.async_run()
    await close_worker(worker)
    return time.perf_counter() - t0


async def test_scale(site, llm, make_user) -> None:  # noqa: ANN001
    from app.core.config import get_settings

    s = get_settings()
    s.test_private_hosts = [*s.test_private_hosts, "load.test"]
    s.fetch_default_domain_interval_seconds = 0.001  # synthetic site: no politeness delay needed
    owners = [(await make_user(plan="pro")).id for _ in range(max(N_SUBS + 2, 10))]
    urls = await seed(site, owners)
    llm.on("judge", keyword_judge("breaking notice"))
    llm.on("triage", {"plausibly_relevant": True})

    # round 1: baseline for every watch
    elapsed = await run_all_due()
    async with session_scope() as sess:
        runs = (await sess.execute(select(Run.watch_id, Run.outcome))).all()
    assert len(runs) == N_WATCHES, "every due watch ran exactly once"
    assert Counter(o for _, o in runs) == {"baseline": N_WATCHES}
    fetches = sum(v for k, v in site.hits.items() if k.startswith("load.test/p"))
    assert fetches == N_SOURCES, f"shared sources fetched once each, got {fetches}"
    print(f"\nround1: {N_WATCHES} runs in {elapsed:.1f}s ({N_WATCHES / elapsed:.1f} runs/s), {fetches} fetches")

    # round 2: half the pages change; the rest are unchanged
    changed = set(range(0, N_SOURCES, 2))
    for i in changed:
        site.set("load.test", f"/p{i}", f"<html><body><h1>Page {i}</h1><p>stable content {i}</p>"
                                        f"<p>Breaking notice for topic {i}</p></body></html>")
    async with session_scope() as sess:
        await sess.execute(update(Check).values(next_run_at=datetime.now(UTC) - timedelta(seconds=1)))
        await sess.execute(text("UPDATE sources SET last_fetched_at = now() - interval '1 hour'"))
    elapsed2 = await run_all_due()
    async with session_scope() as sess:
        r2 = (await sess.execute(select(Run.outcome, func.count()).where(Run.outcome != "baseline")
                                 .group_by(Run.outcome))).all()
        per_watch = (await sess.execute(select(Run.watch_id, func.count()).group_by(Run.watch_id))).all()
    outcomes = dict(r2)
    affected = sum(1 for i in range(N_WATCHES) if (i % N_SOURCES) in changed)
    assert outcomes.get("matched", 0) == affected
    assert outcomes.get("skipped_unchanged", 0) == N_WATCHES - affected
    assert all(c == 2 for _, c in per_watch), "no duplicate runs"
    assert llm.count("judge") == affected  # zero AI calls for unchanged pages
    print(f"round2: {N_WATCHES} runs in {elapsed2:.1f}s; judge calls={llm.count('judge')} "
          f"(AI skipped for {N_WATCHES - affected}/{N_WATCHES} = {(N_WATCHES - affected) / N_WATCHES:.0%})")
    _ = (Profile, urls)
