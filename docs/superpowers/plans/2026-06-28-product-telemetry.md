# Product Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** First-party pageview telemetry — capture each route change per user/league into Postgres and surface active-users, per-league activity, and a per-user drill-down on the admin page.

**Architecture:** A client beacon posts the raw pathname to `POST /api/events` (through the existing Next proxy, which attaches the backend token). The backend normalizes the path to a route template + league id (pure function), inserts a `page_events` row, and authenticates via `get_current_user` (which already stamps `active_days`). Admin read endpoints aggregate the table; the admin UI renders the three views.

**Tech Stack:** FastAPI + async SQLAlchemy + Alembic (backend), Next.js 14 App Router + Tailwind (frontend), pytest + vitest.

## Global Constraints

- Backend env prefix `TRADE_GRADER_`; identity/data DB is Postgres in prod, SQLite fallback locally/tests — **all queries must be dialect-portable** (no `date()`/`date_trunc` SQL; bucket by day in Python).
- Model conventions (from `api/app/db/models.py`): String(36) UUID PKs via `_uuid`, `DateTime(timezone=True)` with `server_default=func.now()`, `_now()` for Python-side timestamps.
- Never show "KTC" in UI (project-wide); not relevant here but keep labels consistent with existing admin styling (CSS tokens in `web/app/globals.css`: `--ink`, `--dim`, `--divider`, `--surface`).
- Query strings are **never** persisted (strip before storing).
- All `/api/admin/*` endpoints self-guard with `require_admin`; `/api/events` self-authenticates with `get_current_user` (not league-gated).
- This branch already carries the **active-days** change: `users.active_days` / `users.last_active_at`, `users.touch_activity`, and `get_current_user` calling it. Build on that; do not re-add `login_count`.

---

### Task 1: `page_events` table + migration

**Files:**
- Modify: `api/app/db/models.py` (append `PageEvent` model)
- Create: `api/migrations/versions/0006_page_events.py`
- Test: covered indirectly by Task 3; this task's verification is the migration applying.

**Interfaces:**
- Produces: `PageEvent` ORM model with columns `id, user_id, league_id, route, path, created_at`; table `page_events`.

- [ ] **Step 1: Add the model**

In `api/app/db/models.py`, after the `AppSetting` class, append:

```python
class PageEvent(Base):
    """One pageview (route change) by an authenticated user. First-party product
    telemetry: who's active, which sections/leagues get used. `route` is the
    normalized template (low cardinality, for aggregation); `path` is the raw
    pathname (for the per-user drill-down). Query strings are never stored."""

    __tablename__ = "page_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    league_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    route: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )
```

- [ ] **Step 2: Create the migration**

Create `api/migrations/versions/0006_page_events.py`:

```python
"""add page_events telemetry table

Revision ID: 0006_page_events
Revises: 0005_active_days
Create Date: 2026-06-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_page_events"
down_revision: Union[str, None] = "0005_active_days"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "page_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(), nullable=True),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_events_user_id", "page_events", ["user_id"])
    op.create_index("ix_page_events_league_id", "page_events", ["league_id"])
    op.create_index("ix_page_events_route", "page_events", ["route"])
    op.create_index("ix_page_events_created_at", "page_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_page_events_created_at", table_name="page_events")
    op.drop_index("ix_page_events_route", table_name="page_events")
    op.drop_index("ix_page_events_league_id", table_name="page_events")
    op.drop_index("ix_page_events_user_id", table_name="page_events")
    op.drop_table("page_events")
```

- [ ] **Step 3: Verify the migration applies on a fresh DB**

Run:
```bash
cd api && rm -f /tmp/pe.db && TRADE_GRADER_DATABASE_URL="sqlite+aiosqlite:////tmp/pe.db" alembic upgrade head
```
Expected: ends with `Running upgrade 0005_active_days -> 0006_page_events`.

- [ ] **Step 4: Commit**

```bash
git add api/app/db/models.py api/migrations/versions/0006_page_events.py
git commit -m "feat(telemetry): add page_events table + migration 0006"
```

---

### Task 2: `normalize_route` pure function

**Files:**
- Create: `api/app/services/route_normalize.py`
- Test: `api/tests/test_route_normalize.py`

**Interfaces:**
- Produces: `normalize_route(path: str) -> tuple[str, str | None]` returning `(route_template, league_id_or_None)`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_route_normalize.py`:

```python
from __future__ import annotations

import pytest

