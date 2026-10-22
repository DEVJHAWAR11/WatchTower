"""Application settings. Everything comes from environment variables (or a .env file)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WT_", extra="ignore")

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    app_name: str = "Watchtower"
    public_base_url: str = "http://localhost:8000"  # API base, used in links (unsubscribe, ics)
    frontend_base_url: str = "http://localhost:3000"
    cors_origins: CsvList = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: str = "INFO"
    log_json: bool = True

    # --- datastores ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:15432/watchtower"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    redis_url: str = "redis://127.0.0.1:6379/0"

    # --- auth (Supabase) ---
    supabase_url: str = "http://localhost:54321"
    supabase_anon_key: SecretStr = SecretStr("")
    supabase_service_role_key: SecretStr = SecretStr("")
    supabase_jwt_secret: SecretStr = SecretStr("")  # only for legacy HS256 projects
    supabase_jwks_url: str | None = None  # defaults to {supabase_url}/auth/v1/.well-known/jwks.json
    jwt_audience: str = "authenticated"
    jwt_leeway_seconds: int = 30
    auth_hook_secret: SecretStr = SecretStr("")  # Supabase "before user created" hook (Standard Webhooks)

    # --- secrets for our own signing/encryption ---
    signing_secret: SecretStr = SecretStr("dev-signing-secret-change-me-0123456789abcdef")
    encryption_key: SecretStr = SecretStr("")  # Fernet key; derived from signing_secret if empty

    # --- LLM (Groq) ---
    groq_api_key: SecretStr = SecretStr("")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_model_fast: str = "openai/gpt-oss-20b"
    llm_model_smart: str = "openai/gpt-oss-120b"
    # Empty = fall back to the other tier's model (each Groq model has its own quota, so this doubles headroom).
    llm_model_fallback: str = ""
    llm_strict_schema_models: CsvList = Field(
        default_factory=lambda: ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    )
    llm_reasoning_models: CsvList = Field(
        default_factory=lambda: ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    )
    llm_timeout_seconds: float = 45.0
    llm_max_concurrency: int = 16
    # USD per 1M tokens (input, output). Used for cost accounting and the budget breaker.
    llm_pricing: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "openai/gpt-oss-20b": (0.075, 0.30),
            "openai/gpt-oss-120b": (0.15, 0.60),
            "llama-3.3-70b-versatile": (0.59, 0.79),
            "llama-3.1-8b-instant": (0.05, 0.08),
        }
    )
    llm_daily_budget_usd: float = 10.0  # soft cap: free tier degrades to rule-only beyond this
    llm_hard_budget_multiplier: float = 2.0  # hard cap for everyone
    llm_cache_ttl_seconds: int = 7 * 24 * 3600
    # Groq account limits per model: (requests/day, tokens/minute). "*" is the default for unlisted models.
    # Defaults are the free tier; raise them when the account is upgraded (responses re-sync these anyway).
    llm_rate_limits: dict[str, tuple[int, int]] = Field(
        default_factory=lambda: {"*": (1000, 8000)}
    )
    llm_interactive_reserve_fraction: float = 0.15  # share of daily requests background checks may not touch
    llm_max_wait_interactive_s: float = 20.0
    llm_max_wait_background_s: float = 30.0
    judge_min_confidence: float = 0.6
    triage_min_diff_chars: int = 1500

    # --- search ---
    tavily_api_key: SecretStr = SecretStr("")
    brave_api_key: SecretStr = SecretStr("")
    search_cache_ttl_seconds: int = 24 * 3600
    search_daily_budget_calls: int = 60  # all providers; spreads the monthly credits over the month
    # Credits per calendar month per provider (Tavily free = 1000; Brave free = 2000). Remove a key for no cap.
    search_monthly_budget: dict[str, int] = Field(default_factory=lambda: {"tavily": 1000, "brave": 2000})

    # --- fetching ---
    fetch_user_agent: str = "WatchtowerBot/1.0 (+https://watchtower.app/bot)"
    fetch_timeout_seconds: float = 20.0
    fetch_max_bytes: int = 5 * 1024 * 1024
    fetch_max_redirects: int = 5
    fetch_respect_robots: bool = True
    fetch_default_domain_interval_seconds: float = 2.0
    render_enabled: bool = False
    render_max_concurrency: int = 2
    # Hostnames allowed to resolve to private IPs. ONLY honoured when env == "test".
    test_private_hosts: CsvList = Field(default_factory=list)

    # --- notifications ---
    email_provider: Literal["resend", "smtp", "console"] = "console"
    resend_api_key: SecretStr = SecretStr("")
    resend_webhook_secret: SecretStr = SecretStr("")
    email_from: str = "Watchtower <alerts@watchtower.app>"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = True
    vapid_private_key: SecretStr = SecretStr("")
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@watchtower.app"
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_bot_username: str = "WatchtowerAlertsBot"
    telegram_webhook_secret: SecretStr = SecretStr("")
    telegram_api_base: str = "https://api.telegram.org"
    default_max_alerts_per_hour: int = 6

    # --- scheduler / workers ---
    scheduler_tick_seconds: float = 5.0
    scheduler_batch_size: int = 500
    scheduler_lease_seconds: int = 600
    scheduler_max_queue_depth: int = 20000
    check_max_backoff_seconds: int = 24 * 3600
    check_failure_threshold: int = 5
    act_timeout_seconds: float = 90.0
    fanout_chunk_size: int = 500
    worker_metrics_port: int = 9100
    # Run the arq workers and the scheduler inside the API process (single-instance hosts such as Render free).
    embedded_workers: bool = False
    embedded_max_jobs: int = 4

    # --- observability ---
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "watchtower"
    metrics_token: SecretStr = SecretStr("")  # if set, /metrics requires "Authorization: Bearer <token>"

    # --- API limits ---
    max_request_body_bytes: int = 1024 * 1024
    disposable_email_domains: CsvList = Field(
        default_factory=lambda: [
            "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "yopmail.com",
            "trashmail.com", "sharklasers.com", "getnada.com", "temp-mail.org", "dispostable.com",
            "maildrop.cc", "fakeinbox.com", "throwawaymail.com", "mintemail.com", "mohmal.com",
        ]
    )
    public_watch_report_threshold: int = 3

    @field_validator("cors_origins", "test_private_hosts", "disposable_email_domains", "llm_strict_schema_models",
                     "llm_reasoning_models", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            if v.strip().startswith("["):
                import json

                return json.loads(v)
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @property
    def jwks_url(self) -> str:
        return self.supabase_jwks_url or f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def is_test(self) -> bool:
        return self.env == "test"

    @property
    def sync_database_url(self) -> str:
        """psycopg-style URL (LangGraph checkpointer, Alembic offline)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
