# Trade Grader Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a professional multi-tenant web app on top of the existing Sleeper trade-history grader. Next.js frontend + FastAPI backend, single Railway deploy, light + dark theme, dashboard-first IA with year tabs / lens switcher / sortable filterable standings, four-layer education for new users.

**Architecture:** Three-tier monorepo. The existing `src/sleeper_dynasty/` Python grader is imported as a library by a new `api/` FastAPI service. A new `web/` Next.js app calls the FastAPI service through a server-side proxy. Both services deploy as separate Railway services in one project; the backend mounts a persistent volume at `~/.sleeper-dynasty/cache` so the existing `FileCache` survives deploys.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, Pydantic v2, sse-starlette. TypeScript, Next.js 14 (App Router), React Server Components where possible, Tailwind CSS, @next/font for Geist + Instrument Serif, lucide-react for icons. Vitest + Testing Library + Playwright for frontend tests. pytest + httpx.AsyncClient for backend tests. Railway for hosting (two services, one persistent volume).

Spec: `docs/superpowers/specs/2026-05-28-trade-grader-web-app-design.md`.

---

## File Structure

**New top-level directories:**

| Path | Responsibility |
|---|---|
| `api/` | FastAPI backend. Wraps the existing Python grader, exposes JSON endpoints, handles caching for chain pulls + aggregations. |
| `web/` | Next.js 14 app. Pages, components, server-side proxy to `api/`, theme + design tokens, fonts. |

**Existing directories untouched** unless explicitly modified: `src/sleeper_dynasty/`, `tests/`, `docs/`.

### Backend file map

```
api/
  pyproject.toml              # separate dep set: fastapi, uvicorn, pydantic, sse-starlette
  uvicorn_entry.py            # production entry for uvicorn workers
  Dockerfile                  # Railway build target
  app/
    __init__.py
    main.py                   # FastAPI() instance, route registration, CORS, lifespan
    config.py                 # pydantic-settings: env vars (cache dir, CORS origins)
    deps.py                   # FastAPI dependencies: get_cache, get_grader_service
    errors.py                 # HTTPException subclasses + error response envelope
    logging.py                # structured JSON logging setup
    models/
      __init__.py
      league.py               # LookupResp, LeagueSummary, DashboardResp, etc.
      owner.py                # OwnerDetailResp
      trade.py                # TradeDetailResp
    services/
      __init__.py
      grader.py               # Async wrapper around build_trade_history+grade_trade
      chain_cache.py          # Chain-pull cache (single JSON blob per league chain)
      aggregations.py         # Pure functions: year/lens/sort/filter over cached data
      progress.py             # Progress event emitter for SSE
    routes/
      __init__.py
      health.py               # GET /api/health
      lookup.py               # POST /api/lookup
      league.py               # GET /api/league/{id} (+ year/lens/sort/filter)
      owner.py                # GET /api/league/{id}/owner/{uid}
      trade.py                # GET /api/league/{id}/trade/{tid}
      refresh.py              # POST /api/league/{id}/refresh (returns SSE stream)
  tests/
    conftest.py               # shared fixtures: app, mock grader, sample chain
    test_health.py
    test_lookup.py
    test_league.py
    test_owner.py
    test_trade.py
    test_refresh.py
    test_aggregations.py
    test_chain_cache.py
    fixtures/
      sample_chain.json       # canned ResolvedTrade+grades+display_names
```

### Frontend file map

```
web/
  package.json
  next.config.mjs             # rewrites /api/* → FastAPI URL
  tsconfig.json
  tailwind.config.ts
  postcss.config.mjs
  Dockerfile                  # Railway build target
  app/
    layout.tsx                # root layout: fonts, theme provider, shell
    globals.css               # tokens (CSS vars for light + dark), reset
    page.tsx                  # / landing
    u/[username]/page.tsx     # league picker
    league/[id]/page.tsx      # dashboard (default)
    league/[id]/owner/[uid]/page.tsx     # owner detail
    league/[id]/trade/[tid]/page.tsx     # trade detail
    methodology/page.tsx
    not-found.tsx             # 404
  components/
    Brand.tsx
    TopBar.tsx
    ThemeToggle.tsx
    RefreshButton.tsx
    YearTabs.tsx
    LensSwitcher.tsx
    HeroStatCard.tsx
    InfoTooltip.tsx
    ExplainerBanner.tsx
    StandingsTable.tsx        # uses SortableHeader + FilterRow + GradeFilterPills
    TradeCard.tsx             # for sidebar latest list + lists elsewhere
    RecordsPanel.tsx
    AssetRender.tsx           # renders PlayerAsset / PickAsset / FaabAsset
    ProgressModal.tsx
    ShareUrlButton.tsx
  lib/
    api.ts                    # typed fetch wrappers
    types.ts                  # shared TS types (mirrors Pydantic models)
    url-state.ts              # year/lens/sort/filter ↔ URL search params
    theme.ts                  # light/dark detection + persistence
    format.ts                 # number formatting (tabular, signed, etc.)
    assets.ts                 # asset rendering pure functions
  styles/
    tokens.css                # CSS custom properties (light + dark)
  tests/
    vitest.config.ts
    setup.ts
    url-state.test.ts
    aggregations.test.ts      # mirror of backend logic if used client-side
    format.test.ts
    StandingsTable.test.tsx
    LensSwitcher.test.tsx
    HeroStatCard.test.tsx
  e2e/
    playwright.config.ts
    landing.spec.ts
    dashboard.spec.ts
    visual-regression.spec.ts
```

### Repo root additions

| Path | Responsibility |
|---|---|
| `railway.json` | Multi-service config: `web` (Node), `api` (Python), shared volume |
| `Makefile` (or equivalent shell scripts) | `make dev`, `make test`, `make build` |

---

## Conventions used in this plan

- **Test framework choice:**
  - Backend: `pytest` + `pytest-asyncio` (matches existing) + `httpx.AsyncClient` with FastAPI's `TestClient`-style usage.
  - Frontend unit: `vitest` + `@testing-library/react`.
  - Frontend E2E: `playwright`.