from app.services.route_normalize import normalize_route


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/", ("/", None)),
        ("/admin", ("/admin", None)),
        ("/admin/user/u123", ("/admin/user/[id]", None)),
        ("/account", ("/account", None)),
        ("/leagues/add", ("/leagues/add", None)),
        ("/login", ("/login", None)),
        ("/methodology", ("/methodology", None)),
        ("/league/123", ("/league/[id]", "123")),
        ("/league/123/", ("/league/[id]", "123")),
        ("/league/123/gm", ("/league/[id]/gm", "123")),
        ("/league/123/settings", ("/league/[id]/settings", "123")),
        ("/league/123/owner/abc", ("/league/[id]/owner/[uid]", "123")),
        ("/league/123/trade/t9", ("/league/[id]/trade/[tid]", "123")),
        # Unknown shape: id-looking segments masked, no league.
        ("/wat/99/x", ("/wat/[seg]/x", None)),
    ],
)
def test_normalize_route(path, expected):
    assert normalize_route(path) == expected
```

- [ ] **Step 2: Run it; expect failure**

Run: `cd api && pytest tests/test_route_normalize.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `api/app/services/route_normalize.py`:

```python
"""Map a raw URL pathname to a low-cardinality route template + league id.

Pure and deterministic — the single source of truth for how telemetry buckets
pages. Known App-Router shapes map to explicit templates; unknown shapes get
id-looking segments masked so a stray path can't explode `route` cardinality.
"""
from __future__ import annotations

import re

# Exact, parameterless routes.
_STATIC = {
    "/",
    "/admin",
    "/account",
    "/leagues/add",
    "/login",
    "/methodology",
}

# A segment that looks like an id (digits, or contains a digit, or long token).
_ID_RE = re.compile(r"^(?=.*\d)[A-Za-z0-9_-]+$")


def _looks_like_id(seg: str) -> bool:
    return bool(_ID_RE.match(seg)) or len(seg) >= 16


def normalize_route(path: str) -> tuple[str, str | None]:
    # Drop any query string / fragment and trailing slash (keep root "/").
    path = path.split("?", 1)[0].split("#", 1)[0]
    if len(path) > 1:
        path = path.rstrip("/")
    if not path:
        path = "/"

    if path in _STATIC:
        return path, None

    parts = path.strip("/").split("/")

    # /admin/user/[id]
    if parts[:2] == ["admin", "user"] and len(parts) == 3:
        return "/admin/user/[id]", None

    # /league/[id]/...
    if parts[0] == "league" and len(parts) >= 2:
        league_id = parts[1]
        rest = parts[2:]
        if not rest:
            return "/league/[id]", league_id
        if rest == ["gm"]:
            return "/league/[id]/gm", league_id
        if rest == ["settings"]:
            return "/league/[id]/settings", league_id
        if rest[:1] == ["owner"] and len(rest) == 2:
            return "/league/[id]/owner/[uid]", league_id
        if rest[:1] == ["trade"] and len(rest) == 2:
            return "/league/[id]/trade/[tid]", league_id
        # Unknown sub-route under a known league: mask the tail.
        masked = "/".join("[seg]" if _looks_like_id(p) else p for p in rest)
        return f"/league/[id]/{masked}", league_id

    # Fallback: mask id-looking segments, no league.
    masked = "/".join("[seg]" if _looks_like_id(p) else p for p in parts)
    return "/" + masked, None
```

- [ ] **Step 4: Run tests; expect pass**

Run: `cd api && pytest tests/test_route_normalize.py -q`
Expected: PASS (14 cases).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/route_normalize.py api/tests/test_route_normalize.py
git commit -m "feat(telemetry): pure route-normalization function"
```

---

### Task 3: events repository (insert + aggregations)

**Files:**
- Create: `api/app/repositories/events.py`
- Test: `api/tests/test_events_repo.py`

**Interfaces:**
- Consumes: `PageEvent` (Task 1), `normalize_route` (Task 2).
- Produces:
  - `record_event(db, *, user_id: str, path: str) -> None`
  - `active_user_counts(db) -> dict[str, int]` keys `d1`,`d7`,`d30`
  - `daily_active_users(db, days: int) -> list[tuple[str, int]]` — `(YYYY-MM-DD, distinct_users)` ascending, one entry per day with events
  - `league_activity(db) -> dict[str, dict]` — `league_id -> {events:int, active_users:int, last_activity:str|None}`
  - `user_activity(db, user_id: str, *, recent_limit: int = 50, days: int = 30) -> dict` — `{recent:[{path,route,league_id,created_at}], daily:[(YYYY-MM-DD,int)]}`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_events_repo.py`:

