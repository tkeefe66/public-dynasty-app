from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.deps import require_admin, require_league_member
from app.config import get_settings
from app.db.engine import dispose_engine, init_engine
from app.ratelimit import limiter
from app.services.backup_service import backup_loop
from app.services.refresh_service import auto_refresh_loop

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    # Error monitoring (inert unless TRADE_GRADER_SENTRY_DSN is set). The SDK
    # auto-instruments FastAPI/Starlette, so unhandled errors are captured.
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.0,
            send_default_pii=False,
            # Frame locals default to ON and would ship whatever a failing
            # frame happened to hold — Settings objects, credentials, tokens.
            # A routine R2 outage must not become a secret disclosure.
            include_local_variables=False,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Create the identity DB engine eagerly (one pool, no first-request race).
        init_engine()
        tasks = []
        # Liveness: keep known leagues warm in the background.
        if settings.auto_refresh:
            tasks.append(asyncio.create_task(auto_refresh_loop(
                settings.cache_dir, settings.refresh_interval_seconds)))
            log.info("auto-refresh scheduler started (every %ss)",
                     settings.refresh_interval_seconds)
        # Durability: daily backup of Postgres + the cache volume to R2.
        if settings.backup_configured:
            tasks.append(asyncio.create_task(backup_loop(settings.cache_dir)))
            log.info("backup scheduler started (daily at %02d:00 UTC)",
                     settings.backup_hour_utc)
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            # Tear down the identity DB engine's connection pool.
            await dispose_engine()

    app = FastAPI(title="Trade Grader API", version="0.1.0", lifespan=lifespan)
    # Rate limiting: per-route @limiter.limit decorators key by authenticated
    # user (see app/ratelimit.py). The handler turns over-limit into HTTP 429.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["*"],
    )
    # Every gated route lives under /api/league/{league_id}/..., so the
    # membership guard is applied at the router level (no per-handler edits).
    # `require_league_member` resolves the caller itself (see app/auth/deps.py):
    # it must be able to short-circuit the og-card principal *before*
    # `get_current_user` runs, so `get_current_user` is no longer listed here
    # as a sibling dependency. Authentication is not weakened — every non-og
    # request still goes through it inside the guard.
    league_guard = [Depends(require_league_member)]
    admin_guard = [Depends(require_admin)]

    from app.routes import health
    app.include_router(health.router)  # open: liveness probe
    from app.routes import league
    app.include_router(league.router, dependencies=league_guard)
    from app.routes import refresh
    app.include_router(refresh.router, dependencies=league_guard)
    from app.routes import owner
    app.include_router(owner.router, dependencies=league_guard)
    from app.routes import trade
    app.include_router(trade.router, dependencies=league_guard)
    from app.routes import profiles
    app.include_router(profiles.router, dependencies=league_guard)
    from app.routes import leaderboard
    app.include_router(leaderboard.router, dependencies=league_guard)
    from app.routes import bets
    app.include_router(bets.router, dependencies=league_guard)
    from app.routes import draft
    app.include_router(draft.router, dependencies=league_guard)
    from app.routes import settings as settings_routes
    app.include_router(settings_routes.league_router, dependencies=league_guard)
    app.include_router(settings_routes.admin_router, dependencies=admin_guard)
    # Onboarding: user-scoped (self-guards via get_current_user), not league-gated.
    from app.routes import me
    app.include_router(me.router)
    # Telemetry: user-scoped pageview capture, not league-gated.
    from app.routes import events as events_route
    app.include_router(events_route.router)
    # Current NFL week for the TopBar note: user-scoped, not league-gated (the
    # chrome renders before a league is chosen, so it must never 409).
    from app.routes import nfl_state as nfl_state_route
    app.include_router(nfl_state_route.router)
    # App-owner admin surface (each route self-guards via require_admin).
    from app.routes import admin
    app.include_router(admin.router)
    return app


app = create_app()
