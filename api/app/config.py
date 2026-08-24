from __future__ import annotations

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration sourced from env vars.

    Defaults match local-dev shape; Railway sets the env in production.
    """

    cache_dir: Path = Path.home() / ".sleeper-dynasty" / "cache"
    cors_origins: list[str] = ["http://localhost:3000"]
    chain_cache_ttl_seconds: int = 24 * 3600
    log_level: str = "INFO"
    # Liveness: keep known leagues warm via an in-process scheduler.
    auto_refresh: bool = True
    refresh_interval_seconds: int = 3 * 3600
    llm_model: str | None = None  # env: TRADE_GRADER_LLM_MODEL — overrides all writer defaults
    # LLM-regeneration throttle: within this window since the last LLM pass, the
    # 3h auto-refresh reuses cached stories/blurbs verbatim (new trades still get
    # generated) rather than re-evaluating hashes. Caps regen to ~once/day on top
    # of the coarsened skip-hash. Set 0 to disable the throttle.
    llm_min_interval_seconds: int = 20 * 3600

    # --- Identity / multi-tenant (Phase 0+1) ---
    # Always-set DB URL. Local/CI default is a SQLite file under the cache dir
    # (no Postgres needed to develop); prod overrides to postgresql+asyncpg://...
    # There is no "unset = legacy single-tenant" path — the DB is always on.
    database_url: str = ""
    # Async engine pool sizing (tune for the public product's concurrency).
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Shared HS256 secret. The frontend (NextAuth) mints a backend-facing token
    # signed with this; FastAPI verifies it. Must match the web AUTH_BACKEND_SECRET.
    auth_backend_secret: str = ""
    # Comma-separated emails that get is_admin=True on upsert. Stored as a raw
    # string (a list[str] field would make pydantic-settings JSON-parse the env
    # value); use the ``admin_email_list`` property to read it parsed.
    admin_emails: str = ""
    # Rollout bridge: signed-in users may view this one league without a
    # membership row, so the live site keeps working between Phase 1 and the
    # Phase 2 onboarding flow. Removed once add-league ships.
    allowlisted_league_id: str | None = None
    # Cap on how many leagues one user can import (cost lever — each new league
    # is a first-importer-pays cold build).
    max_leagues_per_user: int = 10
    # Global LLM spend ceiling per calendar month (USD). When month-to-date
    # spend reaches this, refreshes still run but skip all LLM generation
    # (stories/blurbs), reusing cached prose. 0 = no cap.
    llm_monthly_budget_usd: float = 0.0
    # Default per-user/route rate limits (slowapi).
    rate_limit_default: str = "120/minute"
    rate_limit_discovery: str = "15/minute"
    # Social-card reads. These four endpoints are reachable WITHOUT a session
    # (see app/auth/deps.py's og-card principal), and each one a crawler hits
    # costs a backend read plus a Satori rasterization in the web service. The
    # limit applies ONLY to og-card traffic — signed-in users on the same
    # endpoints are exempt, because these are the main app's own routes and a
    # shared ceiling would throttle real usage. Keyed per league.
    rate_limit_og_card: str = "30/minute"
    # Error monitoring. When set, the backend initializes Sentry; inert if blank.
    sentry_dsn: str = ""

    # --- Backups (Cloudflare R2) ---
    # Inert unless enabled AND all four R2 values are present (the Sentry
    # DSN-gating pattern). The token is PutObject-scoped: nothing here ever
    # reads or deletes, and retention is an R2 bucket lifecycle rule.
    backup_enabled: bool = False
    backup_hour_utc: int = 9
    r2_account_id: str = ""
    r2_bucket: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""

    model_config = SettingsConfigDict(
        env_prefix="TRADE_GRADER_", env_file=".env", extra="ignore"
    )

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def backup_configured(self) -> bool:
        """True only when the job is switched on and fully credentialed."""
        return bool(
            self.backup_enabled
            and self.r2_account_id
            and self.r2_bucket
            and self.r2_access_key_id
            and self.r2_secret_access_key
        )

    @model_validator(mode="after")
    def _normalize_database_url(self) -> Settings:
        # Default to a SQLite file alongside the existing file cache when the
        # env doesn't pin a URL (local dev / CI).
        if not self.database_url:
            db_path = self.cache_dir / "identity.db"
            self.database_url = f"sqlite+aiosqlite:///{db_path}"
        # Managed Postgres (Railway/Heroku/etc.) hands out a sync-driver URL
        # (postgresql:// or postgres://); SQLAlchemy's async engine needs the
        # asyncpg driver. Normalize so the raw provider URL can be referenced
        # directly without a deploy-time crash.
        elif self.database_url.startswith("postgresql://"):
            self.database_url = "postgresql+asyncpg://" + self.database_url[len("postgresql://"):]
        elif self.database_url.startswith("postgres://"):
            self.database_url = "postgresql+asyncpg://" + self.database_url[len("postgres://"):]
        return self


def get_settings() -> Settings:
    return Settings()