```python
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import PageEvent, User
from app.repositories import events


@pytest.fixture()
def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ev.db'}")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        m = async_sessionmaker(engine, expire_on_commit=False)
        async with m() as db:
            db.add(User(id="u1", google_sub="g1", email="a@t.local"))
            db.add(User(id="u2", google_sub="g2", email="b@t.local"))
            await db.commit()
        return m

    m = asyncio.run(_setup())
    try:
        yield m
    finally:
        asyncio.run(engine.dispose())


def _seed(maker, rows):
    async def _run():
        async with maker() as db:
            for uid, lid, route, path, ts in rows:
                db.add(PageEvent(user_id=uid, league_id=lid, route=route, path=path, created_at=ts))
            await db.commit()
    asyncio.run(_run())


def test_record_event_normalizes_and_inserts(maker):
    async def _run():
        async with maker() as db:
            await events.record_event(db, user_id="u1", path="/league/55/owner/x?foo=1")
            await db.commit()
            la = await events.league_activity(db)
        return la
    la = asyncio.run(_run())
    assert la["55"]["events"] == 1
    assert la["55"]["active_users"] == 1


def test_active_user_counts_windows(maker):
    now = datetime.now(tz=timezone.utc)
    _seed(maker, [
        ("u1", None, "/", "/", now),
        ("u2", None, "/", "/", now - timedelta(days=3)),
        ("u1", None, "/", "/", now - timedelta(days=10)),
    ])
    async def _run():
        async with maker() as db:
            return await events.active_user_counts(db)
    c = asyncio.run(_run())
    assert c["d1"] == 1   # only u1 today
    assert c["d7"] == 2   # u1 + u2
    assert c["d30"] == 2  # distinct users


def test_user_activity_drilldown(maker):
    now = datetime.now(tz=timezone.utc)
    _seed(maker, [
        ("u1", "55", "/league/[id]", "/league/55", now),
        ("u1", "55", "/league/[id]/gm", "/league/55/gm", now - timedelta(minutes=5)),
        ("u2", None, "/", "/", now),
    ])
    async def _run():
        async with maker() as db:
            return await events.user_activity(db, "u1", recent_limit=10, days=30)
    ua = asyncio.run(_run())
    assert len(ua["recent"]) == 2
    assert ua["recent"][0]["path"] == "/league/55"  # newest first
    assert sum(n for _, n in ua["daily"]) == 2
```

- [ ] **Step 2: Run it; expect failure**