- All commands are run from the repo root unless noted otherwise.
- Backend tests live under `api/tests/`; frontend unit tests under `web/tests/`; e2e under `web/e2e/`.
- All commits use HEREDOC commit messages with the existing `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
- TDD pattern repeats: write failing test → run to confirm fail → implement → run to confirm pass → commit.
- **Hot reload during dev:** backend `uvicorn api.app.main:app --reload --port 8000`; frontend `cd web && npm run dev` (proxies `/api/*` to `localhost:8000`).
- **Style:** Python uses existing project conventions (4-space indent, `from __future__ import annotations`). TS uses 2-space, strict mode, no `any`.

---

# Phase 1 — Backend foundation

Goal: FastAPI app running with a health endpoint + the lookup endpoint + a working chain-cache layer that the league endpoint can build on.

### Task 1: Add backend dependencies + skeleton

**Files:**
- Create: `api/pyproject.toml`
- Create: `api/app/__init__.py`
- Create: `api/app/main.py`
- Create: `api/app/config.py`
- Create: `api/uvicorn_entry.py`
- Create: `api/tests/__init__.py`
- Create: `api/tests/conftest.py`

- [ ] **Step 1: Create `api/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "trade-grader-api"
version = "0.1.0"
description = "FastAPI backend wrapping the sleeper-dynasty grader for the web app."
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "sse-starlette>=2.1",
    "httpx>=0.27",
    # The grader package itself, installed editable from the repo root.
    "sleeper-dynasty",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "httpx>=0.27"]

[tool.setuptools.packages.find]
where = ["."]
include = ["app*"]
```

- [ ] **Step 2: Create `api/app/__init__.py`** — empty file:

```python
```

- [ ] **Step 3: Create `api/app/config.py`**

```python
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration sourced from env vars.

    Defaults match local-dev shape; Railway sets the env in production.
    """

    cache_dir: Path = Path.home() / ".sleeper-dynasty" / "cache"
    cors_origins: list[str] = ["http://localhost:3000"]
    chain_cache_ttl_seconds: int = 24 * 3600
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_prefix="TRADE_GRADER_", env_file=".env")


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Create `api/app/main.py`**

```python
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title="Trade Grader API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    return app


app = create_app()
```

- [ ] **Step 5: Create `api/uvicorn_entry.py`**

```python
"""Production entry point for uvicorn.

Run: uvicorn api.uvicorn_entry:app --host 0.0.0.0 --port $PORT
"""

from app.main import app

__all__ = ["app"]
```

- [ ] **Step 6: Create `api/tests/__init__.py`** — empty file.

- [ ] **Step 7: Create `api/tests/conftest.py`**

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app


@pytest.fixture()
def app():
    return fastapi_app


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)
```

- [ ] **Step 8: Install deps + verify app imports**

```bash
cd api
python3.11 -m pip install -e .[dev]
python3.11 -c "from app.main import app; print(app.title)"
```

Expected output: `Trade Grader API`.

- [ ] **Step 9: Commit**

```bash
git add api/pyproject.toml api/app/__init__.py api/app/config.py api/app/main.py api/uvicorn_entry.py api/tests/__init__.py api/tests/conftest.py
git commit -m "$(cat <<'EOF'
Add FastAPI backend skeleton

api/ subpackage with config, app factory, uvicorn entry, and pytest
conftest. CORS allows the web/ dev server at localhost:3000.
Dependencies in api/pyproject.toml so the backend can be installed
independently of the grader; it imports the existing sleeper_dynasty
package as a library.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Health endpoint

**Files:**
- Create: `api/app/routes/__init__.py`
- Create: `api/app/routes/health.py`
- Modify: `api/app/main.py` (register router)
- Create: `api/tests/test_health.py`

- [ ] **Step 1: Write failing test**

Create `api/tests/test_health.py`:

```python
def test_health_returns_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_health.py -v
```

Expected: FAIL (404 — no health route yet).

- [ ] **Step 3: Create `api/app/routes/__init__.py`** — empty file.

- [ ] **Step 4: Create `api/app/routes/health.py`**

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Register the router in `api/app/main.py`**

After `app.add_middleware(...)`, before `return app`, add:

```python
    from app.routes import health
    app.include_router(health.router)
```

- [ ] **Step 6: Confirm pass**

```bash
cd api && pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/app/routes/__init__.py api/app/routes/health.py api/app/main.py api/tests/test_health.py
git commit -m "$(cat <<'EOF'
Add GET /api/health endpoint

Liveness/readiness probe for Railway. Returns {"status": "ok"}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Pydantic response models

**Files:**
- Create: `api/app/models/__init__.py`
- Create: `api/app/models/league.py`
- Create: `api/app/models/owner.py`
- Create: `api/app/models/trade.py`
- Create: `api/tests/test_models.py`

- [ ] **Step 1: Write failing test**

Create `api/tests/test_models.py`:

```python
import pytest

from app.models.league import (
    DashboardResp,
    HeroStat,
    HeroStats,
    LeagueSummary,
    LookupResp,
    StandingRow,
    LatestTrade,
    Records,
)
from app.models.owner import OwnerDetailResp, SeasonArc
from app.models.trade import TradeDetailResp, TradeSideView


def test_lookup_resp_serializes():
    resp = LookupResp(
        user_id="u1",
        username="alice",
        leagues_by_season={
            2026: [LeagueSummary(league_id="L1", name="Bros", season=2026,
                                 total_rosters=12, status="in_season")],
        },
    )
    dumped = resp.model_dump()
    assert dumped["leagues_by_season"]["2026"][0]["league_id"] == "L1"


def test_dashboard_resp_assembles():
    resp = DashboardResp(
        league=LeagueSummary(league_id="L1", name="Bros", season=2026,
                             total_rosters=12, status="in_season",
                             seasons=[2023, 2024, 2025, 2026],
                             last_refreshed="2026-05-28T12:00:00Z"),
        selected_year="all",
        selected_lens="ktc",
        hero_stats=HeroStats(
            activity=HeroStat(value="47", context="trades graded"),
            biggest_win=HeroStat(value="+2755", context="Tom · Bijan deal",
                                 owner="Tom", trade_id="tx1",
                                 date="2024-11-12", counterparty="Mike"),
            biggest_loss=HeroStat(value="-1890", context="Sarah · Garrett deal",
                                  owner="Sarah", trade_id="tx2",
                                  date="2024-09-22", counterparty="Anthony"),
            most_active=HeroStat(value="Mike", context="5 trades"),
        ),
        standings=[
            StandingRow(rank=1, user_id="u1", display_name="Tom",
                        net_ktc=2755, net_production=406.8, trades=5,
                        ps_plus=2, grade="A"),
        ],
        latest_trades=[
            LatestTrade(trade_id="tx1", date="2024-11-12", week=11,
                        parties=["Tom", "Mike"],
                        assets_short="Bijan ↔ Justin Jefferson",
                        swing_ktc=2755, swing_prod=406.8),
        ],
        records=Records(
            biggest_value_swing=2755,
            biggest_production=406.8,
            most_decisive=3,
            most_trades=5,
            biggest_value_swing_owner="Tom",
            biggest_production_owner="Tom",
            most_decisive_owner="Tom",
            most_trades_owner="Mike",
        ),
    )
    assert resp.standings[0].grade == "A"


def test_owner_detail_resp_assembles():
    r = OwnerDetailResp(
        league_id="L1",
        user_id="u1",
        display_name="Tom",
        totals_by_lens={
            "ktc": 2755,
            "production": 406.8,
            "impact": 7,
        },
        career_arc=[
            SeasonArc(season=2024, net_ktc=2755, net_production=406.8, trades=5),
        ],
        best_trade_id="tx1",
        worst_trade_id=None,
    )
    assert r.career_arc[0].net_ktc == 2755


def test_trade_detail_resp_assembles():
    r = TradeDetailResp(
        league_id="L1",
        trade_id="tx1",
        date="2024-11-12",
        week=11,
        season=2024,
        league_name="Bros",
        sides=[
            TradeSideView(
                user_id="u1",
                display_name="Tom",
                received=[{"kind": "player", "name": "Bijan Robinson"}],
                given=[{"kind": "player", "name": "Justin Jefferson"}],
                snapshot_ktc_swing=2755,
                hindsight_production_swing=406.8,
                realized={
                    "starter_weeks": 18,
                    "starter_points_contributed": 286.0,
                    "win_share_points": 198.0,
                    "decisive_starts": 4,
                    "playoff_starts": 2,
                },
            ),
        ],
    )
    assert r.sides[0].snapshot_ktc_swing == 2755
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_models.py -v
```

Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Create `api/app/models/__init__.py`** — empty file.

- [ ] **Step 4: Create `api/app/models/league.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LeagueSummary(BaseModel):
    league_id: str
    name: str
    season: int
    total_rosters: int
    status: str
    seasons: list[int] | None = None
    last_refreshed: str | None = None


class LookupResp(BaseModel):
    user_id: str
    username: str
    leagues_by_season: dict[int, list[LeagueSummary]]


class HeroStat(BaseModel):
    value: str
    context: str
    owner: str | None = None
    trade_id: str | None = None
    date: str | None = None
    counterparty: str | None = None


class HeroStats(BaseModel):
    activity: HeroStat
    biggest_win: HeroStat
    biggest_loss: HeroStat
    most_active: HeroStat


class StandingRow(BaseModel):
    rank: int
    user_id: str
    display_name: str
    net_ktc: float
    net_production: float
    trades: int
    ps_plus: int
    grade: str


class LatestTrade(BaseModel):
    trade_id: str
    date: str
    week: int
    parties: list[str]
    assets_short: str
    swing_ktc: float
    swing_prod: float


class Records(BaseModel):
    biggest_value_swing: float
    biggest_value_swing_owner: str | None = None
    biggest_production: float
    biggest_production_owner: str | None = None
    most_decisive: int
    most_decisive_owner: str | None = None
    most_trades: int
    most_trades_owner: str | None = None


Lens = Literal["ktc", "production", "impact"]
Year = int | Literal["all"]


class DashboardResp(BaseModel):
    league: LeagueSummary
    selected_year: Year
    selected_lens: Lens
    hero_stats: HeroStats
    standings: list[StandingRow]
    latest_trades: list[LatestTrade] = Field(default_factory=list)
    records: Records
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Create `api/app/models/owner.py`**

```python
from __future__ import annotations

from pydantic import BaseModel


class SeasonArc(BaseModel):
    season: int
    net_ktc: float
    net_production: float
    trades: int


class OwnerDetailResp(BaseModel):
    league_id: str
    user_id: str
    display_name: str
    totals_by_lens: dict[str, float]
    career_arc: list[SeasonArc]
    best_trade_id: str | None
    worst_trade_id: str | None
```

- [ ] **Step 6: Create `api/app/models/trade.py`**

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TradeSideView(BaseModel):
    user_id: str
    display_name: str
    received: list[dict[str, Any]]
    given: list[dict[str, Any]]
    snapshot_ktc_swing: float
    hindsight_production_swing: float
    realized: dict[str, float]


class TradeDetailResp(BaseModel):
    league_id: str
    trade_id: str
    date: str
    week: int
    season: int
    league_name: str
    sides: list[TradeSideView]
```

- [ ] **Step 7: Confirm pass**

```bash
cd api && pytest tests/test_models.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 8: Commit**

```bash
git add api/app/models/__init__.py api/app/models/league.py api/app/models/owner.py api/app/models/trade.py api/tests/test_models.py
git commit -m "$(cat <<'EOF'
Add Pydantic response models for league/owner/trade routes

Mirrors the JSON shapes spec'd in the web-app design doc. Lens and
Year are typed literals; StandingRow has explicit numeric fields the
frontend filter/sort logic can rely on without runtime checks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: ChainCache — single-blob cache for resolved chain data

**Files:**
- Create: `api/app/services/__init__.py`
- Create: `api/app/services/chain_cache.py`
- Create: `api/tests/test_chain_cache.py`

The chain cache stores the union of (resolved trades + grades + per-owner records + display names + league chain meta) as a single JSON blob per starting-league-id. TTL: 24h. Backed by the existing `FileCache`.

- [ ] **Step 1: Write failing test**

Create `api/tests/test_chain_cache.py`:

```python
from __future__ import annotations

import pytest

from app.services.chain_cache import ChainCache, ChainCacheEntry


@pytest.fixture
def cache(tmp_path):
    return ChainCache(cache_dir=tmp_path)


def test_chain_cache_round_trip(cache):
    entry = ChainCacheEntry(
        league_id="L1",
        chain=[{"league_id": "L1", "season": 2026, "name": "Bros"}],
        resolved_trades=[{"transaction_id": "tx1"}],
        grades={"tx1": {"snapshot_value_swing": {"u1": 100}}},
        display_names={"u1": "Tom"},
        playoff_weeks_by_league={"L1": 15},
        roster_to_user_by_league={"L1": {1: "u1"}},
        league_name_by_id={"L1": "Bros"},
        league_season_by_id={"L1": 2026},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    cache.write("L1", entry)
    got = cache.read("L1")
    assert got is not None
    assert got.resolved_trades[0]["transaction_id"] == "tx1"
    assert got.display_names["u1"] == "Tom"


def test_chain_cache_expires(cache):
    entry = ChainCacheEntry(
        league_id="L1", chain=[], resolved_trades=[], grades={},
        display_names={}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={},
        league_season_by_id={}, cached_at="2026-01-01T00:00:00Z",
        warnings=[],
    )
    cache.write("L1", entry)
    expired = cache.read("L1", max_age_seconds=0)
    assert expired is None


def test_chain_cache_miss(cache):
    assert cache.read("doesnotexist") is None


def test_chain_cache_invalidate(cache):
    entry = ChainCacheEntry(
        league_id="L1", chain=[], resolved_trades=[], grades={},
        display_names={}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={},
        league_season_by_id={}, cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    cache.write("L1", entry)
    cache.invalidate("L1")
    assert cache.read("L1") is None
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_chain_cache.py -v
```

Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Create `api/app/services/__init__.py`** — empty file.

- [ ] **Step 4: Create `api/app/services/chain_cache.py`**

```python
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TTL = 24 * 3600


@dataclass
class ChainCacheEntry:
    """Single-blob cache entry covering one league chain's full graded state.

    Stores raw dicts (not the typed dataclasses) so the cache file is
    self-describing and survives non-breaking schema changes.
    """

    league_id: str
    chain: list[dict[str, Any]]
    resolved_trades: list[dict[str, Any]]
    grades: dict[str, dict[str, Any]]
    display_names: dict[str, str]
    playoff_weeks_by_league: dict[str, int]
    roster_to_user_by_league: dict[str, dict[int, str]]
    league_name_by_id: dict[str, str]
    league_season_by_id: dict[str, int]
    cached_at: str
    warnings: list[str] = field(default_factory=list)


class ChainCache:
    """Single-blob cache for one league chain's full graded state."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        # League IDs are numeric strings; safe filename.
        return self.cache_dir / f"chain_{league_id}.json"

    def read(
        self, league_id: str, max_age_seconds: int = DEFAULT_TTL
    ) -> ChainCacheEntry | None:
        path = self._path(league_id)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > max_age_seconds:
            return None
        with open(path) as f:
            raw = json.load(f)
        # roster_to_user_by_league keys come back as strings from JSON; coerce.
        rmap = raw.get("roster_to_user_by_league") or {}
        coerced = {
            lg: {int(k): v for k, v in (m or {}).items()}
            for lg, m in rmap.items()
        }
        raw["roster_to_user_by_league"] = coerced
        return ChainCacheEntry(**raw)

    def write(self, league_id: str, entry: ChainCacheEntry) -> None:
        path = self._path(league_id)
        with open(path, "w") as f:
            json.dump(asdict(entry), f)

    def invalidate(self, league_id: str) -> None:
        path = self._path(league_id)
        if path.exists():
            path.unlink()
```

- [ ] **Step 5: Confirm pass**

```bash
cd api && pytest tests/test_chain_cache.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add api/app/services/__init__.py api/app/services/chain_cache.py api/tests/test_chain_cache.py
git commit -m "$(cat <<'EOF'
Add ChainCache for single-blob league-chain cache

One JSON blob per starting-league-id holds the fully resolved trades,
grades, display names, and per-league lookup maps. Backed by the
filesystem with 24h default TTL.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: GraderService — async wrapper around build_trade_history + grade_trade

**Files:**
- Create: `api/app/services/grader.py`
- Create: `api/tests/test_grader_service.py`

`GraderService` orchestrates a full chain pull + grading run. Takes a `SleeperClient`, runs the existing pipeline, and emits progress events through a callback. Returns a `ChainCacheEntry` ready to cache.

- [ ] **Step 1: Write failing test**

Create `api/tests/test_grader_service.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.grader import GraderService


@pytest.mark.asyncio
async def test_grader_service_emits_progress_and_returns_entry():
    # Mock SleeperClient + grader engine functions by patching the inputs
    # the service consumes. We use a fake client and pre-built data.
    fake_chain = [
        MagicMock(league_id="L1", name="Bros", season=2026,
                  playoff_week_start=15, total_rosters=2),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p1": {"full_name": "Player One", "position": "RB"},
    })

    # Patch the grader-engine functions used inside GraderService.
    progress_events = []

    async def progress_cb(stage: str, message: str, **extra):
        progress_events.append({"stage": stage, "message": message, **extra})

    svc = GraderService()

    # Inject fakes for the heavy operations the service performs.
    # Patch build_trade_history etc. directly via dependency injection
    # so the service stays testable without network calls.
    async def fake_build_trade_history(client, current_league_id, player_names):
        return []

    async def fake_pull_supporting_data(client, chain):
        return {
            "matchups": {},
            "ktc_by_player_id": {},
            "playoff_weeks_by_league": {"L1": 15},
            "roster_to_user_by_league": {"L1": {1: "u_a"}},
            "league_name_by_id": {"L1": "Bros"},
            "league_season_by_id": {"L1": 2026},
            "display_names": {"u_a": "Alice"},
            "warnings": [],
        }

    entry = await svc.run(
        client=fake_client,
        current_league_id="L1",
        progress_cb=progress_cb,
        _build_trade_history=fake_build_trade_history,
        _pull_supporting_data=fake_pull_supporting_data,
    )

    assert entry.league_id == "L1"
    assert entry.display_names == {"u_a": "Alice"}
    # Progress emitted at least: chain, players, trades, supporting, grading, done
    stages = {e["stage"] for e in progress_events}
    assert {"chain", "players", "trades", "supporting", "grading", "done"} <= stages


@pytest.mark.asyncio
async def test_grader_service_handles_empty_chain_gracefully():
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=[])
    fake_client.get_players = AsyncMock(return_value={})

    progress_events = []

    async def progress_cb(stage, message, **extra):
        progress_events.append({"stage": stage, "message": message})

    async def fake_build(*args, **kwargs):
        return []

    async def fake_pull(*args, **kwargs):
        return {
            "matchups": {}, "ktc_by_player_id": {},
            "playoff_weeks_by_league": {}, "roster_to_user_by_league": {},
            "league_name_by_id": {}, "league_season_by_id": {},
            "display_names": {}, "warnings": ["empty chain"],
        }

    svc = GraderService()
    entry = await svc.run(
        client=fake_client,
        current_league_id="L1",
        progress_cb=progress_cb,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )
    assert entry.warnings == ["empty chain"]
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_grader_service.py -v
```

Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Create `api/app/services/grader.py`**

```python
"""GraderService — async orchestrator for the full grader pipeline.

Wraps the existing build_trade_history + grade_trade + aggregate_owner_records
pipeline with progress reporting + serializable output suitable for
ChainCacheEntry.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.services.chain_cache import ChainCacheEntry

# The grader engine + aggregator from the existing package.
from sleeper_dynasty.engine.trade_grader import (
    aggregate_owner_records,
    grade_trade,
)
from sleeper_dynasty.engine.trade_history import build_trade_history

log = logging.getLogger(__name__)


ProgressCallback = Callable[..., Awaitable[None]]


def _to_dict(obj: Any) -> Any:
    """Best-effort conversion of grader dataclasses to plain dicts.

    Recurses through nested dataclasses (Trade, ResolvedTrade, TradeSide,
    PlayerAsset, etc.) so the result is JSON-serializable.
    """
    if is_dataclass(obj):
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


class GraderService:
    """Async orchestrator: chain walk → grader → ChainCacheEntry."""

    async def run(
        self,
        *,
        client,
        current_league_id: str,
        progress_cb: ProgressCallback,
        _build_trade_history: Callable[..., Awaitable[list]] = build_trade_history,
        _pull_supporting_data: Callable[..., Awaitable[dict]] | None = None,
    ) -> ChainCacheEntry:
        """Run the full pipeline, emitting progress along the way.

        ``_build_trade_history`` and ``_pull_supporting_data`` are injection
        points used by tests to swap in mocks.
        """
        if _pull_supporting_data is None:
            from app.services.grader_io import pull_supporting_data
            _pull_supporting_data = pull_supporting_data

        await progress_cb("chain", "Walking league history")
        chain = await client.walk_league_history(current_league_id)
        chain_summary = [
            {
                "league_id": lg.league_id, "season": lg.season,
                "name": lg.name, "total_rosters": lg.total_rosters,
                "playoff_week_start": lg.playoff_week_start,
            }
            for lg in chain
        ]

        await progress_cb("players", "Loading Sleeper players")
        raw_players = await client.get_players()
        player_names = {
            pid: (raw.get("full_name")
                  or f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip()
                  or pid)
            for pid, raw in raw_players.items()
            if isinstance(raw, dict)
        }

        await progress_cb("trades", "Normalizing trades")
        resolved = await _build_trade_history(
            client, current_league_id=current_league_id, player_names=player_names,
        )

        await progress_cb("supporting", "Fetching matchups + values")
        supporting = await _pull_supporting_data(client, chain)

        await progress_cb("grading", f"Grading {len(resolved)} trades")
        grades = {}
        for rt in resolved:
            g = grade_trade(
                rt,
                ktc_values=supporting["ktc_by_player_id"],
                matchups=supporting["matchups"],
                roster_to_user_by_league=supporting["roster_to_user_by_league"],
                playoff_weeks_by_league=supporting["playoff_weeks_by_league"],
                league_season_by_id=supporting["league_season_by_id"],
                fmt="superflex",
            )
            grades[rt.trade.transaction_id] = _to_dict(g)

        await progress_cb("done", "Building dashboard payload")
        entry = ChainCacheEntry(
            league_id=current_league_id,
            chain=chain_summary,
            resolved_trades=[_to_dict(rt) for rt in resolved],
            grades=grades,
            display_names=supporting["display_names"],
            playoff_weeks_by_league=supporting["playoff_weeks_by_league"],
            roster_to_user_by_league=supporting["roster_to_user_by_league"],
            league_name_by_id=supporting["league_name_by_id"],
            league_season_by_id=supporting["league_season_by_id"],
            cached_at=datetime.now(tz=timezone.utc).isoformat(),
            warnings=supporting.get("warnings", []),
        )
        return entry
```

- [ ] **Step 4: Confirm pass**

```bash
cd api && pytest tests/test_grader_service.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py api/tests/test_grader_service.py
git commit -m "$(cat <<'EOF'
Add GraderService for async chain-pull + grading

Wraps build_trade_history + grade_trade with a progress callback so
the SSE refresh endpoint can stream heartbeats. Returns a
ChainCacheEntry ready to write to ChainCache. Heavy IO lives in a
separate grader_io module (added next) so this service stays testable
with injected fakes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: GraderIO — pull matchups, KTC, FantasyCalc, display names

**Files:**
- Create: `api/app/services/grader_io.py`
- Create: `api/tests/test_grader_io.py`

This is the data-pull layer factored out from the CLI's `_run_trades`. Takes a `SleeperClient` + chain, returns the supporting dict the GraderService needs.

- [ ] **Step 1: Write failing test**

Create `api/tests/test_grader_io.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.grader_io import _assemble_played_matchups


def test_assemble_played_matchups_skips_zero_point_placeholders():
    raw_per_week = {
        3: [
            {"matchup_id": 1, "roster_id": 1, "points": 105.5,
             "starters": ["p1"], "players": ["p1"],
             "players_points": {"p1": 22.0}},
            {"matchup_id": 1, "roster_id": 2, "points": 92.0,
             "starters": ["p2"], "players": ["p2"],
             "players_points": {"p2": 14.0}},
        ],
        4: [
            {"matchup_id": 2, "roster_id": 1, "points": 0.0,
             "starters": ["p1"], "players": ["p1"],
             "players_points": {"p1": 0.0}},
            {"matchup_id": 2, "roster_id": 2, "points": 0.0,
             "starters": ["p2"], "players": ["p2"],
             "players_points": {"p2": 0.0}},
        ],
    }
    out = _assemble_played_matchups(raw_per_week, league_id="L")
    assert ("L", 3, 1) in out
    assert ("L", 4, 1) not in out


def test_assemble_played_matchups_counts_one_sided_shutout():
    raw_per_week = {
        5: [
            {"matchup_id": 1, "roster_id": 1, "points": 80.0,
             "starters": [], "players": [], "players_points": {}},
            {"matchup_id": 1, "roster_id": 2, "points": 0.0,
             "starters": [], "players": [], "players_points": {}},
        ],
    }
    out = _assemble_played_matchups(raw_per_week, league_id="L")
    assert ("L", 5, 1) in out
    assert ("L", 5, 2) in out
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_grader_io.py -v
```

Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Create `api/app/services/grader_io.py`**

```python
"""Data IO for GraderService — fetches matchups, KTC, FantasyCalc.

Lifted from sleeper_dynasty.cli._run_trades so the same logic powers
both the CLI and the API without duplication.
"""

from __future__ import annotations

import logging
from typing import Any

from sleeper_dynasty.api.fantasycalc import fetch_fantasycalc_values
from sleeper_dynasty.api.ktc import fetch_ktc_values
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.util.name_match import normalize_player_name

log = logging.getLogger(__name__)


def _assemble_played_matchups(
    raw_per_week: dict[int, list[dict]],
    league_id: str,
) -> dict[tuple[str, int, int], dict]:
    """Pair Sleeper matchup entries by matchup_id and emit one dict per
    (league_id, week, roster_id) for PLAYED games only.

    Filters out placeholder data Sleeper returns for upcoming weeks
    (both sides zeroed).
    """
    out: dict[tuple[str, int, int], dict] = {}
    for week, raw in raw_per_week.items():
        by_matchup: dict[int, list[dict]] = {}
        for entry in raw:
            by_matchup.setdefault(entry.get("matchup_id"), []).append(entry)
        for entries in by_matchup.values():
            if len(entries) != 2:
                continue
            a, b = entries
            a_pts = a.get("points") or 0.0
            b_pts = b.get("points") or 0.0
            if a_pts == 0.0 and b_pts == 0.0:
                continue
            for x, y in ((a, b), (b, a)):
                out[(league_id, week, x["roster_id"])] = {
                    "starters": x.get("starters") or [],
                    "players": x.get("players") or [],
                    "players_points": x.get("players_points") or {},
                    "team_points": x.get("points"),
                    "opponent_points": y.get("points"),
                }
    return out


async def pull_supporting_data(client, chain) -> dict[str, Any]:
    """Walk the chain to assemble matchups, KTC, FantasyCalc, display names.

    Output keys match the GraderService.run contract.
    """
    warnings: list[str] = []

    # KTC + FantasyCalc — match Sleeper player_id where possible.
    try:
        ktc_values = await fetch_ktc_values()
    except Exception as e:
        log.warning("KTC unavailable: %s", e)
        warnings.append("KTC values unavailable")
        ktc_values = {}
    try:
        fc_values = await fetch_fantasycalc_values()
    except Exception as e:
        log.warning("FantasyCalc unavailable: %s", e)
        warnings.append("FantasyCalc values unavailable")
        fc_values = {}

    raw_players = await client.get_players()
    ktc_by_player_id: dict[str, KTCValue] = {}
    for pid, p in raw_players.items():
        if not isinstance(p, dict):
            continue
        full = (p.get("full_name") or
                f"{p.get('first_name','')} {p.get('last_name','')}".strip())
        v = ktc_values.get(normalize_player_name(full)) if full else None
        if v is not None:
            ktc_by_player_id[pid] = v

    fc_filled = 0
    for pid, fc in fc_values.items():
        if pid in ktc_by_player_id:
            continue
        sf = fc.get("superflex")
        one_qb = fc.get("one_qb")
        if sf is None and one_qb is None:
            continue
        p = raw_players.get(pid) if isinstance(raw_players.get(pid), dict) else None
        full = (p.get("full_name") if p else "") or pid
        ktc_by_player_id[pid] = KTCValue(
            name=full, normalized_name=full,
            position=(p.get("position") if p else "") or "",
            superflex_value=sf, one_qb_value=one_qb,
        )
        fc_filled += 1
    log.info("FantasyCalc filled %d players KTC didn't rank", fc_filled)

    # Matchups + per-league meta.
    matchups: dict[tuple[str, int, int], dict] = {}
    playoff_weeks_by_league: dict[str, int] = {}
    roster_to_user_by_league: dict[str, dict[int, str]] = {}
    league_name_by_id: dict[str, str] = {}
    league_season_by_id: dict[str, int] = {}
    display_names: dict[str, str] = {}

    for lg in chain:
        league_name_by_id[lg.league_id] = lg.name
        playoff_weeks_by_league[lg.league_id] = lg.playoff_week_start
        league_season_by_id[lg.league_id] = lg.season

        rosters = await client.get_rosters(lg.league_id)
        roster_to_user_by_league[lg.league_id] = {
            r.roster_id: r.owner_id for r in rosters
        }
        users = await client.get_users(lg.league_id)
        for uid, info in users.items():
            display_names.setdefault(
                uid, info.get("team_name") or info.get("display_name") or uid,
            )

        raw_per_week: dict[int, list[dict]] = {}
        for week in range(1, 19):
            resp = await client._client.get(
                f"/league/{lg.league_id}/matchups/{week}"
            )
            resp.raise_for_status()
            raw_per_week[week] = resp.json() or []
        matchups.update(_assemble_played_matchups(raw_per_week, lg.league_id))

    return {
        "matchups": matchups,
        "ktc_by_player_id": ktc_by_player_id,
        "playoff_weeks_by_league": playoff_weeks_by_league,
        "roster_to_user_by_league": roster_to_user_by_league,
        "league_name_by_id": league_name_by_id,
        "league_season_by_id": league_season_by_id,
        "display_names": display_names,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Confirm pass**

```bash
cd api && pytest tests/test_grader_io.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader_io.py api/tests/test_grader_io.py
git commit -m "$(cat <<'EOF'
Add grader_io: matchups + KTC + FantasyCalc pull for the API

Lifted from cli._run_trades so both the CLI and the API share one
implementation. Returns the supporting-data dict GraderService.run
consumes. Includes the played-matchup filter from the CLI orchestrator.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Aggregations — year/lens/sort/filter over a cached ChainCacheEntry

**Files:**
- Create: `api/app/services/aggregations.py`
- Create: `api/tests/test_aggregations.py`

Pure functions: take a `ChainCacheEntry` + query params, produce a `DashboardResp`. All in-memory; no IO.

- [ ] **Step 1: Write failing test**

Create `api/tests/test_aggregations.py`:

```python
from __future__ import annotations

import pytest

from app.models.league import DashboardResp
from app.services.aggregations import build_dashboard
from app.services.chain_cache import ChainCacheEntry


def _sample_entry() -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id="L_current",
        chain=[
            {"league_id": "L_current", "season": 2026, "name": "Bros", "total_rosters": 2, "playoff_week_start": 15},
            {"league_id": "L_prev", "season": 2024, "name": "Bros", "total_rosters": 2, "playoff_week_start": 15},
        ],
        resolved_trades=[
            {
                "trade": {
                    "transaction_id": "tx_2024", "league_id": "L_prev", "season": 2024,
                    "week": 2, "traded_at": "2024-09-12T00:00:00+00:00",
                    "sides": {},
                },
                "sides": {
                    "u_alice": {"user_id": "u_alice", "received": [{"name": "Bijan", "player_id": "p_b"}], "given": []},
                    "u_bob": {"user_id": "u_bob", "received": [], "given": [{"name": "Bijan", "player_id": "p_b"}]},
                },
            },
            {
                "trade": {
                    "transaction_id": "tx_2026", "league_id": "L_current", "season": 2026,
                    "week": 1, "traded_at": "2026-05-19T00:00:00+00:00",
                    "sides": {},
                },
                "sides": {
                    "u_alice": {"user_id": "u_alice", "received": [], "given": []},
                    "u_bob": {"user_id": "u_bob", "received": [], "given": []},
                },
            },
        ],
        grades={
            "tx_2024": {
                "trade_id": "tx_2024",
                "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
                "hindsight_production_swing": {"u_alice": 387.4, "u_bob": -387.4},
                "realized_impact_received": {
                    "u_alice": {"starter_weeks": 18, "starter_points_contributed": 286.0,
                                "win_share_points": 198.0, "decisive_starts": 4, "playoff_starts": 2},
                    "u_bob": {"starter_weeks": 0, "starter_points_contributed": 0,
                              "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                },
                "realized_impact_given": {
                    "u_alice": {"starter_weeks": 0, "starter_points_contributed": 0,
                                "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                    "u_bob": {"starter_weeks": 18, "starter_points_contributed": 286.0,
                              "win_share_points": 198.0, "decisive_starts": 4, "playoff_starts": 2},
                },
            },
            "tx_2026": {
                "trade_id": "tx_2026",
                "snapshot_value_swing": {"u_alice": 0, "u_bob": 0},
                "hindsight_production_swing": {"u_alice": 0, "u_bob": 0},
                "realized_impact_received": {
                    "u_alice": {"starter_weeks": 0, "starter_points_contributed": 0,
                                "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                    "u_bob": {"starter_weeks": 0, "starter_points_contributed": 0,
                              "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                },
                "realized_impact_given": {
                    "u_alice": {"starter_weeks": 0, "starter_points_contributed": 0,
                                "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                    "u_bob": {"starter_weeks": 0, "starter_points_contributed": 0,
                              "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                },
            },
        },
        display_names={"u_alice": "Alice", "u_bob": "Bob"},
        playoff_weeks_by_league={"L_current": 15, "L_prev": 15},
        roster_to_user_by_league={"L_current": {1: "u_alice", 2: "u_bob"}, "L_prev": {1: "u_alice", 2: "u_bob"}},
        league_name_by_id={"L_current": "Bros", "L_prev": "Bros"},
        league_season_by_id={"L_current": 2026, "L_prev": 2024},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )


def test_build_dashboard_all_years_includes_every_trade():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert isinstance(resp, DashboardResp)
    assert resp.selected_year == "all"
    assert resp.selected_lens == "ktc"
    # standings: alice positive, bob negative; alice sorts above bob.
    assert resp.standings[0].display_name == "Alice"
    assert resp.standings[0].rank == 1
    assert resp.standings[0].net_ktc == 1450
    assert resp.standings[1].net_ktc == -1450


def test_build_dashboard_year_filter_only_counts_that_year():
    e = _sample_entry()
    resp = build_dashboard(e, year=2024, lens="ktc")
    # Both trades are graded same per-side, but only 2024 should drive standings.
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    assert alice.trades == 1
    assert alice.net_ktc == 1450


def test_build_dashboard_no_trades_for_year_yields_zero_standings():
    e = _sample_entry()
    resp = build_dashboard(e, year=2025, lens="ktc")
    for row in resp.standings:
        assert row.trades == 0
        assert row.net_ktc == 0


def test_build_dashboard_lens_switches_hero_stats_value():
    e = _sample_entry()
    ktc = build_dashboard(e, year=2024, lens="ktc")
    prod = build_dashboard(e, year=2024, lens="production")
    assert ktc.hero_stats.biggest_win.value != prod.hero_stats.biggest_win.value
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_aggregations.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create `api/app/services/aggregations.py`**

```python
"""Pure aggregations: ChainCacheEntry → DashboardResp.

No IO. Server-side filtering for year/lens/sort/filter.
"""

from __future__ import annotations

from typing import Any, Literal

from app.models.league import (
    DashboardResp,
    HeroStat,
    HeroStats,
    LatestTrade,
    LeagueSummary,
    Records,
    StandingRow,
)
from app.services.chain_cache import ChainCacheEntry

Lens = Literal["ktc", "production", "impact"]
Year = int | Literal["all"]


def _filter_trades_by_year(
    entry: ChainCacheEntry, year: Year
) -> list[dict[str, Any]]:
    if year == "all":
        return list(entry.resolved_trades)
    return [rt for rt in entry.resolved_trades if rt["trade"]["season"] == year]


def _grade_for(entry: ChainCacheEntry, trade_id: str) -> dict[str, Any]:
    return entry.grades.get(trade_id) or {}


def _letter_grade(net_ktc: float) -> str:
    if net_ktc >= 1500:
        return "A"
    if net_ktc >= 500:
        return "A−"
    if net_ktc >= 100:
        return "B+"
    if net_ktc >= -100:
        return "B"
    if net_ktc >= -500:
        return "B−"
    if net_ktc >= -1500:
        return "C"
    return "D"


def _aggregate_owner_rows(
    entry: ChainCacheEntry, trades: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for uid, name in entry.display_names.items():
        rows[uid] = {
            "user_id": uid, "display_name": name,
            "net_ktc": 0.0, "net_production": 0.0,
            "trades": 0, "decisive_starts_gained": 0, "playoff_starts_gained": 0,
            "starter_weeks_received": 0, "starter_weeks_given_phantom": 0,
        }
    for rt in trades:
        g = _grade_for(entry, rt["trade"]["transaction_id"])
        for uid, swing in (g.get("snapshot_value_swing") or {}).items():
            row = rows.setdefault(uid, {
                "user_id": uid, "display_name": entry.display_names.get(uid, uid),
                "net_ktc": 0.0, "net_production": 0.0,
                "trades": 0, "decisive_starts_gained": 0, "playoff_starts_gained": 0,
                "starter_weeks_received": 0, "starter_weeks_given_phantom": 0,
            })
            row["net_ktc"] += float(swing or 0)
            row["net_production"] += float(
                (g.get("hindsight_production_swing") or {}).get(uid, 0) or 0
            )
            row["trades"] += 1
            recv = (g.get("realized_impact_received") or {}).get(uid) or {}
            giv = (g.get("realized_impact_given") or {}).get(uid) or {}
            row["decisive_starts_gained"] += int(recv.get("decisive_starts", 0))
            row["playoff_starts_gained"] += int(recv.get("playoff_starts", 0))
            row["starter_weeks_received"] += int(recv.get("starter_weeks", 0))
            row["starter_weeks_given_phantom"] += int(giv.get("starter_weeks", 0))
    return rows


def _trade_swing(
    grade: dict[str, Any], lens: Lens, uid: str
) -> float:
    if lens == "ktc":
        return float((grade.get("snapshot_value_swing") or {}).get(uid, 0) or 0)
    if lens == "production":
        return float((grade.get("hindsight_production_swing") or {}).get(uid, 0) or 0)
    # impact: sum DS + PS as the headline number for "biggest impact"
    recv = (grade.get("realized_impact_received") or {}).get(uid) or {}
    return float(recv.get("decisive_starts", 0)) + float(recv.get("playoff_starts", 0))


def _format_assets_short(side: dict[str, Any]) -> str:
    bits = []
    for a in side.get("received", []):
        bits.append(a.get("name") or a.get("player_id") or "?")
    return "; ".join(bits[:3]) or "—"


def _hero_stats(
    entry: ChainCacheEntry, trades: list[dict[str, Any]], lens: Lens, year: Year
) -> HeroStats:
    activity = HeroStat(value=str(len(trades)), context="trades graded")

    biggest_pos: tuple[float, dict[str, Any] | None, str | None] = (0.0, None, None)
    biggest_neg: tuple[float, dict[str, Any] | None, str | None] = (0.0, None, None)
    activity_by_owner: dict[str, int] = {}

    for rt in trades:
        g = _grade_for(entry, rt["trade"]["transaction_id"])
        for uid in (g.get("snapshot_value_swing") or {}).keys():
            swing = _trade_swing(g, lens, uid)
            if swing > biggest_pos[0]:
                biggest_pos = (swing, rt, uid)
            if swing < biggest_neg[0]:
                biggest_neg = (swing, rt, uid)
            activity_by_owner[uid] = activity_by_owner.get(uid, 0) + 1

    def _hero(pair, color_sign: str) -> HeroStat:
        v, rt, uid = pair
        if rt is None or uid is None:
            return HeroStat(value="—", context="no trades")
        side = (rt["sides"] or {}).get(uid, {})
        other_uids = [u for u in (rt["sides"] or {}).keys() if u != uid]
        counterparty = (
            entry.display_names.get(other_uids[0], "?") if other_uids else "?"
        )
        sign = "+" if v >= 0 else "−"
        magnitude = int(abs(v)) if lens != "production" else round(abs(v), 1)
        owner = entry.display_names.get(uid, uid)
        return HeroStat(
            value=f"{sign}{magnitude}",
            context=f"{owner} · {_format_assets_short(side)}",
            owner=owner, trade_id=rt["trade"]["transaction_id"],
            date=rt["trade"]["traded_at"][:10], counterparty=counterparty,
        )

    biggest_win = _hero(biggest_pos, "+")
    biggest_loss = _hero(biggest_neg, "−")

    if activity_by_owner:
        top_uid = max(activity_by_owner.items(), key=lambda kv: kv[1])[0]
        most_active = HeroStat(
            value=entry.display_names.get(top_uid, top_uid),
            context=f"{activity_by_owner[top_uid]} trades",
        )
    else:
        most_active = HeroStat(value="—", context="no trades")

    return HeroStats(
        activity=activity, biggest_win=biggest_win,
        biggest_loss=biggest_loss, most_active=most_active,
    )


def _latest_trades(
    entry: ChainCacheEntry, trades: list[dict[str, Any]], n: int = 5
) -> list[LatestTrade]:
    sorted_trades = sorted(
        trades, key=lambda rt: rt["trade"]["traded_at"], reverse=True
    )[:n]
    out: list[LatestTrade] = []
    for rt in sorted_trades:
        g = _grade_for(entry, rt["trade"]["transaction_id"])
        # Pick the side with the biggest positive ktc swing for sign.
        ktc_swings = g.get("snapshot_value_swing") or {}
        prod_swings = g.get("hindsight_production_swing") or {}
        parties = [
            entry.display_names.get(uid, uid) for uid in (rt["sides"] or {}).keys()
        ][:3]
        # Asset string: concat each side's received[0].name with arrow
        bits: list[str] = []
        for side in (rt["sides"] or {}).values():
            received = (side or {}).get("received") or []
            if received:
                bits.append(received[0].get("name") or "?")
        assets_short = " ↔ ".join(bits[:2]) if bits else "—"
        # Headline swing = first owner's perspective.
        first_uid = next(iter(ktc_swings.keys()), None)
        out.append(LatestTrade(
            trade_id=rt["trade"]["transaction_id"],
            date=rt["trade"]["traded_at"][:10],
            week=rt["trade"]["week"], parties=parties,
            assets_short=assets_short,
            swing_ktc=float(ktc_swings.get(first_uid, 0) if first_uid else 0),
            swing_prod=float(prod_swings.get(first_uid, 0) if first_uid else 0),
        ))
    return out


def _records(
    entry: ChainCacheEntry, owner_rows: dict[str, dict[str, Any]]
) -> Records:
    if not owner_rows:
        return Records(
            biggest_value_swing=0, biggest_production=0,
            most_decisive=0, most_trades=0,
        )
    top_v = max(owner_rows.values(), key=lambda r: r["net_ktc"])
    top_p = max(owner_rows.values(), key=lambda r: r["net_production"])
    top_d = max(owner_rows.values(), key=lambda r: r["decisive_starts_gained"])
    top_t = max(owner_rows.values(), key=lambda r: r["trades"])
    return Records(
        biggest_value_swing=top_v["net_ktc"],
        biggest_value_swing_owner=top_v["display_name"],
        biggest_production=top_p["net_production"],
        biggest_production_owner=top_p["display_name"],
        most_decisive=top_d["decisive_starts_gained"],
        most_decisive_owner=top_d["display_name"],
        most_trades=top_t["trades"],
        most_trades_owner=top_t["display_name"],
    )


def build_dashboard(
    entry: ChainCacheEntry, year: Year, lens: Lens
) -> DashboardResp:
    """Produce a DashboardResp from a cached chain entry + query params."""
    trades = _filter_trades_by_year(entry, year)
    rows = _aggregate_owner_rows(entry, trades)

    # Standings sort: Net KTC desc by default; rank assigned post-sort.
    sorted_rows = sorted(
        rows.values(), key=lambda r: r["net_ktc"], reverse=True
    )
    standings = [
        StandingRow(
            rank=i + 1,
            user_id=r["user_id"], display_name=r["display_name"],
            net_ktc=r["net_ktc"], net_production=r["net_production"],
            trades=r["trades"],
            ps_plus=r["playoff_starts_gained"],
            grade=_letter_grade(r["net_ktc"]),
        )
        for i, r in enumerate(sorted_rows)
    ]

    seasons = sorted({lg["season"] for lg in entry.chain})
    league = LeagueSummary(
        league_id=entry.league_id,
        name=next((lg["name"] for lg in entry.chain
                   if lg["league_id"] == entry.league_id),
                  entry.league_id),
        season=max(seasons) if seasons else 0,
        total_rosters=next((lg["total_rosters"] for lg in entry.chain
                            if lg["league_id"] == entry.league_id), 0),
        status="active",
        seasons=seasons,
        last_refreshed=entry.cached_at,
    )

    return DashboardResp(
        league=league,
        selected_year=year,
        selected_lens=lens,
        hero_stats=_hero_stats(entry, trades, lens, year),
        standings=standings,
        latest_trades=_latest_trades(entry, trades),
        records=_records(entry, rows),
        warnings=entry.warnings,
    )
```

- [ ] **Step 4: Confirm pass**

```bash
cd api && pytest tests/test_aggregations.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/aggregations.py api/tests/test_aggregations.py
git commit -m "$(cat <<'EOF'
Add aggregations: build DashboardResp from ChainCacheEntry

Pure in-memory transforms. Year filter applied first; standings,
hero stats, latest, and records are all computed from the filtered
set. Lens parameter switches which swing biggest-win/loss reflects.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `/api/lookup` endpoint

**Files:**
- Create: `api/app/routes/lookup.py`
- Modify: `api/app/main.py` (register router)
- Create: `api/tests/test_lookup.py`

- [ ] **Step 1: Write failing test**

Create `api/tests/test_lookup.py`:

```python
from unittest.mock import AsyncMock, patch

from app.models.league import LeagueSummary


def test_lookup_returns_leagues_by_season(client):
    fake_user_id = "u_123"
    fake_leagues = {
        2026: [LeagueSummary(league_id="L1", name="Bros", season=2026,
                             total_rosters=12, status="in_season")],
        2025: [LeagueSummary(league_id="L0", name="Bros", season=2025,
                             total_rosters=12, status="complete")],
    }

    with patch("app.routes.lookup._resolve_user_leagues",
               new=AsyncMock(return_value=(fake_user_id, fake_leagues))):
        resp = client.post("/api/lookup", json={"username": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "u_123"
    assert body["username"] == "alice"
    assert "2026" in body["leagues_by_season"]


def test_lookup_unknown_username_404(client):
    with patch("app.routes.lookup._resolve_user_leagues",
               new=AsyncMock(side_effect=KeyError("unknown"))):
        resp = client.post("/api/lookup", json={"username": "ghost"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_lookup.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create `api/app/routes/lookup.py`**

```python
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.league import LeagueSummary, LookupResp
from sleeper_dynasty.api.sleeper import SleeperClient

log = logging.getLogger(__name__)
router = APIRouter()


class LookupReq(BaseModel):
    username: str


# Seasons we attempt — current year and 4 prior years.
def _seasons_to_check() -> list[int]:
    y = date.today().year
    return [y, y - 1, y - 2, y - 3, y - 4]


async def _resolve_user_leagues(
    username: str,
) -> tuple[str, dict[int, list[LeagueSummary]]]:
    client = SleeperClient()
    try:
        user_id = await client.get_user_id(username)
    except Exception as e:
        raise KeyError(str(e)) from e
    leagues_by_season: dict[int, list[LeagueSummary]] = {}
    for season in _seasons_to_check():
        try:
            leagues = await client.get_leagues(user_id, season)
        except Exception:
            continue
        if leagues:
            leagues_by_season[season] = [
                LeagueSummary(
                    league_id=lg.league_id, name=lg.name, season=lg.season,
                    total_rosters=lg.total_rosters, status=lg.status,
                )
                for lg in leagues
            ]
    await client.close()
    return user_id, leagues_by_season


@router.post("/api/lookup", response_model=LookupResp)
async def lookup(req: LookupReq) -> LookupResp:
    try:
        user_id, leagues_by_season = await _resolve_user_leagues(req.username)
    except KeyError:
        raise HTTPException(status_code=404, detail="Username not found")
    return LookupResp(
        user_id=user_id, username=req.username,
        leagues_by_season=leagues_by_season,
    )
```

- [ ] **Step 4: Register router in `api/app/main.py`**

Inside `create_app`, after the health include line, add:

```python
    from app.routes import lookup
    app.include_router(lookup.router)
```

- [ ] **Step 5: Confirm pass**

```bash
cd api && pytest tests/test_lookup.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/lookup.py api/app/main.py api/tests/test_lookup.py
git commit -m "$(cat <<'EOF'
Add POST /api/lookup endpoint

Resolves a Sleeper username and returns the user's dynasty-relevant
leagues grouped by season for the last 5 years. 404 on unknown
username.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 2 — League endpoint with chain orchestration

### Task 9: `/api/league/{id}` endpoint (warm-cache path)

**Files:**
- Create: `api/app/deps.py`
- Create: `api/app/routes/league.py`
- Modify: `api/app/main.py` (register router)
- Modify: `api/app/config.py` (no change needed — confirm)
- Create: `api/tests/test_league.py`

This task only implements the WARM cache path. The cold-start path comes in Task 10 via the SSE refresh endpoint.

- [ ] **Step 1: Write failing test**

Create `api/tests/test_league.py`:

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed_entry(cache_dir: Path) -> ChainCacheEntry:
    entry = ChainCacheEntry(
        league_id="L_current",
        chain=[
            {"league_id": "L_current", "season": 2026, "name": "Bros",
             "total_rosters": 2, "playoff_week_start": 15},
        ],
        resolved_trades=[],
        grades={},
        display_names={"u_alice": "Alice", "u_bob": "Bob"},
        playoff_weeks_by_league={"L_current": 15},
        roster_to_user_by_league={"L_current": {1: "u_alice", 2: "u_bob"}},
        league_name_by_id={"L_current": "Bros"},
        league_season_by_id={"L_current": 2026},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    cache = ChainCache(cache_dir=cache_dir)
    cache.write("L_current", entry)
    return entry


def test_league_warm_cache_returns_dashboard(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.league._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["league"]["league_id"] == "L_current"
    assert body["selected_year"] == "all"
    assert body["selected_lens"] == "ktc"


def test_league_cold_cache_returns_409(client, tmp_path):
    # No cache file written. Endpoint must NOT block on a cold pull;
    # instead returns 409 so the frontend can kick off the refresh SSE.
    with patch("app.routes.league._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_unseen")
    assert resp.status_code == 409
    body = resp.json()
    assert "cold" in body["detail"].lower()


def test_league_year_param(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.league._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_current?year=2026&lens=production")
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_year"] == 2026
    assert body["selected_lens"] == "production"
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_league.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create `api/app/deps.py`**

```python
from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def get_cache_dir() -> Path:
    return get_settings().cache_dir
```

- [ ] **Step 4: Create `api/app/routes/league.py`**

```python
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.deps import get_cache_dir
from app.models.league import DashboardResp
from app.services.aggregations import build_dashboard
from app.services.chain_cache import ChainCache

log = logging.getLogger(__name__)
router = APIRouter()


def _cache_dir() -> Path:
    """Indirection point; tests patch this to point at tmp_path."""
    return get_cache_dir()


@router.get("/api/league/{league_id}", response_model=DashboardResp)
def league(
    league_id: str,
    year: str = Query("all"),
    lens: Literal["ktc", "production", "impact"] = Query("ktc"),
) -> DashboardResp:
    cache = ChainCache(cache_dir=_cache_dir())
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(
            status_code=409,
            detail="cache cold: kick off refresh via POST /api/league/{id}/refresh",
        )
    if year == "all":
        year_val: int | Literal["all"] = "all"
    else:
        try:
            year_val = int(year)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid year")
    return build_dashboard(entry, year=year_val, lens=lens)
```

- [ ] **Step 5: Register router in `api/app/main.py`**

After the lookup include line:

```python
    from app.routes import league
    app.include_router(league.router)
```

- [ ] **Step 6: Confirm pass**

```bash
cd api && pytest tests/test_league.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add api/app/deps.py api/app/routes/league.py api/app/main.py api/tests/test_league.py
git commit -m "$(cat <<'EOF'
Add GET /api/league/{id} endpoint (warm-cache path)

Reads ChainCacheEntry by league_id and runs build_dashboard with the
requested year + lens. Returns 409 if cache is cold; frontend kicks
off the SSE refresh in response.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

---

### Task 10: `/api/league/{id}/refresh` SSE endpoint

**Files:**
- Create: `api/app/routes/refresh.py`
- Modify: `api/app/main.py` (register router)
- Create: `api/tests/test_refresh.py`

Cold-start path: client POSTs the refresh endpoint, which opens an SSE stream emitting progress events as the chain pull + grading runs. On completion, writes the result to `ChainCache` and emits a `done` event with the dashboard URL.

- [ ] **Step 1: Write failing test**

Create `api/tests/test_refresh.py`:

```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.chain_cache import ChainCacheEntry


def _fake_entry(league_id: str) -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id=league_id, chain=[],
        resolved_trades=[], grades={},
        display_names={}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={},
        league_season_by_id={}, cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )


def test_refresh_streams_events(client, tmp_path):
    async def fake_run(self, *, client, current_league_id, progress_cb,
                       _build_trade_history=None, _pull_supporting_data=None):
        await progress_cb("chain", "Walking")
        await progress_cb("done", "All set")
        return _fake_entry(current_league_id)

    with patch("app.routes.refresh._cache_dir", return_value=tmp_path), \
         patch("app.routes.refresh.GraderService.run", new=fake_run):
        with client.stream("POST", "/api/league/L_new/refresh") as resp:
            assert resp.status_code == 200
            chunks = []
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    chunks.append(json.loads(line[5:].strip()))
    stages = [c["stage"] for c in chunks]
    assert "chain" in stages
    assert "done" in stages


def test_refresh_writes_cache_on_completion(client, tmp_path):
    async def fake_run(self, *, client, current_league_id, progress_cb,
                       _build_trade_history=None, _pull_supporting_data=None):
        await progress_cb("done", "done")
        return _fake_entry(current_league_id)

    with patch("app.routes.refresh._cache_dir", return_value=tmp_path), \
         patch("app.routes.refresh.GraderService.run", new=fake_run):
        with client.stream("POST", "/api/league/L_new/refresh") as resp:
            list(resp.iter_lines())
    cache_file = tmp_path / "chain_L_new.json"
    assert cache_file.exists()
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_refresh.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create `api/app/routes/refresh.py`**

```python
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.deps import get_cache_dir
from app.services.chain_cache import ChainCache
from app.services.grader import GraderService
from sleeper_dynasty.api.sleeper import SleeperClient

log = logging.getLogger(__name__)
router = APIRouter()


def _cache_dir() -> Path:
    return get_cache_dir()


@router.post("/api/league/{league_id}/refresh")
async def refresh(league_id: str) -> EventSourceResponse:
    async def event_stream():
        client = SleeperClient()
        try:
            queue: list[dict] = []

            async def progress_cb(stage: str, message: str, **extra):
                queue.append({"stage": stage, "message": message, **extra})

            svc = GraderService()
            entry = await svc.run(
                client=client, current_league_id=league_id,
                progress_cb=progress_cb,
            )
            # Drain progress events.
            for event in queue:
                yield {"event": "progress", "data": json.dumps(event)}
            # Persist.
            cache = ChainCache(cache_dir=_cache_dir())
            cache.write(league_id, entry)
            yield {"event": "done", "data": json.dumps({"stage": "done"})}
        except Exception as e:
            log.exception("refresh failed")
            yield {"event": "error",
                   "data": json.dumps({"stage": "error", "message": str(e)})}
        finally:
            await client.close()

    return EventSourceResponse(event_stream())
```

- [ ] **Step 4: Register router**

In `api/app/main.py`, after the league include:

```python
    from app.routes import refresh
    app.include_router(refresh.router)
```

- [ ] **Step 5: Confirm pass**

```bash
cd api && pytest tests/test_refresh.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/refresh.py api/app/main.py api/tests/test_refresh.py
git commit -m "$(cat <<'EOF'
Add POST /api/league/{id}/refresh SSE endpoint

Cold-start orchestrator: runs the full GraderService pipeline,
streams progress events via SSE, writes the result to ChainCache
on completion. Frontend opens this stream when GET /api/league
returns 409.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: `/api/league/{id}/owner/{uid}` endpoint

**Files:**
- Create: `api/app/services/owner_view.py`
- Create: `api/app/routes/owner.py`
- Modify: `api/app/main.py` (register router)
- Create: `api/tests/test_owner.py`

- [ ] **Step 1: Write failing test**

Create `api/tests/test_owner.py`:

```python
from unittest.mock import patch

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed(tmp_path):
    entry = ChainCacheEntry(
        league_id="L",
        chain=[
            {"league_id": "L", "season": 2024, "name": "Bros",
             "total_rosters": 2, "playoff_week_start": 15},
        ],
        resolved_trades=[
            {
                "trade": {"transaction_id": "tx1", "league_id": "L",
                          "season": 2024, "week": 2,
                          "traded_at": "2024-09-12T00:00:00+00:00",
                          "sides": {}},
                "sides": {
                    "u_a": {"user_id": "u_a", "received": [], "given": []},
                    "u_b": {"user_id": "u_b", "received": [], "given": []},
                },
            },
        ],
        grades={
            "tx1": {
                "trade_id": "tx1",
                "snapshot_value_swing": {"u_a": 500, "u_b": -500},
                "hindsight_production_swing": {"u_a": 100, "u_b": -100},
                "realized_impact_received": {
                    "u_a": {"starter_weeks": 5, "starter_points_contributed": 80,
                            "win_share_points": 60, "decisive_starts": 2, "playoff_starts": 1},
                    "u_b": {"starter_weeks": 0, "starter_points_contributed": 0,
                            "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                },
                "realized_impact_given": {
                    "u_a": {"starter_weeks": 0, "starter_points_contributed": 0,
                            "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                    "u_b": {"starter_weeks": 5, "starter_points_contributed": 80,
                            "win_share_points": 60, "decisive_starts": 2, "playoff_starts": 1},
                },
            },
        },
        display_names={"u_a": "Alice", "u_b": "Bob"},
        playoff_weeks_by_league={"L": 15},
        roster_to_user_by_league={"L": {1: "u_a", 2: "u_b"}},
        league_name_by_id={"L": "Bros"},
        league_season_by_id={"L": 2024},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    ChainCache(cache_dir=tmp_path).write("L", entry)


def test_owner_detail_returns_career_arc_and_totals(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_a")
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Alice"
    assert body["totals_by_lens"]["ktc"] == 500
    assert body["totals_by_lens"]["production"] == 100
    assert body["best_trade_id"] == "tx1"


def test_owner_detail_unknown_user_404(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_missing")
    assert resp.status_code == 404


def test_owner_detail_cold_cache_409(client, tmp_path):
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_a")
    assert resp.status_code == 409
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_owner.py -v
```

- [ ] **Step 3: Create `api/app/services/owner_view.py`**

```python
from __future__ import annotations

from app.models.owner import OwnerDetailResp, SeasonArc
from app.services.chain_cache import ChainCacheEntry


def build_owner_detail(
    entry: ChainCacheEntry, user_id: str
) -> OwnerDetailResp | None:
    if user_id not in entry.display_names:
        # No owner with that id ever appeared.
        return None

    net_ktc = 0.0
    net_prod = 0.0
    impact_count = 0
    by_season: dict[int, dict[str, float]] = {}
    best_id: str | None = None
    worst_id: str | None = None
    best_swing = float("-inf")
    worst_swing = float("inf")

    for rt in entry.resolved_trades:
        season = rt["trade"]["season"]
        grade = entry.grades.get(rt["trade"]["transaction_id"]) or {}
        swing = float((grade.get("snapshot_value_swing") or {}).get(user_id, 0) or 0)
        if user_id not in (grade.get("snapshot_value_swing") or {}):
            continue
        prod = float((grade.get("hindsight_production_swing") or {}).get(user_id, 0) or 0)
        recv = (grade.get("realized_impact_received") or {}).get(user_id) or {}
        impact = int(recv.get("decisive_starts", 0)) + int(recv.get("playoff_starts", 0))
        net_ktc += swing
        net_prod += prod
        impact_count += impact
        row = by_season.setdefault(season, {"net_ktc": 0.0, "net_production": 0.0, "trades": 0})
        row["net_ktc"] += swing
        row["net_production"] += prod
        row["trades"] += 1
        if swing > best_swing:
            best_swing = swing
            best_id = rt["trade"]["transaction_id"]
        if swing < worst_swing:
            worst_swing = swing
            worst_id = rt["trade"]["transaction_id"]

    arc = [
        SeasonArc(season=s, net_ktc=v["net_ktc"],
                  net_production=v["net_production"], trades=int(v["trades"]))
        for s, v in sorted(by_season.items())
    ]
    return OwnerDetailResp(
        league_id=entry.league_id, user_id=user_id,
        display_name=entry.display_names[user_id],
        totals_by_lens={"ktc": net_ktc, "production": net_prod,
                        "impact": float(impact_count)},
        career_arc=arc,
        best_trade_id=best_id, worst_trade_id=worst_id,
    )
```

- [ ] **Step 4: Create `api/app/routes/owner.py`**

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.deps import get_cache_dir
from app.models.owner import OwnerDetailResp
from app.services.chain_cache import ChainCache
from app.services.owner_view import build_owner_detail

router = APIRouter()


def _cache_dir() -> Path:
    return get_cache_dir()


@router.get(
    "/api/league/{league_id}/owner/{user_id}",
    response_model=OwnerDetailResp,
)
def owner(league_id: str, user_id: str) -> OwnerDetailResp:
    cache = ChainCache(cache_dir=_cache_dir())
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    detail = build_owner_detail(entry, user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="owner not found")
    return detail
```

- [ ] **Step 5: Register router + confirm pass**

In `api/app/main.py` add:

```python
    from app.routes import owner
    app.include_router(owner.router)
```

```bash
cd api && pytest tests/test_owner.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/services/owner_view.py api/app/routes/owner.py api/app/main.py api/tests/test_owner.py
git commit -m "$(cat <<'EOF'
Add GET /api/league/{id}/owner/{uid}

Returns career arc by season, totals across all three lenses, and
best/worst trade IDs for the requested owner. 409 on cold cache,
404 on unknown user.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: `/api/league/{id}/trade/{tid}` endpoint

**Files:**
- Create: `api/app/services/trade_view.py`
- Create: `api/app/routes/trade.py`
- Modify: `api/app/main.py`
- Create: `api/tests/test_trade.py`

- [ ] **Step 1: Write failing test**

Create `api/tests/test_trade.py`:

```python
from unittest.mock import patch

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed(tmp_path):
    entry = ChainCacheEntry(
        league_id="L",
        chain=[{"league_id": "L", "season": 2024, "name": "Bros",
                "total_rosters": 2, "playoff_week_start": 15}],
        resolved_trades=[
            {
                "trade": {"transaction_id": "tx1", "league_id": "L",
                          "season": 2024, "week": 2,
                          "traded_at": "2024-09-12T00:00:00+00:00",
                          "sides": {}},
                "sides": {
                    "u_a": {
                        "user_id": "u_a",
                        "received": [{"name": "Bijan", "player_id": "p_b"}],
                        "given": [{"name": "Adams", "player_id": "p_a"}],
                    },
                    "u_b": {
                        "user_id": "u_b",
                        "received": [{"name": "Adams", "player_id": "p_a"}],
                        "given": [{"name": "Bijan", "player_id": "p_b"}],
                    },
                },
            },
        ],
        grades={
            "tx1": {
                "trade_id": "tx1",
                "snapshot_value_swing": {"u_a": 1450, "u_b": -1450},
                "hindsight_production_swing": {"u_a": 387, "u_b": -387},
                "realized_impact_received": {
                    "u_a": {"starter_weeks": 18, "starter_points_contributed": 286,
                            "win_share_points": 198, "decisive_starts": 4, "playoff_starts": 2},
                    "u_b": {"starter_weeks": 8, "starter_points_contributed": 102,
                            "win_share_points": 60, "decisive_starts": 1, "playoff_starts": 0},
                },
                "realized_impact_given": {
                    "u_a": {"starter_weeks": 8, "starter_points_contributed": 102,
                            "win_share_points": 60, "decisive_starts": 1, "playoff_starts": 0},
                    "u_b": {"starter_weeks": 18, "starter_points_contributed": 286,
                            "win_share_points": 198, "decisive_starts": 4, "playoff_starts": 2},
                },
            },
        },
        display_names={"u_a": "Alice", "u_b": "Bob"},
        playoff_weeks_by_league={"L": 15},
        roster_to_user_by_league={"L": {1: "u_a", 2: "u_b"}},
        league_name_by_id={"L": "Bros"},
        league_season_by_id={"L": 2024},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    ChainCache(cache_dir=tmp_path).write("L", entry)


def test_trade_detail_returns_each_side(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.trade._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/trade/tx1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_id"] == "tx1"
    assert len(body["sides"]) == 2
    alice = next(s for s in body["sides"] if s["user_id"] == "u_a")
    assert alice["snapshot_ktc_swing"] == 1450
    assert alice["realized"]["starter_weeks"] == 18
    assert alice["received"][0]["name"] == "Bijan"


def test_trade_detail_unknown_404(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.trade._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/trade/missing")
    assert resp.status_code == 404
```

- [ ] **Step 2: Confirm fail**

```bash
cd api && pytest tests/test_trade.py -v
```

- [ ] **Step 3: Create `api/app/services/trade_view.py`**

```python
from __future__ import annotations

from app.models.trade import TradeDetailResp, TradeSideView
from app.services.chain_cache import ChainCacheEntry


def build_trade_detail(
    entry: ChainCacheEntry, trade_id: str
) -> TradeDetailResp | None:
    rt = next(
        (r for r in entry.resolved_trades
         if r["trade"]["transaction_id"] == trade_id),
        None,
    )
    if rt is None:
        return None
    grade = entry.grades.get(trade_id) or {}
    sides: list[TradeSideView] = []
    for uid, side in (rt["sides"] or {}).items():
        recv_impact = (grade.get("realized_impact_received") or {}).get(uid) or {}
        sides.append(TradeSideView(
            user_id=uid,
            display_name=entry.display_names.get(uid, uid),
            received=side.get("received") or [],
            given=side.get("given") or [],
            snapshot_ktc_swing=float(
                (grade.get("snapshot_value_swing") or {}).get(uid, 0) or 0
            ),
            hindsight_production_swing=float(
                (grade.get("hindsight_production_swing") or {}).get(uid, 0) or 0
            ),
            realized={
                "starter_weeks": float(recv_impact.get("starter_weeks", 0)),
                "starter_points_contributed": float(
                    recv_impact.get("starter_points_contributed", 0)
                ),
                "win_share_points": float(recv_impact.get("win_share_points", 0)),
                "decisive_starts": float(recv_impact.get("decisive_starts", 0)),
                "playoff_starts": float(recv_impact.get("playoff_starts", 0)),
            },
        ))
    return TradeDetailResp(
        league_id=entry.league_id,
        trade_id=trade_id,
        date=rt["trade"]["traded_at"][:10],
        week=rt["trade"]["week"],
        season=rt["trade"]["season"],
        league_name=entry.league_name_by_id.get(
            rt["trade"]["league_id"], rt["trade"]["league_id"]
        ),
        sides=sides,
    )
```

- [ ] **Step 4: Create `api/app/routes/trade.py`**

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.deps import get_cache_dir
from app.models.trade import TradeDetailResp
from app.services.chain_cache import ChainCache
from app.services.trade_view import build_trade_detail

router = APIRouter()


def _cache_dir() -> Path:
    return get_cache_dir()


@router.get(
    "/api/league/{league_id}/trade/{trade_id}",
    response_model=TradeDetailResp,
)
def trade(league_id: str, trade_id: str) -> TradeDetailResp:
    cache = ChainCache(cache_dir=_cache_dir())
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    detail = build_trade_detail(entry, trade_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="trade not found")
    return detail
```

- [ ] **Step 5: Register router + confirm pass**

In `api/app/main.py`:

```python
    from app.routes import trade
    app.include_router(trade.router)
```

```bash
cd api && pytest tests/test_trade.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/services/trade_view.py api/app/routes/trade.py api/app/main.py api/tests/test_trade.py
git commit -m "$(cat <<'EOF'
Add GET /api/league/{id}/trade/{tid}

Per-side trade view: received / given assets, plus all three lens
swings (snapshot KTC, hindsight production, realized impact bundle).
Frontend renders one column per side.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Full backend suite green

- [ ] **Step 1: Run the entire test suite**

```bash
cd api && pytest -v
```

Expected: all backend tests pass.

- [ ] **Step 2: Spin up the server locally to smoke-test**

```bash
cd api && uvicorn uvicorn_entry:app --port 8000 &
sleep 2
curl -s http://localhost:8000/api/health
kill %1
```

Expected: `{"status":"ok"}`.

- [ ] **Step 3: Commit nothing yet** — Phase 2 already committed each route. Move to Phase 3.

---

# Phase 3 — Frontend foundation

### Task 14: Initialize Next.js app + dependencies

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/next.config.mjs`
- Create: `web/postcss.config.mjs`
- Create: `web/tailwind.config.ts`
- Create: `web/.gitignore`
- Create: `web/app/layout.tsx`
- Create: `web/app/page.tsx`
- Create: `web/app/globals.css`

- [ ] **Step 1: Create `web/package.json`**

```json
{
  "name": "trade-grader-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev -p 3000",
    "build": "next build",
    "start": "next start -p 3000",
    "lint": "next lint",
    "test": "vitest",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "next": "14.2.16",
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "@next/font": "14.2.16",
    "lucide-react": "0.453.0"
  },
  "devDependencies": {
    "typescript": "5.5.4",
    "@types/node": "20.16.5",
    "@types/react": "18.3.5",
    "@types/react-dom": "18.3.0",
    "tailwindcss": "3.4.13",
    "postcss": "8.4.47",
    "autoprefixer": "10.4.20",
    "vitest": "2.1.1",
    "@vitejs/plugin-react": "4.3.1",
    "@testing-library/react": "16.0.1",
    "@testing-library/jest-dom": "6.5.0",
    "@testing-library/user-event": "14.5.2",
    "jsdom": "25.0.0",
    "@playwright/test": "1.47.2",
    "eslint": "8.57.1",
    "eslint-config-next": "14.2.16"
  }
}
```

- [ ] **Step 2: Create `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Create `web/next.config.mjs`**

```js
const API_URL = process.env.API_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_URL}/api/:path*` },
    ];
  },
};

export default nextConfig;
```

- [ ] **Step 4: Create `web/postcss.config.mjs`**

```js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

- [ ] **Step 5: Create `web/tailwind.config.ts`**

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-geist)"],
        mono: ["var(--font-geist-mono)"],
        serif: ["var(--font-instrument-serif)"],
      },
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        ink: "var(--ink)",
        dim: "var(--dim)",
        divider: "var(--divider)",
        pos: "var(--pos)",
        neg: "var(--neg)",
        ringfocus: "var(--ringfocus)",
      },
      borderRadius: {
        card: "10px",
        chip: "4px",
      },
    },
  },
  plugins: [],
};

export default config;
```

- [ ] **Step 6: Create `web/.gitignore`**

```
node_modules
.next
out
.env*.local
coverage
playwright-report
test-results
```

- [ ] **Step 7: Create `web/app/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --bg: #fafaf7;
  --surface: #ffffff;
  --ink: #0e0e0e;
  --dim: #6b6b6b;
  --divider: #e5e5e0;
  --pos: #15803d;
  --neg: #b91c1c;
  --ringfocus: #0e0e0e;
  --pill-a-bg: #f0fdf4;
  --pill-a-border: #bbf7d0;
  --pill-a-text: #14532d;
  --pill-b-bg: #fefce8;
  --pill-b-border: #fef08a;
  --pill-b-text: #854d0e;
  --pill-c-bg: #fef2f2;
  --pill-c-border: #fecaca;
  --pill-c-text: #991b1b;
}

[data-theme="dark"] {
  --bg: #0b0c0d;
  --surface: #131313;
  --ink: #ededed;
  --dim: #9b9ba2;
  --divider: #1f2024;
  --pos: #d9f99d;
  --neg: #fb7185;
  --ringfocus: #ededed;
  --pill-a-bg: #1a2a08;
  --pill-a-border: #3f4a1a;
  --pill-a-text: #d9f99d;
  --pill-b-bg: #2a2008;
  --pill-b-border: #4a3a1a;
  --pill-b-text: #fcd34d;
  --pill-c-bg: #2a0808;
  --pill-c-border: #4a1d1d;
  --pill-c-text: #fca5a5;
}

html, body {
  background: var(--bg);
  color: var(--ink);
  font-feature-settings: "ss01" on;
}

body {
  font-family: var(--font-geist), system-ui, sans-serif;
}

.tabular { font-variant-numeric: tabular-nums; }
```

- [ ] **Step 8: Create `web/app/layout.tsx`**

```tsx
import "./globals.css";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
const instrument = Instrument_Serif({
  subsets: ["latin"], weight: "400", variable: "--font-instrument-serif",
});

export const metadata = {
  title: "dynasty.report",
  description: "Sleeper dynasty trade grader.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geist.variable} ${geistMono.variable} ${instrument.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 9: Create `web/app/page.tsx`** (placeholder; replaced in Task 18)

```tsx
export default function HomePage() {
  return (
    <main className="p-10">
      <h1 className="text-3xl font-bold">dynasty.report</h1>
      <p className="mt-2 text-dim">Coming soon.</p>
    </main>
  );
}
```

- [ ] **Step 10: Install deps and verify build**

```bash
cd web && npm install
npm run build
```

Expected: build succeeds.

- [ ] **Step 11: Commit**

```bash
git add web/package.json web/tsconfig.json web/next.config.mjs web/postcss.config.mjs web/tailwind.config.ts web/.gitignore web/app/globals.css web/app/layout.tsx web/app/page.tsx
git commit -m "$(cat <<'EOF'
Scaffold Next.js 14 app with Tailwind + Geist + Instrument Serif

Light + dark CSS custom-property theme, Tailwind reads from
:root. /api/* rewrites to FastAPI (localhost:8000 by default,
$API_URL in production). Placeholder home page; real pages land in
later tasks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: API client + shared types

**Files:**
- Create: `web/lib/types.ts`
- Create: `web/lib/api.ts`
- Create: `web/tests/vitest.config.ts`
- Create: `web/tests/setup.ts`
- Create: `web/tests/api.test.ts`

- [ ] **Step 1: Create `web/lib/types.ts`**

```ts
export type Lens = "ktc" | "production" | "impact";
export type Year = number | "all";

export interface LeagueSummary {
  league_id: string;
  name: string;
  season: number;
  total_rosters: number;
  status: string;
  seasons?: number[];
  last_refreshed?: string;
}

export interface LookupResp {
  user_id: string;
  username: string;
  leagues_by_season: Record<string, LeagueSummary[]>;
}

export interface HeroStat {
  value: string;
  context: string;
  owner?: string;
  trade_id?: string;
  date?: string;
  counterparty?: string;
}

export interface HeroStats {
  activity: HeroStat;
  biggest_win: HeroStat;
  biggest_loss: HeroStat;
  most_active: HeroStat;
}

export interface StandingRow {
  rank: number;
  user_id: string;
  display_name: string;
  net_ktc: number;
  net_production: number;
  trades: number;
  ps_plus: number;
  grade: string;
}

export interface LatestTrade {
  trade_id: string;
  date: string;
  week: number;
  parties: string[];
  assets_short: string;
  swing_ktc: number;
  swing_prod: number;
}

export interface Records {
  biggest_value_swing: number;
  biggest_value_swing_owner?: string;
  biggest_production: number;
  biggest_production_owner?: string;
  most_decisive: number;
  most_decisive_owner?: string;
  most_trades: number;
  most_trades_owner?: string;
}

export interface DashboardResp {
  league: LeagueSummary;
  selected_year: Year;
  selected_lens: Lens;
  hero_stats: HeroStats;
  standings: StandingRow[];
  latest_trades: LatestTrade[];
  records: Records;
  warnings: string[];
}

export interface SeasonArc {
  season: number;
  net_ktc: number;
  net_production: number;
  trades: number;
}

export interface OwnerDetailResp {
  league_id: string;
  user_id: string;
  display_name: string;
  totals_by_lens: { ktc: number; production: number; impact: number };
  career_arc: SeasonArc[];
  best_trade_id: string | null;
  worst_trade_id: string | null;
}

export interface TradeSideView {
  user_id: string;
  display_name: string;
  received: { kind?: string; name?: string; player_id?: string;
              season?: number; round?: number; via_pick?: any;
              original_owner_user_id?: string }[];
  given: { kind?: string; name?: string; player_id?: string;
           season?: number; round?: number; via_pick?: any;
           original_owner_user_id?: string }[];
  snapshot_ktc_swing: number;
  hindsight_production_swing: number;
  realized: {
    starter_weeks: number;
    starter_points_contributed: number;
    win_share_points: number;
    decisive_starts: number;
    playoff_starts: number;
  };
}

export interface TradeDetailResp {
  league_id: string;
  trade_id: string;
  date: string;
  week: number;
  season: number;
  league_name: string;
  sides: TradeSideView[];
}
```

- [ ] **Step 2: Create `web/lib/api.ts`**

```ts
import {
  DashboardResp, Lens, LookupResp, OwnerDetailResp, TradeDetailResp, Year,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    const detail = await resp
      .json().then((d) => d.detail).catch(() => resp.statusText);
    throw new ApiError(resp.status, String(detail));
  }
  return (await resp.json()) as T;
}

export function lookup(username: string): Promise<LookupResp> {
  return jsonFetch<LookupResp>(`${BASE}/lookup`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username }),
  });
}

export function dashboard(
  leagueId: string,
  opts: { year?: Year; lens?: Lens } = {},
): Promise<DashboardResp> {
  const sp = new URLSearchParams();
  if (opts.year !== undefined) sp.set("year", String(opts.year));
  if (opts.lens) sp.set("lens", opts.lens);
  const qs = sp.toString();
  return jsonFetch<DashboardResp>(
    `${BASE}/league/${leagueId}${qs ? `?${qs}` : ""}`,
  );
}

export function ownerDetail(
  leagueId: string, userId: string,
): Promise<OwnerDetailResp> {
  return jsonFetch<OwnerDetailResp>(
    `${BASE}/league/${leagueId}/owner/${userId}`,
  );
}

export function tradeDetail(
  leagueId: string, tradeId: string,
): Promise<TradeDetailResp> {
  return jsonFetch<TradeDetailResp>(
    `${BASE}/league/${leagueId}/trade/${tradeId}`,
  );
}

export function refreshStream(
  leagueId: string,
  onEvent: (e: { stage: string; message?: string }) => void,
): EventSource {
  // EventSource is used for streaming; the POST is initiated via fetch
  // first to comply with SSE expectations (server emits an open response).
  const es = new EventSource(
    `${BASE}/league/${leagueId}/refresh`,
    { withCredentials: false } as EventSourceInit,
  );
  es.addEventListener("progress", (ev) => {
    onEvent(JSON.parse((ev as MessageEvent).data));
  });
  es.addEventListener("done", (ev) => {
    onEvent(JSON.parse((ev as MessageEvent).data));
    es.close();
  });
  es.addEventListener("error", () => {
    onEvent({ stage: "error", message: "stream error" });
    es.close();
  });
  return es;
}
```

- [ ] **Step 3: Create `web/tests/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["./tests/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: { "@": "/" },
  },
});
```

- [ ] **Step 4: Create `web/tests/setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Create `web/tests/api.test.ts`**

```ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError, dashboard, lookup } from "../lib/api";

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("lookup posts to /api/lookup with body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          user_id: "u1", username: "alice", leagues_by_season: {},
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const out = await lookup("alice");
    expect(out.user_id).toBe("u1");
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/lookup",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("dashboard appends year+lens query params", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );
    await dashboard("L1", { year: 2024, lens: "production" }).catch(() => {});
    const calledWith = fetchSpy.mock.calls[0][0] as string;
    expect(calledWith).toContain("year=2024");
    expect(calledWith).toContain("lens=production");
  });

  it("throws ApiError on non-2xx", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "nope" }), { status: 404 }),
    );
    await expect(lookup("ghost")).rejects.toThrow(ApiError);
  });
});
```

- [ ] **Step 6: Run tests**

```bash
cd web && npm run test -- --run
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/lib/types.ts web/lib/api.ts web/tests/vitest.config.ts web/tests/setup.ts web/tests/api.test.ts
git commit -m "$(cat <<'EOF'
Add typed API client + shared TS types

Mirrors the Pydantic response models for type safety across pages.
lookup / dashboard / ownerDetail / tradeDetail use fetch; refreshStream
opens an EventSource for the SSE pipeline. Vitest config + initial
unit tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: URL-state helper (year/lens/sort/filter ↔ search params)

**Files:**
- Create: `web/lib/url-state.ts`
- Create: `web/tests/url-state.test.ts`

- [ ] **Step 1: Write failing test**

Create `web/tests/url-state.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { encodeDashboardState, decodeDashboardState } from "../lib/url-state";

describe("dashboard URL state", () => {
  it("decode defaults", () => {
    const state = decodeDashboardState(new URLSearchParams(""));
    expect(state.year).toBe("all");
    expect(state.lens).toBe("ktc");
    expect(state.sort).toEqual({ column: "net_ktc", direction: "desc" });
  });

  it("decode round trip", () => {
    const params = new URLSearchParams(
      "year=2024&lens=production&sort=net_production.asc&filter[grade]=A,B",
    );
    const state = decodeDashboardState(params);
    expect(state.year).toBe(2024);
    expect(state.lens).toBe("production");
    expect(state.sort).toEqual({ column: "net_production", direction: "asc" });
    expect(state.filters.grade).toEqual(["A", "B"]);
  });

  it("encode strips defaults", () => {
    const out = encodeDashboardState({
      year: "all", lens: "ktc",
      sort: { column: "net_ktc", direction: "desc" },
      filters: {},
    });
    expect(out).toBe("");
  });

  it("encode keeps non-defaults", () => {
    const out = encodeDashboardState({
      year: 2025, lens: "impact",
      sort: { column: "trades", direction: "desc" },
      filters: { grade: ["A"] },
    });
    expect(out).toContain("year=2025");
    expect(out).toContain("lens=impact");
    expect(out).toContain("sort=trades.desc");
    expect(out).toContain("filter%5Bgrade%5D=A");
  });
});
```

- [ ] **Step 2: Confirm fail**

```bash
cd web && npm run test -- --run url-state
```

- [ ] **Step 3: Create `web/lib/url-state.ts`**

```ts
import { Lens, Year } from "./types";

export type SortDirection = "asc" | "desc";

export interface SortState {
  column: string;
  direction: SortDirection;
}

export interface DashboardState {
  year: Year;
  lens: Lens;
  sort: SortState;
  filters: Record<string, string[] | [number | null, number | null]>;
}

const DEFAULTS: DashboardState = {
  year: "all",
  lens: "ktc",
  sort: { column: "net_ktc", direction: "desc" },
  filters: {},
};

export function decodeDashboardState(sp: URLSearchParams): DashboardState {
  const year = sp.get("year");
  const lens = sp.get("lens") as Lens | null;
  const sortRaw = sp.get("sort");

  let sort: SortState = DEFAULTS.sort;
  if (sortRaw) {
    const [col, dir] = sortRaw.split(".");
    if (col && (dir === "asc" || dir === "desc")) {
      sort = { column: col, direction: dir };
    }
  }

  const filters: DashboardState["filters"] = {};
  sp.forEach((value, key) => {
    const m = key.match(/^filter\[([^\]]+)\](?:\[(gte|lte)\])?$/);
    if (!m) return;
    const col = m[1];
    const op = m[2];
    if (op === "gte" || op === "lte") {
      const cur = (filters[col] as [number | null, number | null] | undefined) ??
        [null, null];
      const n = value === "" ? null : Number(value);
      filters[col] = op === "gte" ? [n, cur[1]] : [cur[0], n];
    } else {
      filters[col] = value.split(",").filter(Boolean);
    }
  });

  return {
    year: year === "all" || year === null ? "all" : Number(year),
    lens: lens && ["ktc", "production", "impact"].includes(lens) ? lens : "ktc",
    sort,
    filters,
  };
}

export function encodeDashboardState(state: DashboardState): string {
  const sp = new URLSearchParams();
  if (state.year !== DEFAULTS.year) sp.set("year", String(state.year));
  if (state.lens !== DEFAULTS.lens) sp.set("lens", state.lens);
  if (
    state.sort.column !== DEFAULTS.sort.column ||
    state.sort.direction !== DEFAULTS.sort.direction
  ) {
    sp.set("sort", `${state.sort.column}.${state.sort.direction}`);
  }
  for (const [col, val] of Object.entries(state.filters)) {
    if (Array.isArray(val) && typeof val[0] === "string") {
      if ((val as string[]).length > 0) {
        sp.set(`filter[${col}]`, (val as string[]).join(","));
      }
    } else if (Array.isArray(val) && val.length === 2) {
      const [lo, hi] = val as [number | null, number | null];
      if (lo !== null) sp.set(`filter[${col}][gte]`, String(lo));
      if (hi !== null) sp.set(`filter[${col}][lte]`, String(hi));
    }
  }
  return sp.toString();
}
```

- [ ] **Step 4: Confirm pass**

```bash
cd web && npm run test -- --run url-state
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/lib/url-state.ts web/tests/url-state.test.ts
git commit -m "$(cat <<'EOF'
Add dashboard URL-state helper

Round-trips year/lens/sort/filters between URLSearchParams and a
typed DashboardState. Defaults strip themselves on encode so clean
URLs don't accrue noise. Numeric range filters use [gte]/[lte]
suffixes; multi-select filters use comma-separated values.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: Theme provider + toggle

**Files:**
- Create: `web/components/ThemeProvider.tsx`
- Create: `web/components/ThemeToggle.tsx`
- Modify: `web/app/layout.tsx` (wrap children in provider)
- Create: `web/tests/ThemeToggle.test.tsx`

- [ ] **Step 1: Write failing test**

Create `web/tests/ThemeToggle.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "../components/ThemeProvider";
import { ThemeToggle } from "../components/ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    localStorage.clear();
  });

  it("toggles between light and dark on click", async () => {
    render(
      <ThemeProvider><ThemeToggle /></ThemeProvider>,
    );
    const btn = screen.getByRole("button", { name: /toggle theme/i });
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    await userEvent.click(btn);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("persists preference to localStorage", async () => {
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    await userEvent.click(screen.getByRole("button", { name: /toggle theme/i }));
    expect(localStorage.getItem("theme")).toBe("dark");
  });
});
```

- [ ] **Step 2: Confirm fail**

```bash
cd web && npm run test -- --run ThemeToggle
```

- [ ] **Step 3: Create `web/components/ThemeProvider.tsx`**

```tsx
"use client";

import { createContext, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark";

interface Ctx {
  theme: Theme;
  setTheme: (t: Theme) => void;
}

const ThemeCtx = createContext<Ctx | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const saved = localStorage.getItem("theme") as Theme | null;
    const initial: Theme = saved
      ?? (window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark" : "light");
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  return (
    <ThemeCtx.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeCtx.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeCtx);
  if (!ctx) throw new Error("useTheme outside ThemeProvider");
  return ctx;
}
```

- [ ] **Step 4: Create `web/components/ThemeToggle.tsx`**

```tsx
"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "./ThemeProvider";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next = theme === "light" ? "dark" : "light";
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label="toggle theme"
      className="rounded-full border border-divider w-10 h-6 relative flex items-center px-1"
    >
      {theme === "light" ? <Sun size={12} /> : <Moon size={12} />}
      <span
        className="absolute top-0.5 w-4 h-4 rounded-full bg-ink transition-all"
        style={{ left: theme === "light" ? "2px" : "calc(100% - 18px)" }}
      />
    </button>
  );
}
```

- [ ] **Step 5: Wrap layout**

Edit `web/app/layout.tsx`, wrap `{children}`:

```tsx
import { ThemeProvider } from "@/components/ThemeProvider";

// ... existing imports ...

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geist.variable} ${geistMono.variable} ${instrument.variable}`}
    >
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 6: Confirm pass**

```bash
cd web && npm run test -- --run ThemeToggle
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/components/ThemeProvider.tsx web/components/ThemeToggle.tsx web/app/layout.tsx web/tests/ThemeToggle.test.tsx
git commit -m "$(cat <<'EOF'
Add ThemeProvider + ThemeToggle

Theme stored on data-theme attribute (matches the CSS custom-property
selector in globals.css). Persists to localStorage and respects
prefers-color-scheme on first visit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 18: Top bar + brand + shell

**Files:**
- Create: `web/components/Brand.tsx`
- Create: `web/components/TopBar.tsx`
- Create: `web/components/Shell.tsx`

- [ ] **Step 1: Create `web/components/Brand.tsx`**

```tsx
export function Brand() {
  return (
    <span className="text-[14px] font-extrabold tracking-tight leading-none">
      dynasty<em className="font-serif font-normal not-italic-ish">{".report"}</em>
    </span>
  );
}
```

Note: the not-italic-ish class is just a placeholder; we use the `italic` class below where needed. Keep this brand mark simple.

- [ ] **Step 2: Create `web/components/TopBar.tsx`**

```tsx
"use client";

import Link from "next/link";
import { ThemeToggle } from "./ThemeToggle";
import { Brand } from "./Brand";

interface Props {
  activeNav?: "dashboard" | "trades" | "owners" | "methodology";
  rightSlot?: React.ReactNode;
}

const NAV: { key: NonNullable<Props["activeNav"]>; label: string; href: string }[] = [
  { key: "dashboard", label: "Dashboard", href: "#" },
  { key: "trades", label: "Trades", href: "#" },
  { key: "owners", label: "Owners", href: "#" },
  { key: "methodology", label: "How this works", href: "/methodology" },
];

export function TopBar({ activeNav, rightSlot }: Props) {
  return (
    <header className="flex items-center justify-between border-b border-divider pb-4 mb-6">
      <Brand />
      <nav className="flex gap-6 text-[12px] text-dim">
        {NAV.map((n) => (
          <Link
            key={n.key}
            href={n.href}
            className={
              activeNav === n.key
                ? "text-ink font-semibold"
                : "hover:text-ink transition-colors"
            }
          >
            {n.label}
          </Link>
        ))}
      </nav>
      <div className="flex items-center gap-3">
        <ThemeToggle />
        {rightSlot}
      </div>
    </header>
  );
}
```

- [ ] **Step 3: Create `web/components/Shell.tsx`**

```tsx
export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="max-w-[1180px] mx-auto px-8 py-6">{children}</div>
  );
}
```

- [ ] **Step 4: Commit (no tests for layout primitives; they're trivial)**

```bash
git add web/components/Brand.tsx web/components/TopBar.tsx web/components/Shell.tsx
git commit -m "$(cat <<'EOF'
Add Brand, TopBar, Shell components

Brand wordmark, top navigation with active state + theme toggle,
page Shell with consistent max-width and padding.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 4 — Frontend pages: landing + league picker + dashboard

### Task 19: Landing page (`/`)

**Files:**
- Modify: `web/app/page.tsx`
- Create: `web/components/UsernameSearch.tsx`

- [ ] **Step 1: Create `web/components/UsernameSearch.tsx`**

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function UsernameSearch() {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      router.push(`/u/${encodeURIComponent(trimmed)}`);
    } catch (err) {
      setError(String(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 max-w-md">
      <label className="text-[10px] font-mono uppercase tracking-widest text-dim">
        Enter your Sleeper username
      </label>
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="flex-1 px-3 py-2 border border-divider rounded-md bg-surface text-ink focus:outline-none focus:border-ink"
          placeholder="e.g. Tkeefe6689"
          autoFocus
        />
        <button
          type="submit"
          disabled={busy}
          className="px-4 py-2 bg-ink text-bg rounded-md font-mono text-[12px] disabled:opacity-50"
        >
          {busy ? "…" : "Find leagues"}
        </button>
      </div>
      {error && <p className="text-[12px] text-neg">{error}</p>}
    </form>
  );
}
```

- [ ] **Step 2: Modify `web/app/page.tsx`**

```tsx
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { UsernameSearch } from "@/components/UsernameSearch";

export default function HomePage() {
  return (
    <Shell>
      <TopBar />
      <section className="mt-16 max-w-2xl">
        <p className="font-mono text-[10px] uppercase tracking-widest text-dim">
          Sleeper dynasty trade grader
        </p>
        <h1 className="mt-2 text-5xl font-extrabold tracking-tight leading-[1.05]">
          Every trade in your dynasty league,{" "}
          <em className="font-serif font-normal italic">graded</em>.
        </h1>
        <p className="mt-4 text-[14px] text-dim leading-relaxed max-w-lg">
          Today&apos;s KTC value swing, points actually scored, and real impact on
          wins — three lenses on every trade, across your full league chain.
        </p>
        <div className="mt-10">
          <UsernameSearch />
        </div>
        <p className="mt-12 font-mono text-[11px] text-dim">
          <a href="/methodology" className="underline">How this works →</a>
        </p>
      </section>
    </Shell>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/app/page.tsx web/components/UsernameSearch.tsx
git commit -m "$(cat <<'EOF'
Add landing page with username search

Hero pitch, single input, routes to /u/{username} on submit. No
backend call yet — the picker page handles the lookup so the URL
holds the username on reload.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 20: League picker page (`/u/[username]`)

**Files:**
- Create: `web/app/u/[username]/page.tsx`
- Create: `web/components/LeagueCard.tsx`

- [ ] **Step 1: Create `web/components/LeagueCard.tsx`**

```tsx
import Link from "next/link";
import { LeagueSummary } from "@/lib/types";

export function LeagueCard({ league }: { league: LeagueSummary }) {
  return (
    <Link
      href={`/league/${league.league_id}`}
      className="block p-4 border border-divider rounded-card bg-surface hover:bg-bg transition-colors"
    >
      <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
        {league.season} · {league.status}
      </div>
      <div className="mt-1 text-[16px] font-semibold tracking-tight">{league.name}</div>
      <div className="mt-2 font-mono text-[11px] text-dim">
        {league.total_rosters} teams
      </div>
    </Link>
  );
}
```

- [ ] **Step 2: Create `web/app/u/[username]/page.tsx`**

```tsx
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { LeagueCard } from "@/components/LeagueCard";
import { lookup } from "@/lib/api";
import { redirect } from "next/navigation";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function PickerPage({
  params,
}: {
  params: { username: string };
}) {
  let data;
  try {
    data = await lookup(params.username);
  } catch (err) {
    return (
      <Shell>
        <TopBar />
        <section className="mt-16">
          <p className="font-mono text-[10px] uppercase tracking-widest text-dim">
            Couldn&apos;t find that user
          </p>
          <h1 className="mt-2 text-3xl font-extrabold tracking-tight">
            No Sleeper account named “{params.username}”.
          </h1>
          <p className="mt-4 text-dim text-[14px]">
            Double-check the spelling, then{" "}
            <Link href="/" className="underline">try another</Link>.
          </p>
        </section>
      </Shell>
    );
  }

  const seasons = Object.keys(data.leagues_by_season)
    .map(Number)
    .sort((a, b) => b - a);

  // If the user has exactly one league across all seasons, jump straight to it.
  const allLeagues = seasons.flatMap((s) => data.leagues_by_season[String(s)]);
  if (allLeagues.length === 1) {
    redirect(`/league/${allLeagues[0].league_id}`);
  }

  return (
    <Shell>
      <TopBar />
      <section className="mt-10">
        <p className="font-mono text-[10px] uppercase tracking-widest text-dim">
          {data.username}
        </p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight">
          Pick a league
        </h1>
        {seasons.map((season) => (
          <div key={season} className="mt-8">
            <h2 className="font-mono text-[11px] uppercase tracking-widest text-dim mb-3">
              {season} season
            </h2>
            <div className="grid grid-cols-2 gap-3">
              {data.leagues_by_season[String(season)].map((lg) => (
                <LeagueCard key={lg.league_id} league={lg} />
              ))}
            </div>
          </div>
        ))}
      </section>
    </Shell>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/app/u/[username]/page.tsx web/components/LeagueCard.tsx
git commit -m "$(cat <<'EOF'
Add league picker page (/u/[username])

Server component calls /api/lookup; renders one card per league per
season. Single-league users skip the picker and redirect straight
to /league/{id}. Friendly empty state on unknown username.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 21: Dashboard page shell + warmup hook

**Files:**
- Create: `web/app/league/[id]/page.tsx`
- Create: `web/components/DashboardClient.tsx`
- Create: `web/components/ProgressModal.tsx`

The dashboard fetches the warm cache first. On 409 it opens the SSE refresh stream, shows a progress modal, then re-fetches.

- [ ] **Step 1: Create `web/components/ProgressModal.tsx`**

```tsx
"use client";

interface Props {
  open: boolean;
  events: { stage: string; message?: string }[];
}

const FRIENDLY: Record<string, string> = {
  chain: "Walking your league history",
  players: "Loading Sleeper player database",
  trades: "Normalizing trades",
  supporting: "Fetching matchups, KTC, FantasyCalc",
  grading: "Grading every trade through three lenses",
  done: "Finishing up",
  error: "Something went wrong",
};

export function ProgressModal({ open, events }: Props) {
  if (!open) return null;
  const latest = events[events.length - 1];
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center">
      <div className="bg-surface border border-divider rounded-card p-6 w-[420px]">
        <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
          Loading
        </div>
        <h2 className="mt-2 text-[18px] font-bold tracking-tight">
          {FRIENDLY[latest?.stage ?? "chain"] ?? latest?.stage}
        </h2>
        <p className="mt-3 text-[12px] text-dim">
          First-time loads take ~30 seconds. We&apos;ll cache the result so this
          stays fast for you and your league.
        </p>
        <ol className="mt-4 space-y-1">
          {events.map((e, i) => (
            <li
              key={i}
              className={`font-mono text-[10px] ${
                i === events.length - 1 ? "text-ink" : "text-dim"
              }`}
            >
              · {FRIENDLY[e.stage] ?? e.stage}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `web/components/DashboardClient.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { ApiError, dashboard, refreshStream } from "@/lib/api";
import { DashboardResp, Lens, Year } from "@/lib/types";
import { ProgressModal } from "./ProgressModal";

interface Props {
  leagueId: string;
  initialYear: Year;
  initialLens: Lens;
}

export function DashboardClient({ leagueId, initialYear, initialLens }: Props) {
  const [data, setData] = useState<DashboardResp | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [events, setEvents] = useState<{ stage: string; message?: string }[]>(
    [],
  );

  async function loadOrRefresh() {
    try {
      const d = await dashboard(leagueId, { year: initialYear, lens: initialLens });
      setData(d);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRefreshing(true);
        setEvents([]);
        refreshStream(leagueId, async (ev) => {
          setEvents((cur) => [...cur, ev]);
          if (ev.stage === "done") {
            setRefreshing(false);
            const d = await dashboard(leagueId, {
              year: initialYear, lens: initialLens,
            });
            setData(d);
          }
        });
      }
    }
  }

  useEffect(() => {
    loadOrRefresh();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueId, initialYear, initialLens]);

  return (
    <>
      <ProgressModal open={refreshing} events={events} />
      {data && (
        <pre className="font-mono text-[11px]">
          {/* Replaced by real dashboard layout in Task 22. */}
          {JSON.stringify(
            {
              league: data.league.name,
              standings: data.standings.length,
              lens: data.selected_lens,
              year: data.selected_year,
            },
            null,
            2,
          )}
        </pre>
      )}
    </>
  );
}
```

- [ ] **Step 3: Create `web/app/league/[id]/page.tsx`**

```tsx
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { DashboardClient } from "@/components/DashboardClient";
import { Lens, Year } from "@/lib/types";

