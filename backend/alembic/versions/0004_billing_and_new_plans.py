"""New plan limits and prices, INR prices, and billing columns on profiles.

Revision ID: 0004_billing_and_new_plans
Revises: 0003_alembic_version_rls
"""

import json

from alembic import op

revision = "0004_billing_and_new_plans"
down_revision = "0003_alembic_version_rls"
branch_labels = None
depends_on = None

# (id, usd_month, usd_year, inr_month, inr_year, limits, features)
PLANS = [
    ("free", 0, 0, 0, 0,
     {"max_watches": 5, "max_subscriptions": 20, "min_interval_seconds": 21600, "acts_per_month": 5,
      "intake_per_day": 2, "run_now_per_day": 3, "llm_tokens_per_day": 8000, "retention_days": 30,
      "max_sources_per_watch": 2, "max_alerts_per_hour": 6, "checks_per_month": 1000},
     {"channels": ["email", "push", "telegram"], "auto_tune": False, "js_render": False, "api_tokens": False,
      "webhooks": False, "per_watch_channels": False, "public_watches": True}),
    ("plus", 9, 79, 449, 3999,
     {"max_watches": 25, "max_subscriptions": 100, "min_interval_seconds": 3600, "acts_per_month": 30,
      "intake_per_day": 8, "run_now_per_day": 20, "llm_tokens_per_day": 60000, "retention_days": 90,
      "max_sources_per_watch": 3, "max_alerts_per_hour": 20, "checks_per_month": 20000},
     {"channels": ["email", "push", "telegram"], "auto_tune": True, "js_render": True, "api_tokens": False,
      "webhooks": False, "per_watch_channels": True, "public_watches": True}),
    ("pro", 19, 169, 949, 8499,
     {"max_watches": 120, "max_subscriptions": 500, "min_interval_seconds": 900, "acts_per_month": 150,
      "intake_per_day": 20, "run_now_per_day": 100, "llm_tokens_per_day": 200000, "retention_days": 365,
      "max_sources_per_watch": 5, "max_alerts_per_hour": 60, "checks_per_month": 100000},
     {"channels": ["email", "push", "telegram", "webhook"], "auto_tune": True, "js_render": True,
      "api_tokens": True, "webhooks": True, "per_watch_channels": True, "public_watches": True}),
]

OLD_PLANS = [
    ("free", 0, 0, {"max_watches": 5, "max_subscriptions": 25, "min_interval_seconds": 21600, "acts_per_month": 20,
                    "intake_per_day": 10, "run_now_per_day": 3, "llm_tokens_per_day": 150000, "retention_days": 30,
                    "max_sources_per_watch": 2, "max_alerts_per_hour": 6}),
    ("plus", 2, 20, {"max_watches": 30, "max_subscriptions": 150, "min_interval_seconds": 3600, "acts_per_month": 200,
                     "intake_per_day": 40, "run_now_per_day": 20, "llm_tokens_per_day": 1000000, "retention_days": 180,
                     "max_sources_per_watch": 3, "max_alerts_per_hour": 20}),
    ("pro", 6, 60, {"max_watches": 150, "max_subscriptions": 1000, "min_interval_seconds": 900, "acts_per_month": 1500,
                    "intake_per_day": 100, "run_now_per_day": 100, "llm_tokens_per_day": 5000000, "retention_days": 730,
                    "max_sources_per_watch": 5, "max_alerts_per_hour": 60}),
]


def upgrade() -> None:
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS price_inr_month numeric(10,2) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS price_inr_year numeric(10,2) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS billing_customer_id varchar(64)")
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS billing_subscription_id varchar(64)")
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS billing_interval varchar(8)")
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS billing_status varchar(16)")
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS billing_cancel_at_period_end boolean NOT NULL DEFAULT false")
    op.execute("CREATE INDEX IF NOT EXISTS ix_profiles_billing_customer_id ON profiles (billing_customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_profiles_billing_subscription_id ON profiles (billing_subscription_id)")
    for pid, um, uy, im, iy, limits, features in PLANS:
        op.execute(
            "UPDATE plans SET price_usd_month = %s, price_usd_year = %s, price_inr_month = %s, price_inr_year = %s, "
            "limits = '%s'::jsonb, features = '%s'::jsonb WHERE id = '%s'"
            % (um, uy, im, iy, json.dumps(limits), json.dumps(features), pid)
        )


def downgrade() -> None:
    for pid, um, uy, limits in OLD_PLANS:
        op.execute(
            "UPDATE plans SET price_usd_month = %s, price_usd_year = %s, limits = '%s'::jsonb WHERE id = '%s'"
            % (um, uy, json.dumps(limits), pid)
        )
    op.execute("DROP INDEX IF EXISTS ix_profiles_billing_subscription_id")
    op.execute("DROP INDEX IF EXISTS ix_profiles_billing_customer_id")
    for col in ("billing_cancel_at_period_end", "billing_status", "billing_interval", "billing_subscription_id",
                "billing_customer_id"):
        op.execute(f"ALTER TABLE profiles DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS price_inr_year")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS price_inr_month")