Run: `cd api && pytest tests/test_events_repo.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `api/app/repositories/events.py`:

```python
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PageEvent
from app.services.route_normalize import normalize_route


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _day(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


async def record_event(db: AsyncSession, *, user_id: str, path: str) -> None:
    """Normalize a raw pathname and store one pageview. Query strings dropped."""
    route, league_id = normalize_route(path)
    clean_path = path.split("?", 1)[0].split("#", 1)[0]
    db.add(
        PageEvent(user_id=user_id, league_id=league_id, route=route, path=clean_path)
    )
    await db.flush()


async def _distinct_users_since(db: AsyncSession, since: datetime) -> int:
    stmt = select(func.count(func.distinct(PageEvent.user_id))).where(
        PageEvent.created_at >= since
    )
    return (await db.execute(stmt)).scalar() or 0


async def active_user_counts(db: AsyncSession) -> dict[str, int]:
    now = _now()
    return {
        "d1": await _distinct_users_since(db, now - timedelta(days=1)),
        "d7": await _distinct_users_since(db, now - timedelta(days=7)),
        "d30": await _distinct_users_since(db, now - timedelta(days=30)),
    }


async def daily_active_users(db: AsyncSession, days: int) -> list[tuple[str, int]]:
    """Distinct users per UTC day over the window. Bucketed in Python so the
    query is dialect-portable (no SQL date functions)."""
    since = _now() - timedelta(days=days)
    rows = (
        await db.execute(
            select(PageEvent.user_id, PageEvent.created_at).where(
                PageEvent.created_at >= since
            )
        )
    ).all()
    per_day: dict[str, set[str]] = {}
    for user_id, created_at in rows:
        per_day.setdefault(_day(created_at), set()).add(user_id)
    return [(day, len(users)) for day, users in sorted(per_day.items())]


async def league_activity(db: AsyncSession) -> dict[str, dict]:
    rows = (
        await db.execute(
            select(
                PageEvent.league_id,
                func.count(),
                func.count(func.distinct(PageEvent.user_id)),
                func.max(PageEvent.created_at),
            )
            .where(PageEvent.league_id.is_not(None))
            .group_by(PageEvent.league_id)
        )
    ).all()
    out: dict[str, dict] = {}
    for league_id, events_n, users_n, last in rows:
        out[league_id] = {
            "events": events_n,
            "active_users": users_n,
            "last_activity": last.isoformat() if last else None,
        }
    return out


async def user_activity(
    db: AsyncSession, user_id: str, *, recent_limit: int = 50, days: int = 30
) -> dict:
    recent_rows = (
        await db.execute(
            select(PageEvent)
            .where(PageEvent.user_id == user_id)
            .order_by(PageEvent.created_at.desc())
            .limit(recent_limit)
        )
    ).scalars().all()
    recent = [
        {
            "path": e.path,
            "route": e.route,
            "league_id": e.league_id,
            "created_at": e.created_at.isoformat(),
        }
        for e in recent_rows
    ]
    since = _now() - timedelta(days=days)
    day_rows = (
        await db.execute(
            select(PageEvent.created_at).where(
                PageEvent.user_id == user_id, PageEvent.created_at >= since
            )
        )
    ).scalars().all()
    counts = Counter(_day(ts) for ts in day_rows)
    daily = sorted(counts.items())
    return {"recent": recent, "daily": daily}
```

- [ ] **Step 4: Run tests; expect pass**

Run: `cd api && pytest tests/test_events_repo.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/repositories/events.py api/tests/test_events_repo.py
git commit -m "feat(telemetry): events repository (insert + aggregations)"
```

---

### Task 4: `POST /api/events` capture endpoint

**Files:**
- Create: `api/app/routes/events.py`
- Modify: `api/app/main.py` (register the router, un-guarded like `me.router`)
- Test: `api/tests/test_events_route.py`

**Interfaces:**
- Consumes: `record_event` (Task 3), `get_current_user`, `limiter`.
- Produces: `POST /api/events` accepting `{path: str}`, returning 204.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_events_route.py`:

```python
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import get_current_user
from app.db.base import Base
from app.db.models import PageEvent, User
from app.db.session import get_db
from app.main import app as fastapi_app
from sqlalchemy import select


@pytest.fixture()
def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evr.db'}")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        m = async_sessionmaker(engine, expire_on_commit=False)
        async with m() as db:
            db.add(User(id="u1", google_sub="g1", email="a@t.local"))
            await db.commit()
        return m

    maker = asyncio.run(_setup())

    async def _override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    try:
        yield TestClient(fastapi_app), maker
    finally:
        fastapi_app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_post_event_stores_normalized(client):
    c, maker = client
    r = c.post("/api/events", json={"path": "/league/77/gm?x=1"})
    assert r.status_code == 204

    async def _read():
        async with maker() as db:
            return (await db.execute(select(PageEvent))).scalars().all()
    rows = asyncio.run(_read())
    assert len(rows) == 1
    assert rows[0].route == "/league/[id]/gm"
    assert rows[0].league_id == "77"
    assert rows[0].path == "/league/77/gm"  # query stripped


def test_post_event_requires_auth():
    fastapi_app.dependency_overrides.clear()
    c = TestClient(fastapi_app)
    assert c.post("/api/events", json={"path": "/"}).status_code == 401
```

- [ ] **Step 2: Run it; expect failure**

Run: `cd api && pytest tests/test_events_route.py -q`
Expected: FAIL (404 — route not registered).

- [ ] **Step 3: Implement the route**

Create `api/app/routes/events.py`:

```python
"""Pageview telemetry capture. User-scoped (get_current_user, which also stamps
active-days), NOT league-gated. Fed by the web app's client beacon."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.ratelimit import limiter
from app.repositories import events

router = APIRouter()


class EventReq(BaseModel):
    path: str


@router.post("/api/events", status_code=204)
@limiter.limit(get_settings().rate_limit_default)
async def capture_event(
    request: Request,
    body: EventReq,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    path = (body.path or "").strip()
    if path:
        await events.record_event(db, user_id=user.id, path=path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Note: `@limiter.limit` requires the handler to take `request: Request` (slowapi reads it). Keep it first.

- [ ] **Step 4: Register the router**

In `api/app/main.py`, near the other un-guarded includes (where `me.router` is included), add:

```python
    from app.routes import events as events_route
    app.include_router(events_route.router)
```

- [ ] **Step 5: Run tests; expect pass**

Run: `cd api && pytest tests/test_events_route.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/events.py api/app/main.py api/tests/test_events_route.py
git commit -m "feat(telemetry): POST /api/events capture endpoint"
```

---

### Task 5: client beacon component

**Files:**
- Create: `web/components/Telemetry.tsx`
- Modify: `web/app/layout.tsx` (mount it inside the providers)
- Test: `web/tests/Telemetry.test.tsx`

**Interfaces:**
- Produces: `<Telemetry/>` client component that beacons `{path}` to `/api/events` on pathname change.

- [ ] **Step 1: Write the failing test**

Create `web/tests/Telemetry.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

import { Telemetry } from "@/components/Telemetry";

describe("Telemetry beacon", () => {
  beforeEach(() => {
    pathname = "/";
    (navigator as unknown as { sendBeacon: ReturnType<typeof vi.fn> }).sendBeacon =
      vi.fn(() => true);
  });

  it("fires on initial mount with the current path", () => {
    render(<Telemetry />);
    expect(navigator.sendBeacon).toHaveBeenCalledTimes(1);
    const [url] = (navigator.sendBeacon as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/events");
  });

  it("fires again when the path changes", () => {
    const { rerender } = render(<Telemetry />);
    pathname = "/league/9";
    rerender(<Telemetry />);
    expect(navigator.sendBeacon).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 2: Run it; expect failure**

Run: `cd web && npm run test -- --run tests/Telemetry.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `web/components/Telemetry.tsx`:

```tsx
"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

/**
 * Fire-and-forget pageview telemetry. Beacons the current pathname to
 * /api/events on every route change (and initial mount). Same-origin, so the
 * Next proxy attaches the backend token; anonymous beacons 401 and are dropped.
 * Sends only the pathname (no query string). Renders nothing.
 */
export function Telemetry() {
  const pathname = usePathname();
  const last = useRef<string | null>(null);

  useEffect(() => {
    if (!pathname || pathname === last.current) return;
    last.current = pathname;
    const body = JSON.stringify({ path: pathname });
    try {
      if (typeof navigator !== "undefined" && navigator.sendBeacon) {
        navigator.sendBeacon("/api/events", new Blob([body], { type: "application/json" }));
      } else {
        void fetch("/api/events", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          keepalive: true,
        });
      }
    } catch {
      // Telemetry must never break navigation.
    }
  }, [pathname]);

  return null;
}
```

- [ ] **Step 4: Run the test; expect pass**

Run: `cd web && npm run test -- --run tests/Telemetry.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Mount in the layout**

In `web/app/layout.tsx`, add the import and render it inside `ThemeProvider`:

```tsx
import { Telemetry } from "@/components/Telemetry";
```

Change the body block to:

```tsx
        <SessionProvider>
          <ThemeProvider>
            <Telemetry />
            {children}
          </ThemeProvider>
        </SessionProvider>
```

- [ ] **Step 6: Typecheck + commit**

Run: `cd web && npx tsc --noEmit` (ignore the two known pre-existing errors in `tests/FutureDraftTab.test.tsx` and `tests/proxy.test.ts`).

```bash
git add web/components/Telemetry.tsx web/app/layout.tsx web/tests/Telemetry.test.tsx
git commit -m "feat(telemetry): client pageview beacon mounted in root layout"
```

---

### Task 6: admin telemetry read endpoints

**Files:**
- Modify: `api/app/routes/admin.py`
- Test: `api/tests/test_admin_telemetry.py`

**Interfaces:**
- Consumes: `events` repo (Task 3), existing `_cache_dir`, `ChainCache`, `require_admin`.
- Produces:
  - `GET /api/admin/telemetry/active-users` → `ActiveUsers {daily: list[DailyPoint], d1, d7, d30}` where `DailyPoint {date: str, count: int}`
  - `GET /api/admin/users/{user_id}/activity` → `UserActivity {recent: list[ActivityEvent], daily: list[DailyPoint]}`, `ActivityEvent {path, route, league_id, league_name, created_at}`
  - Extend `AdminLeague` with `active_users: int` and `last_activity: str | None`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_admin_telemetry.py`:

```python
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import get_current_user
from app.db.base import Base
from app.db.models import LeagueMembership, PageEvent, User
from app.db.session import get_db
from app.main import app as fastapi_app


def _admin():
    return SimpleNamespace(id="u1", email="a@t.local", is_admin=True)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.routes.admin._cache_dir", lambda: tmp_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'at.db'}")
    now = datetime.now(tz=timezone.utc)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        m = async_sessionmaker(engine, expire_on_commit=False)
        async with m() as db:
            db.add(User(id="u1", google_sub="g1", email="a@t.local", is_admin=True))
            await db.flush()
            db.add(LeagueMembership(user_id="u1", league_id="L1", league_name="Alpha"))
            db.add(PageEvent(user_id="u1", league_id="L1", route="/league/[id]",
                             path="/league/L1", created_at=now))
            db.add(PageEvent(user_id="u1", league_id=None, route="/", path="/",
                             created_at=now))
            await db.commit()
        return m

    maker = asyncio.run(_setup())

    async def _override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_current_user] = _admin
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_active_users(client):
    body = client.get("/api/admin/telemetry/active-users").json()
    assert body["d1"] == 1 and body["d7"] == 1 and body["d30"] == 1
    assert sum(p["count"] for p in body["daily"]) == 1  # one distinct-user-day


def test_leagues_include_activity(client):
    leagues = {lg["league_id"]: lg for lg in client.get("/api/admin/leagues").json()}
    assert leagues["L1"]["active_users"] == 1
    assert leagues["L1"]["last_activity"] is not None


def test_user_activity_drilldown(client):
    body = client.get("/api/admin/users/u1/activity").json()
    assert len(body["recent"]) == 2
    league_ev = next(e for e in body["recent"] if e["league_id"] == "L1")
    assert league_ev["league_name"] == "Alpha"
```

- [ ] **Step 2: Run it; expect failure**

Run: `cd api && pytest tests/test_admin_telemetry.py -q`
Expected: FAIL (404s / missing fields).

- [ ] **Step 3: Implement — extend `AdminLeague` + add endpoints**

In `api/app/routes/admin.py`:

(a) Add the events import at the top with the other repo imports:

```python
from app.repositories import app_settings, events
```

(b) Add `active_users` and `last_activity` to `AdminLeague`:

```python
class AdminLeague(BaseModel):
    league_id: str
    name: str | None
    season: int | None
    member_count: int
    warm: bool
    spend_mtd_usd: float
    active_users: int
    last_activity: str | None
```

(c) Add the new response models near `AdminUser`:

```python
class DailyPoint(BaseModel):
    date: str
    count: int


class ActiveUsers(BaseModel):
    daily: list[DailyPoint]
    d1: int
    d7: int
    d30: int


class ActivityEvent(BaseModel):
    path: str
    route: str
    league_id: str | None
    league_name: str | None
    created_at: str


class UserActivity(BaseModel):
    recent: list[ActivityEvent]
    daily: list[DailyPoint]
```

(d) In the `leagues` handler, fetch activity once and fill the new fields. After `spend = _spend_by_league(_cache_dir())` add:

```python
    activity = await events.league_activity(db)
```

and in the `AdminLeague(...)` construction add:

```python
                active_users=(activity.get(league_id) or {}).get("active_users", 0),
                last_activity=(activity.get(league_id) or {}).get("last_activity"),
```

(e) Append the two new endpoints at the end of the file:

```python
@router.get("/api/admin/telemetry/active-users", response_model=ActiveUsers)
async def telemetry_active_users(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ActiveUsers:
    counts = await events.active_user_counts(db)
    daily = await events.daily_active_users(db, days=30)
    return ActiveUsers(
        daily=[DailyPoint(date=d, count=n) for d, n in daily],
        d1=counts["d1"], d7=counts["d7"], d30=counts["d30"],
    )


@router.get("/api/admin/users/{user_id}/activity", response_model=UserActivity)
async def telemetry_user_activity(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserActivity:
    data = await events.user_activity(db, user_id, recent_limit=50, days=30)
    # Resolve league names (cache name preferred, else stored membership name).
    cache = ChainCache(cache_dir=_cache_dir())
    membership_names = dict(
        (
            await db.execute(
                select(LeagueMembership.league_id, func.max(LeagueMembership.league_name))
                .group_by(LeagueMembership.league_id)
            )
        ).all()
    )
    name_cache: dict[str, str | None] = {}

    def _name(lid: str | None) -> str | None:
        if not lid:
            return None
        if lid not in name_cache:
            entry = cache.read(lid)
            cache_name = (entry.league_name_by_id or {}).get(lid) if entry else None
            name_cache[lid] = cache_name or membership_names.get(lid)
        return name_cache[lid]

    return UserActivity(
        recent=[
            ActivityEvent(
                path=e["path"], route=e["route"], league_id=e["league_id"],
                league_name=_name(e["league_id"]), created_at=e["created_at"],
            )
            for e in data["recent"]
        ],
        daily=[DailyPoint(date=d, count=n) for d, n in data["daily"]],
    )
```

- [ ] **Step 4: Run tests; expect pass**

Run: `cd api && pytest tests/test_admin_telemetry.py tests/test_admin_route.py -q`
Expected: PASS (test_admin_route still green — its `AdminLeague` assertions don't check the new fields, but verify; if it constructs `AdminLeague` anywhere it must include the new required fields. It does not — it only reads the endpoint).

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/admin.py api/tests/test_admin_telemetry.py
git commit -m "feat(telemetry): admin read endpoints (active-users, league activity, user drill-down)"
```

---

### Task 7: web API client — types + fetchers

**Files:**
- Modify: `web/lib/api.ts`
- Test: `web/tests/api.test.ts` (extend existing if it asserts shapes; otherwise no test — these are thin typed fetchers)

**Interfaces:**
- Consumes: backend endpoints from Task 6.
- Produces: `AdminLeague` (extended) + `AdminActiveUsers`, `AdminUserActivity` interfaces; `adminActiveUsers()`, `adminUserActivity(id)` fetchers.

- [ ] **Step 1: Extend `AdminLeague` and add interfaces**

In `web/lib/api.ts`, extend `AdminLeague`:

```ts
export interface AdminLeague {
  league_id: string;
  name: string | null;
  season: number | null;
  member_count: number;
  warm: boolean;
  spend_mtd_usd: number;
  active_users: number;
  last_activity: string | null;
}
```

Add near the admin interfaces:

```ts
export interface DailyPoint {
  date: string;
  count: number;
}

export interface AdminActiveUsers {
  daily: DailyPoint[];
  d1: number;
  d7: number;
  d30: number;
}

export interface AdminActivityEvent {
  path: string;
  route: string;
  league_id: string | null;
  league_name: string | null;
  created_at: string;
}

export interface AdminUserActivity {
  recent: AdminActivityEvent[];
  daily: DailyPoint[];
}
```

- [ ] **Step 2: Add the fetchers**

Near `adminUsers()`:

```ts
export function adminActiveUsers(): Promise<AdminActiveUsers> {
  return jsonFetch<AdminActiveUsers>(`${BASE}/admin/telemetry/active-users`);
}

export function adminUserActivity(userId: string): Promise<AdminUserActivity> {
  return jsonFetch<AdminUserActivity>(`${BASE}/admin/users/${userId}/activity`);
}
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit` (ignore the two known pre-existing errors).
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(telemetry): web api client types + fetchers"
```

---

### Task 8: admin UI — Usage section + per-league columns

**Files:**
- Modify: `web/app/admin/page.tsx`
- Create: `web/components/admin/DauBar.tsx` (tiny inline bar chart)

**Interfaces:**
- Consumes: `adminActiveUsers()`, extended `AdminLeague` (Task 7).
- Produces: a "Usage" section + two new Leagues-table columns.

- [ ] **Step 1: Create the mini bar chart**

Create `web/components/admin/DauBar.tsx`:

```tsx
import type { DailyPoint } from "@/lib/api";

/** Tiny CSS bar chart of distinct active users per day (last ~30d). */
export function DauBar({ daily }: { daily: DailyPoint[] }) {
  if (daily.length === 0) {
    return <p className="mt-2 text-sm text-dim">No activity recorded yet.</p>;
  }
  const max = Math.max(...daily.map((d) => d.count), 1);
  return (
    <div className="mt-3 flex items-end gap-[3px] h-24" aria-label="Daily active users">
      {daily.map((d) => (
        <div
          key={d.date}
          title={`${d.date}: ${d.count}`}
          className="flex-1 rounded-sm bg-[var(--pos)] min-h-[2px]"
          style={{ height: `${(d.count / max) * 100}%` }}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Add the Usage section + league columns to the admin page**

In `web/app/admin/page.tsx`:

(a) Imports — add `adminActiveUsers`, `type AdminActiveUsers`, and `DauBar`:

```tsx
import { DauBar } from "@/components/admin/DauBar";
```
and add `adminActiveUsers`, `AdminActiveUsers` to the existing `@/lib/api` import.

(b) Fetch it alongside the others. Change the `Promise.all` to include it:

```tsx
    let activeUsers: AdminActiveUsers;
    [overview, leagues, users, activeUsers] = await Promise.all([
      adminOverview(),
      adminLeagues(),
      adminUsers(),
      adminActiveUsers(),
    ]);
```
(declare `let activeUsers: AdminActiveUsers;` with the other `let` declarations).

(c) Add a Usage section just under the stat cards (before Budget editor):

```tsx
        {/* Usage */}
        <h2 className="mt-10 text-lg font-bold">Usage</h2>
        <div className="mt-3 grid grid-cols-3 gap-3">
          {[
            { label: "Active today", value: activeUsers.d1 },
            { label: "Active 7d", value: activeUsers.d7 },
            { label: "Active 30d", value: activeUsers.d30 },
          ].map((s) => (
            <div key={s.label} className="rounded-card border border-divider bg-surface p-4">
              <div className="text-xs text-dim mb-1">{s.label}</div>
              <div className="text-2xl font-extrabold">{s.value}</div>
            </div>
          ))}
        </div>
        <DauBar daily={activeUsers.daily} />
```

(d) In the Leagues table header, add two columns before "Spend (mo)":

```tsx
                <th className="pb-2 font-normal text-right">Active users</th>
                <th className="pb-2 font-normal text-right">Last activity</th>
```

(e) In the Leagues table body row, add the matching cells (reuse the `lastSeen` helper already defined in this file for the date):

```tsx
                  <td className="py-2 text-right font-mono text-ink">{lg.active_users}</td>
                  <td className="py-2 text-right text-dim">{lastSeen(lg.last_activity)}</td>
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit` (ignore the two pre-existing errors).
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add web/app/admin/page.tsx web/components/admin/DauBar.tsx
git commit -m "feat(telemetry): admin Usage section + per-league activity columns"
```

---

### Task 9: admin per-user drill-down page

**Files:**
- Create: `web/app/admin/user/[id]/page.tsx`
- Modify: `web/app/admin/page.tsx` (link each user email to the drill-down)

**Interfaces:**
- Consumes: `adminUserActivity(id)`, `DauBar` (Task 8).
- Produces: `/admin/user/[id]` page; user rows link to it.

- [ ] **Step 1: Create the drill-down page**

Create `web/app/admin/user/[id]/page.tsx`:

```tsx
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { DauBar } from "@/components/admin/DauBar";
import { adminUserActivity, type AdminUserActivity } from "@/lib/api";

export const dynamic = "force-dynamic";

function when(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export default async function AdminUserPage({ params }: { params: { id: string } }) {
  let activity: AdminUserActivity;
  try {
    activity = await adminUserActivity(params.id);
  } catch {
    return (
      <Shell>
        <TopBar />
        <section className="mt-16 max-w-lg">
          <h1 className="text-3xl font-extrabold tracking-tight">Not authorized</h1>
          <Link href="/admin" className="mt-4 inline-block text-dim underline hover:text-ink">
            ← Back to Admin
          </Link>
        </section>
      </Shell>
    );
  }

  return (
    <Shell>
      <TopBar />
      <section className="mt-8 max-w-3xl">
        <Link href="/admin" className="text-dim underline hover:text-ink">← Admin</Link>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight">User activity</h1>

        <h2 className="mt-8 text-lg font-bold">Active days (30d)</h2>
        <DauBar daily={activity.daily} />

        <h2 className="mt-10 text-lg font-bold">Recent pages</h2>
        {activity.recent.length === 0 ? (
          <p className="mt-2 text-sm text-dim">No pageviews recorded yet.</p>
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-dim border-b border-divider">
                <th className="pb-2 font-normal">When</th>
                <th className="pb-2 font-normal">Page</th>
                <th className="pb-2 font-normal">League</th>
              </tr>
            </thead>
            <tbody>
              {activity.recent.map((e, i) => (
                <tr key={i} className="border-b border-divider">
                  <td className="py-2 text-dim whitespace-nowrap">{when(e.created_at)}</td>
                  <td className="py-2 text-ink font-mono">{e.route}</td>
                  <td className="py-2 text-dim">
                    {e.league_id ? (
                      <Link href={`/league/${e.league_id}`} className="hover:underline">
                        {e.league_name ?? e.league_id}
                      </Link>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </Shell>
  );
}
```

- [ ] **Step 2: Link user rows to the drill-down**

In `web/app/admin/page.tsx`, change the email cell in the primary user row from:

```tsx
                    <td className="py-2 text-ink">{u.email}</td>
```
to:

```tsx
                    <td className="py-2">
                      <Link href={`/admin/user/${u.id}`} className="text-ink hover:underline">
                        {u.email}
                      </Link>
                    </td>
```

(`Link` is already imported in this file.)

- [ ] **Step 3: Typecheck + run all web tests**

Run: `cd web && npx tsc --noEmit` (ignore the two pre-existing errors), then `cd web && npm run test -- --run`.
Expected: tsc no new errors; all vitest pass.

- [ ] **Step 4: Commit**

```bash
git add web/app/admin/user web/app/admin/page.tsx
git commit -m "feat(telemetry): admin per-user activity drill-down page"
```

---

### Task 10: full verification + migration check

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run: `cd api && pytest -q`
Expected: all pass (prior 312 + new telemetry tests).

- [ ] **Step 2: Migration applies clean on a fresh DB**

Run: `cd api && rm -f /tmp/pe2.db && TRADE_GRADER_DATABASE_URL="sqlite+aiosqlite:////tmp/pe2.db" alembic upgrade head`
Expected: ends at `0006_page_events`.

- [ ] **Step 3: Full web suite + typecheck**

Run: `cd web && npm run test -- --run && npx tsc --noEmit`
Expected: vitest all pass; only the two known pre-existing tsc errors remain.

- [ ] **Step 4: Confirm nothing references removed names**

Run: `grep -rn "login_count\|login-event\|record_login" web/app web/lib web/components api/app api/tests | grep -v node_modules`
Expected: no output.

---

## Self-Review

**Spec coverage:**
- Data model (`page_events`) → Task 1. ✓
- Route normalization → Task 2. ✓
- Client beacon → Task 5. ✓
- Capture endpoint → Task 4. ✓
- Repository + aggregations → Task 3. ✓
- Admin endpoints (active-users, per-league, drill-down) → Task 6. ✓
- Admin UI (Usage, per-league columns, drill-down page) → Tasks 8, 9. ✓
- Web API client → Task 7. ✓
- Privacy (strip query strings) → Tasks 3 (`record_event`) + 4 (route) + test in Task 4. ✓
- Testing across normalize/repo/route/admin/frontend → Tasks 2–6, 9. ✓
- "Top pages" intentionally omitted (out of scope). ✓
- Dependency on active-days → satisfied (already cherry-picked onto this branch). ✓

**Type consistency:** `DailyPoint{date,count}`, `ActiveUsers`, `ActivityEvent`, `UserActivity` names match between backend (Task 6) and frontend (Task 7). `record_event(db, *, user_id, path)`, `active_user_counts`, `daily_active_users`, `league_activity`, `user_activity` signatures match between Task 3 (definition) and Tasks 4/6 (callers). `normalize_route` signature matches Task 2 ↔ Task 3. `AdminLeague` extended fields (`active_users`, `last_activity`) consistent Task 6 ↔ Task 7 ↔ Task 8.

**Placeholder scan:** none — all steps contain concrete code/commands.
