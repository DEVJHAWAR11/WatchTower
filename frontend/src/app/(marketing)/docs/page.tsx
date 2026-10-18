import type { Metadata } from "next";
import Link from "next/link";

import { Prose } from "@/components/marketing/prose";

export const metadata: Metadata = {
  title: "API & webhooks",
  description: "Use Watchtower from your own code: personal API tokens, REST endpoints, live Server-Sent Events and signed webhooks.",
  alternates: { canonical: "/docs" },
};

const site = (process.env.NEXT_PUBLIC_SITE_URL || "https://watchtower.example").replace(/\/$/, "");

export default function DocsPage() {
  return (
    <Prose title="API & webhooks" kicker="/ Developers">
      <p>
        Everything you can do in the app is available over a JSON API. Personal API tokens and outgoing webhooks are
        part of the <Link href="/pricing">Pro plan</Link>.
      </p>

      <h2>Authentication</h2>
      <p>
        Create a token in <em>Settings → Developer</em>. It&apos;s shown once and starts with <code>wt_</code>. Send it
        as a bearer token:
      </p>
      <pre>
        <code>{`curl ${site}/v1/me/watches \\
  -H "Authorization: Bearer wt_…"`}</code>
      </pre>
      <p>
        Errors share one shape: <code>{`{"error": {"code", "message", "details", "request_id"}}`}</code>. Rate-limited
        requests return <code>429</code> with <code>Retry-After</code>; plan limits return <code>402</code> with
        <code> details.metric</code>.
      </p>

      <h2>Create a watch in plain English</h2>
      <pre>
        <code>{`POST /v1/intake            {"query": "Tell me when SSC CGL 2026 results are out"}
GET  /v1/intake/{id}       → status: running | awaiting_user | proposed | created | rejected
POST /v1/intake/{id}/answer   {"answers": {"<question id>": "…"}}
POST /v1/intake/{id}/confirm  {"confirm": true, "edits": {"interval_minutes": 120}}`}</code>
      </pre>
      <p>
        Send an <code>Idempotency-Key</code> header on <code>POST /v1/intake</code> and <code>POST /v1/watches</code>
        so retries never create duplicates.
      </p>

      <h2>Useful endpoints</h2>
      <table>
        <thead>
          <tr>
            <th>Endpoint</th>
            <th>What it does</th>
          </tr>
        </thead>
        <tbody>
          {[
            ["GET /v1/me/watches", "Your watches and subscriptions"],
            ["GET /v1/watches/{id}/state", "Live view: schedule, last run with steps, last alert, 7-day stats"],
            ["GET /v1/watches/{id}/runs", "Check history (cursor pagination)"],
            ["POST /v1/watches/{id}/run", "Check now (counts against a daily quota)"],
            ["POST /v1/watches/{id}/pause · /resume", "Pause or resume checking"],
            ["GET /v1/alerts", "Alert inbox across all watches"],
            ["POST /v1/alerts/{id}/feedback", "👍/👎 that tunes the watch"],
            ["POST /v1/actions/{id}/approve", "Approve a follow-up action"],
            ["GET /v1/explore", "Community watches (trending, popular, new)"],
            ["POST /v1/watches/{id}/subscribe", "Subscribe to a public watch"],
          ].map(([e, d]) => (
            <tr key={e}>
              <td>
                <code>{e}</code>
              </td>
              <td>{d}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Live updates</h2>
      <p>
        <code>GET /v1/stream?watch={"{id}"}</code> is a Server-Sent Events stream of your own events plus any watches
        you pass (up to 10): <code>run.started</code>, <code>run.step</code>, <code>run.completed</code>,{" "}
        <code>alert.created</code>, <code>intake.updated</code> and more. Reconnect with <code>Last-Event-ID</code>{" "}
        and missed events are replayed.
      </p>

      <h2>Webhooks</h2>
      <p>
        Add an HTTPS endpoint in <em>Settings → Developer</em>. Each alert is POSTed as JSON with an{" "}
        <code>X-Watchtower-Signature: t=…,v1=…</code> header. Verify it before trusting the body:
      </p>
      <pre>
        <code>{`import hmac, hashlib, time

def verify(secret: str, header: str, body: bytes) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    ts = int(parts["t"])
    if abs(time.time() - ts) > 300:          # reject replays
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])`}</code>
      </pre>
      <p>
        Use <code>X-Watchtower-Delivery</code> to de-duplicate retries. Endpoints that keep failing are disabled
        automatically and shown in settings.
      </p>
    </Prose>
  );
}
