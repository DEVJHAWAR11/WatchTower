"""RLS lockdown, Supabase auth link, plans and categories seed.

Revision ID: 0002_security_and_seed
Revises: 57fc721c4856
"""
import json
from collections.abc import Sequence

from alembic import op

revision: str = "0002_security_and_seed"
down_revision: str | None = "57fc721c4856"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = [
    "audit_log", "categories", "domain_policies", "email_suppressions", "llm_usage_daily", "plans", "sources",
    "profiles", "source_snapshots", "api_tokens", "intake_sessions", "push_subscriptions", "telegram_links",
    "usage_counters", "watches", "webhook_endpoints", "abuse_reports", "alerts", "checks", "refinement_proposals",
    "runs", "subscriptions", "watch_source_state", "watch_versions", "alert_deliveries", "feedback",
    "proposed_actions", "reminders", "action_decisions",
]

# Limits are data: change them with an UPDATE, no deploy needed.
PLANS = [
    {
        "id": "free", "name": "Free", "m": 0, "y": 0, "sort": 0,
        "limits": {
            "max_watches": 5, "max_subscriptions": 25, "min_interval_seconds": 21600, "acts_per_month": 20,
            "intake_per_day": 10, "run_now_per_day": 3, "llm_tokens_per_day": 150000, "retention_days": 30,
            "max_sources_per_watch": 2, "max_alerts_per_hour": 6,
        },
        "features": {"channels": ["email", "push", "telegram"], "auto_tune": False, "js_render": False,
                     "api_tokens": False, "webhooks": False, "per_watch_channels": False, "public_watches": True},
    },
    {
        "id": "plus", "name": "Plus", "m": 2, "y": 20, "sort": 1,
        "limits": {
            "max_watches": 30, "max_subscriptions": 150, "min_interval_seconds": 3600, "acts_per_month": 200,
            "intake_per_day": 40, "run_now_per_day": 20, "llm_tokens_per_day": 1000000, "retention_days": 180,
            "max_sources_per_watch": 3, "max_alerts_per_hour": 20,
        },
        "features": {"channels": ["email", "push", "telegram"], "auto_tune": True, "js_render": True,
                     "api_tokens": False, "webhooks": False, "per_watch_channels": True, "public_watches": True},
    },
    {
        "id": "pro", "name": "Pro", "m": 6, "y": 60, "sort": 2,
        "limits": {
            "max_watches": 150, "max_subscriptions": 1000, "min_interval_seconds": 900, "acts_per_month": 1500,
            "intake_per_day": 100, "run_now_per_day": 100, "llm_tokens_per_day": 5000000, "retention_days": 730,
            "max_sources_per_watch": 5, "max_alerts_per_hour": 60,
        },
        "features": {"channels": ["email", "push", "telegram", "webhook"], "auto_tune": True, "js_render": True,
                     "api_tokens": True, "webhooks": True, "per_watch_channels": True, "public_watches": True},
    },
]

CATEGORIES = [
    ("jobs", "Jobs & hiring", "New openings at companies you care about", "briefcase", 1),
    ("placements", "Campus placements", "Placement portals, drives and shortlists", "graduation-cap", 2),
    ("exams-results", "Exams & results", "SSC, UPSC, NTA, boards: notifications, admit cards, results", "file-check", 3),
    ("admissions", "Admissions", "Counselling rounds, cut-offs, application windows", "school", 4),
    ("scholarships", "Scholarships", "NSP, state and private scholarships", "award", 5),
    ("government", "Government notices", "Circulars, tenders, scheme announcements", "landmark", 6),
    ("ipo", "IPOs & markets", "IPO openings, GMP-free official announcements, allotment status", "trending-up", 7),
    ("price-drops", "Price drops", "Products falling below your target price", "tag", 8),
    ("restocks", "Restocks", "Back-in-stock alerts", "package", 9),
    ("tech-releases", "Tech releases", "Software releases, changelogs, launches", "cpu", 10),
    ("news", "News & updates", "Pages and announcements you follow", "newspaper", 11),
    ("events", "Events & tickets", "Ticket drops, registrations, hackathons", "calendar", 12),
    ("other", "Other", "Everything else", "eye", 99),
]


def upgrade() -> None:
    for t in TABLES:
        # RLS on with no policies = deny-all for non-owner roles (Supabase anon/authenticated via PostgREST).
        # The API connects as the table owner and enforces authorisation itself.
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    for p in PLANS:
        op.execute(
            "INSERT INTO plans (id, name, price_usd_month, price_usd_year, limits, features, is_public, sort) "
            f"VALUES ('{p['id']}', '{p['name']}', {p['m']}, {p['y']}, "
            f"'{json.dumps(p['limits'])}'::jsonb, '{json.dumps(p['features'])}'::jsonb, true, {p['sort']}) "
            "ON CONFLICT (id) DO UPDATE SET limits = EXCLUDED.limits, features = EXCLUDED.features"
        )
    for slug, name, desc, icon, sort in CATEGORIES:
        op.execute(
            "INSERT INTO categories (slug, name, description, icon, sort) "
            f"VALUES ('{slug}', '{name}', '{desc}', '{icon}', {sort}) ON CONFLICT (slug) DO NOTHING"
        )
    # A system account that inherits public watches when their owner deletes their account.
    op.execute(
        "INSERT INTO profiles (id, email, email_verified, display_name, handle, timezone, locale, plan_id, role, "
        "status, digest_time, default_channels, default_delivery_mode, max_alerts_per_hour, auto_tune, "
        "email_alerts_enabled, marketing_opt_in, abuse_score) VALUES "
        "('00000000-0000-0000-0000-000000000001', NULL, true, 'Watchtower Community', 'community', 'Asia/Kolkata', "
        "'en-IN', 'pro', 'user', 'active', '08:00', '[]'::jsonb, 'instant', 0, true, false, false, 0) "
        "ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon';
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated';
          END IF;
          IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'users') THEN
            EXECUTE 'ALTER TABLE profiles ADD CONSTRAINT fk_profiles_auth_users FOREIGN KEY (id)
                     REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM profiles WHERE id = '00000000-0000-0000-0000-000000000001'")
    op.execute("DELETE FROM categories")
    op.execute("DELETE FROM plans")
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