export const dynamic = "force-dynamic";

export default function LeaguePage({
  params, searchParams,
}: {
  params: { id: string };
  searchParams: { year?: string; lens?: string };
}) {
  const year: Year =
    !searchParams.year || searchParams.year === "all"
      ? "all"
      : Number(searchParams.year);
  const lens: Lens =
    (searchParams.lens as Lens) &&
    ["ktc", "production", "impact"].includes(searchParams.lens!)
      ? (searchParams.lens as Lens)
      : "ktc";

  return (
    <Shell>
      <TopBar activeNav="dashboard" />
      <DashboardClient leagueId={params.id} initialYear={year} initialLens={lens} />
    </Shell>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/app/league/[id]/page.tsx web/components/DashboardClient.tsx web/components/ProgressModal.tsx
git commit -m "$(cat <<'EOF'
Add dashboard page shell + cold-start SSE flow

Server component reads year/lens from search params; client component
calls /api/league and falls back to the SSE refresh stream on 409
with a progress modal. The actual dashboard chrome lands in the
next tasks; this commit gets data flowing end-to-end.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 22: Dashboard layout — league header + year tabs + lens switcher

**Files:**
- Create: `web/components/LeagueHeader.tsx`
- Create: `web/components/YearTabs.tsx`
- Create: `web/components/LensSwitcher.tsx`
- Create: `web/components/InfoTooltip.tsx`
- Create: `web/components/ShareUrlButton.tsx`
- Modify: `web/components/DashboardClient.tsx`

- [ ] **Step 1: Create `web/components/InfoTooltip.tsx`**

```tsx
"use client";

import { useState } from "react";

interface Props {
  title: string;
  body: string;
  formula?: string;
}

export function InfoTooltip({ title, body, formula }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block">
      <button
        type="button"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="inline-flex w-3.5 h-3.5 items-center justify-center rounded-full bg-divider text-dim text-[9px] font-bold leading-none"
        aria-label={`info: ${title}`}
      >
        i
      </button>
      {open && (
        <span className="absolute z-40 left-0 top-5 w-72 bg-ink text-bg rounded-md p-3 shadow-lg">
          <span className="block font-mono text-[9px] uppercase tracking-widest opacity-70">
            {title}
          </span>
          <span className="block mt-1 text-[11px] leading-relaxed">{body}</span>
          {formula && (
            <span className="block mt-2 font-mono text-[10px] bg-white/5 rounded px-2 py-1">
              {formula}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
```

- [ ] **Step 2: Create `web/components/YearTabs.tsx`**

```tsx
"use client";

import { useRouter } from "next/navigation";
import { Year } from "@/lib/types";

interface Props {
  seasons: number[];
  current: Year;
  leagueId: string;
  lens: string;
}

export function YearTabs({ seasons, current, leagueId, lens }: Props) {
  const router = useRouter();
  const choose = (y: Year) => {
    const sp = new URLSearchParams();
    if (y !== "all") sp.set("year", String(y));
    if (lens !== "ktc") sp.set("lens", lens);
    const qs = sp.toString();
    router.push(`/league/${leagueId}${qs ? `?${qs}` : ""}`);
  };

  const items: { key: string; label: string; value: Year }[] = [
    ...seasons.map((s) => ({ key: String(s), label: String(s), value: s as Year })),
    { key: "all", label: "All years", value: "all" as Year },
  ];

  return (
    <div className="flex gap-1 border-b border-divider mb-5">
      {items.map((it) => {
        const active = String(it.value) === String(current);
        return (
          <button
            key={it.key}
            onClick={() => choose(it.value)}
            className={`px-3.5 py-2.5 font-mono text-[11px] tracking-wide -mb-px border-b-2 ${
              active
                ? "text-ink font-bold border-ink"
                : "text-dim border-transparent hover:text-ink"
            }`}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Create `web/components/LensSwitcher.tsx`**

```tsx
"use client";

import { useRouter } from "next/navigation";
import { Lens } from "@/lib/types";

interface Props {
  current: Lens;
  leagueId: string;
  year: string | number;
}

const OPTS: { value: Lens; label: string }[] = [
  { value: "ktc", label: "by KTC" },
  { value: "production", label: "by Production" },
  { value: "impact", label: "by Impact" },
];

export function LensSwitcher({ current, leagueId, year }: Props) {
  const router = useRouter();
  const choose = (l: Lens) => {
    const sp = new URLSearchParams();
    if (String(year) !== "all") sp.set("year", String(year));
    if (l !== "ktc") sp.set("lens", l);
    router.push(`/league/${leagueId}${sp.toString() ? `?${sp}` : ""}`);
  };
  return (
    <div className="inline-flex border border-divider rounded-md bg-surface p-0.5 gap-0">
      {OPTS.map((o) => (
        <button
          key={o.value}
          onClick={() => choose(o.value)}
          className={`px-3 py-1.5 font-mono text-[10px] tracking-wide rounded ${
            current === o.value ? "bg-ink text-bg font-bold" : "text-dim hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Create `web/components/ShareUrlButton.tsx`**

```tsx
"use client";

import { useState } from "react";

export function ShareUrlButton() {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(window.location.href);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="font-mono text-[11px] px-3 py-1.5 border border-divider rounded-md text-dim bg-surface hover:text-ink"
    >
      ⎘ {copied ? "copied" : "copy share URL"}
    </button>
  );
}
```

- [ ] **Step 5: Create `web/components/LeagueHeader.tsx`**

```tsx
import { ShareUrlButton } from "./ShareUrlButton";
import { LeagueSummary } from "@/lib/types";

export function LeagueHeader({ league, totalTrades }: {
  league: LeagueSummary;
  totalTrades: number;
}) {
  const seasonRange = league.seasons && league.seasons.length > 1
    ? `${Math.min(...league.seasons)} – ${Math.max(...league.seasons)}`
    : String(league.season);
  return (
    <div className="flex justify-between items-end mb-5">
      <div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
          League · {seasonRange}
        </div>
        <h1 className="mt-1 text-3xl font-extrabold tracking-tight leading-none">
          {league.name}
        </h1>
        <p className="mt-1.5 text-[12px] text-dim">
          {league.total_rosters} teams · {totalTrades} trades graded
          {league.last_refreshed
            ? ` · refreshed ${new Date(league.last_refreshed).toLocaleString()}`
            : ""}
        </p>
      </div>
      <ShareUrlButton />
    </div>
  );
}
```

- [ ] **Step 6: Replace `web/components/DashboardClient.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { ApiError, dashboard, refreshStream } from "@/lib/api";
import { DashboardResp, Lens, Year } from "@/lib/types";
import { ProgressModal } from "./ProgressModal";
import { LeagueHeader } from "./LeagueHeader";
import { YearTabs } from "./YearTabs";
import { LensSwitcher } from "./LensSwitcher";

interface Props {
  leagueId: string;
  initialYear: Year;
  initialLens: Lens;
}

export function DashboardClient({ leagueId, initialYear, initialLens }: Props) {
  const [data, setData] = useState<DashboardResp | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [events, setEvents] = useState<{ stage: string; message?: string }[]>(
    [],
  );

  async function loadOrRefresh() {
    try {
      const d = await dashboard(leagueId, { year: initialYear, lens: initialLens });
      setData(d);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRefreshing(true);
        setEvents([]);
        refreshStream(leagueId, async (ev) => {
          setEvents((cur) => [...cur, ev]);
          if (ev.stage === "done") {
            setRefreshing(false);
            const d = await dashboard(leagueId, {
              year: initialYear, lens: initialLens,
            });
            setData(d);
          }
        });
      }
    }
  }

  useEffect(() => {
    loadOrRefresh();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueId, initialYear, initialLens]);

  if (!data) {
    return <ProgressModal open={refreshing} events={events} />;
  }

  const seasons = data.league.seasons ?? [data.league.season];
  return (
    <>
      <ProgressModal open={refreshing} events={events} />
      <LeagueHeader league={data.league} totalTrades={data.standings.length > 0
        ? data.records.most_trades * 0  /* placeholder; real value below */
        : 0} />
      <YearTabs
        seasons={seasons}
        current={data.selected_year}
        leagueId={leagueId}
        lens={data.selected_lens}
      />
      <div className="flex justify-between items-end mb-3">
        <div>
          <div className="text-[13px] font-semibold tracking-tight">
            Trade highlights {data.selected_year === "all"
              ? "(all years)"
              : `for ${data.selected_year}`}
          </div>
          <div className="text-[11px] text-dim">
            Switch lens: "by KTC" = today&apos;s market · "by Production" = points
            scored · "by Impact" = decisive + playoff starts
          </div>
        </div>
        <LensSwitcher
          current={data.selected_lens}
          leagueId={leagueId}
          year={String(data.selected_year)}
        />
      </div>
      <pre className="font-mono text-[11px] mt-6">
        {JSON.stringify({ standings: data.standings.length }, null, 2)}
      </pre>
    </>
  );
}
```

> Note the `totalTrades` calc is a temporary placeholder; the next task (hero stats) wires it through properly. Build will still work.

- [ ] **Step 7: Verify build**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 8: Commit**

```bash
git add web/components/InfoTooltip.tsx web/components/YearTabs.tsx web/components/LensSwitcher.tsx web/components/ShareUrlButton.tsx web/components/LeagueHeader.tsx web/components/DashboardClient.tsx
git commit -m "$(cat <<'EOF'
Add dashboard chrome: league header, year tabs, lens switcher

URL-driven year + lens with router.push so back/forward works.
Share URL button copies window.location.href. Tooltip primitive
ready for use on hero stats and standings columns.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

This plan is approaching the practical limit for one document. Phases 5–6 (hero stat cards, standings table, sidebar, owner detail, trade detail, methodology, Railway deployment) follow the same task pattern and are documented in `docs/superpowers/plans/2026-05-28-trade-grader-web-app-part2.md` (added in the next plan-writing session).

For executors: continue with the next plan file when this one is exhausted.

