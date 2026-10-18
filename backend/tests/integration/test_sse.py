import asyncio
import json
from typing import Any

from app.realtime.events import publish_user, publish_watch
from tests.helpers import make_watch


async def sse(path: str, headers: dict[str, str], *, until: int, timeout: float = 25.0,  # noqa: ASYNC109
              on_ready: Any = None) -> list[dict[str, Any]]:
    """Drive the ASGI app directly and parse SSE frames until `until` named events arrived."""
    from app.main import app

    hdrs = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    raw_path, _, qs = path.partition("?")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": raw_path, "raw_path": raw_path.encode(), "query_string": qs.encode(), "headers": hdrs,
             "client": ("198.51.100.7", 5555), "server": ("api.test", 80), "root_path": ""}
    disconnect = asyncio.Event()
    events: list[dict[str, Any]] = []
    buf = b""
    ready = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(msg: dict[str, Any]) -> None:
        nonlocal buf
        if msg["type"] == "http.response.start":
            events.append({"status": msg["status"]})
            return
        buf += msg.get("body", b"")
        while b"\n\n" in buf:
            frame, buf = buf.split(b"\n\n", 1)
            ev: dict[str, Any] = {}
            for line in frame.decode().splitlines():
                if line.startswith(":"):
                    continue
                k, _, v = line.partition(": ")
                ev[k] = v
            if "event" in ev:
                ev["data"] = json.loads(ev.get("data", "{}"))
                events.append(ev)
                if ev["event"] == "ready":
                    ready.set()
        if sum(1 for e in events if e.get("event") not in (None, "ready")) >= until:
            disconnect.set()

    task = asyncio.create_task(app(scope, receive, send))
    try:
        if on_ready is not None:
            await asyncio.wait_for(ready.wait(), timeout)
            await on_ready()
        await asyncio.wait_for(disconnect.wait(), timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    return events


async def test_sse_live_and_resume(auth, make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    wid = await make_watch(u, {"sources": [{"url": site.set("site.test", "/sse", "<p>x</p>")}], "condition": "abc"})
    h = auth(u)

    async def emit() -> None:
        await publish_watch(wid, "run.started", {"run_id": "r1"})
        await publish_user(u.id, "alert.created", {"alert_id": "a1"})
        await publish_watch(wid, "run.completed", {"run_id": "r1", "outcome": "matched"})

    evs = await sse(f"/v1/stream?watch={wid}", h, until=3, on_ready=emit)
    assert evs[0]["status"] == 200
    named = [e for e in evs if "event" in e and e["event"] != "ready"]
    assert [e["event"] for e in named] == ["run.started", "alert.created", "run.completed"]
    assert named[1]["data"]["scope"] == "user" and named[0]["data"]["scope"] == "watch"
    resume_from = named[1]["id"]  # client saw up to the alert

    # reconnect with Last-Event-ID: only what came after is replayed, then live events continue
    async def emit2() -> None:
        await publish_watch(wid, "run.step", {"node": "fetch"})

    evs2 = await sse(f"/v1/stream?watch={wid}", {**h, "Last-Event-ID": resume_from}, until=2, on_ready=emit2)
    named2 = [e["event"] for e in evs2 if "event" in e and e["event"] != "ready"]
    assert named2 == ["run.completed", "run.step"]


async def test_sse_ticket_auth(client, auth, make_user) -> None:  # noqa: ANN001
    u = await make_user()
    t = (await client.post("/v1/stream/ticket", headers=auth(u))).json()["ticket"]

    async def emit() -> None:
        await publish_user(u.id, "notification", {"title": "hi"})

    evs = await sse(f"/v1/stream?ticket={t}", {}, until=1, on_ready=emit)
    assert [e["event"] for e in evs if "event" in e and e["event"] != "ready"] == ["notification"]


async def test_sse_orders_events_across_streams(auth, make_user, site) -> None:  # noqa: ANN001
    """Events already waiting in several streams are delivered in true global order, not grouped per stream."""
    from app.api.v1.stream import _encode_pos

    u = await make_user()
    wid = await make_watch(u, {"sources": [{"url": site.set("site.test", "/ord", "<p>x</p>")}], "condition": "abc"})
    await publish_watch(wid, "run.started", {})
    await publish_user(u.id, "alert.created", {})
    await publish_watch(wid, "run.completed", {})
    await publish_user(u.id, "delivery.sent", {})
    since = _encode_pos({f"ev:user:{u.id}": "0-0", f"ev:watch:{wid}": "0-0"})
    evs = await sse(f"/v1/stream?watch={wid}&since={since}", auth(u), until=4)
    assert [e["event"] for e in evs if "event" in e and e["event"] != "ready"] == [
        "run.started", "alert.created", "run.completed", "delivery.sent"]
