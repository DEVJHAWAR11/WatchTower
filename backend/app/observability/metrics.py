"""Prometheus metrics. API exposes /metrics; workers and scheduler expose their own port."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter("wt_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "wt_http_request_seconds", "HTTP latency", ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

FETCH_TOTAL = Counter("wt_fetch_total", "Source fetches by result", ["result"])
FETCH_DURATION = Histogram("wt_fetch_seconds", "Network fetch duration", buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30))

RUNS_TOTAL = Counter("wt_runs_total", "Watch runs", ["outcome", "decided_by"])
RUN_DURATION = Histogram("wt_run_seconds", "Watch run duration", buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120))
ALERTS_TOTAL = Counter("wt_alerts_total", "Alerts fired", ["decided_by"])

LLM_CALLS = Counter("wt_llm_calls_total", "LLM calls", ["model", "purpose", "status"])
LLM_TOKENS = Counter("wt_llm_tokens_total", "LLM tokens", ["model", "kind"])
LLM_COST = Counter("wt_llm_cost_usd_total", "LLM spend in USD", ["model", "purpose"])
LLM_LATENCY = Histogram("wt_llm_seconds", "LLM latency", ["model"], buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32, 64))

SEARCH_CALLS = Counter("wt_search_calls_total", "Web search calls", ["provider", "status"])

NOTIFY_TOTAL = Counter("wt_notifications_total", "Notification deliveries", ["channel", "status"])

SCHED_CLAIMED = Counter("wt_scheduler_claimed_total", "Checks claimed by scheduler")
SCHED_LAG = Histogram(
    "wt_scheduler_lag_seconds", "Delay between a check being due and being claimed",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800),
)
QUEUE_DEPTH = Gauge("wt_queue_depth", "Jobs waiting in queue", ["queue"])
AGENT_NODE_SECONDS = Histogram(
    "wt_agent_node_seconds", "Agent graph node durations", ["graph", "node"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30),
)
