# Trade Titles + Owner Name Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Short LLM trade headlines (prompt already updated) + a `/league/[id]/settings` page to map Sleeper handles to friendly display names applied everywhere.

**Architecture:** A new `NameOverrideStore` service mirrors the existing `ProfileStore` pattern — per-league JSON file in the cache dir, keyed by Sleeper `user_id`. Routes that serve owner data apply overrides by calling `apply_name_overrides(entry, overrides)` (mutates `entry.owners` in place) after reading from `ChainCache`. Story generation in `grader.py` applies the same overrides when building `owners_display`. The frontend adds `web/lib/api.ts` functions and a new `"use client"` form component + server page.

**Tech Stack:** Python/FastAPI (backend), Next.js 14 App Router + Tailwind (frontend), existing `ProfileStore` pattern for persistence.

---

## File Map

**Create:**
- `api/app/services/name_override_store.py` — read/write override JSON per league
- `api/app/routes/settings.py` — GET/PUT `/api/league/{id}/owner-names`
- `web/components/OwnerNamesForm.tsx` — interactive form (client component)
- `web/app/league/[id]/settings/page.tsx` — settings page (server component)
- `api/tests/test_name_override_store.py`
- `api/tests/test_settings_route.py`

**Modify:**
- `api/app/services/identity.py` — add `apply_name_overrides()`
- `api/app/main.py` — register settings router
- `api/app/routes/league.py` — apply overrides after cache read
- `api/app/routes/trade.py` — apply overrides after cache read
- `api/app/routes/owner.py` — apply overrides after cache read
- `api/app/routes/leaderboard.py` — apply overrides after cache read
- `api/app/services/grader.py` — apply overrides in `owners_display` builder
- `web/lib/types.ts` — add `OwnerNameEntry`, `OwnerNamesResp`
- `web/lib/api.ts` — add `getOwnerNames()`, `putOwnerNames()`
- `web/components/TopBar.tsx` — add Settings nav link

---

## Task 1: NameOverrideStore service

**Files:**
- Create: `api/app/services/name_override_store.py`
- Create (test): `api/tests/test_name_override_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_name_override_store.py
from pathlib import Path
from app.services.name_override_store import NameOverrideStore


def test_read_returns_empty_dict_when_file_absent(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    assert store.read("L1") == {}


def test_write_then_read_round_trips(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    overrides = {"u_tom": "Tom", "u_jake": "Jake"}
    store.write("L1", overrides)
    assert store.read("L1") == overrides


def test_write_creates_parent_dir(tmp_path):
    deep = tmp_path / "nested" / "dir"
    store = NameOverrideStore(cache_dir=deep)
    store.write("L1", {"u_tom": "Tom"})
    assert store.read("L1") == {"u_tom": "Tom"}


def test_write_overwrites_previous(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    store.write("L1", {"u_tom": "Tommy"})
    store.write("L1", {"u_tom": "Tom"})
    assert store.read("L1") == {"u_tom": "Tom"}


def test_separate_leagues_dont_collide(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    store.write("L1", {"u_tom": "Tom"})
    store.write("L2", {"u_tom": "Thomas"})
    assert store.read("L1") == {"u_tom": "Tom"}
    assert store.read("L2") == {"u_tom": "Thomas"}
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd api && pytest tests/test_name_override_store.py -v
```

Expected: `ImportError: cannot import name 'NameOverrideStore'`

- [ ] **Step 3: Create the service**

```python
# api/app/services/name_override_store.py
from __future__ import annotations

import json
from pathlib import Path


class NameOverrideStore:
    """Per-league display name overrides: {user_id -> display_name}.

    Persists indefinitely in the same cache dir as ChainCache and ProfileStore.
    File: owner_name_overrides_{league_id}.json
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        return self.cache_dir / f"owner_name_overrides_{league_id}.json"

    def read(self, league_id: str) -> dict[str, str]:
        path = self._path(league_id)
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def write(self, league_id: str, overrides: dict[str, str]) -> None:
        with open(self._path(league_id), "w") as f:
            json.dump(overrides, f)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd api && pytest tests/test_name_override_store.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add api/app/services/name_override_store.py api/tests/test_name_override_store.py
git commit -m "feat: NameOverrideStore — per-league display name override persistence"
```

---

## Task 2: identity.apply_name_overrides

**Files:**
- Modify: `api/app/services/identity.py`

- [ ] **Step 1: Write failing tests**

Add to `api/tests/test_name_override_store.py` (append at bottom):

```python
from app.services.identity import apply_name_overrides
from app.services.chain_cache import ChainCacheEntry


def _make_entry(owners: dict) -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id="L1",
        chain=[],
        resolved_trades=[],
        grades={},
        owners=owners,
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="2026-01-01T00:00:00Z",
    )


def test_apply_name_overrides_mutates_owner_name():
    entry = _make_entry({"u_tom": {"owner_name": "tkeefe66", "team_name": None, "avatar_url": None}})
    apply_name_overrides(entry, {"u_tom": "Tom"})
    assert entry.owners["u_tom"]["owner_name"] == "Tom"


def test_apply_name_overrides_ignores_unknown_uids():
    entry = _make_entry({"u_tom": {"owner_name": "tkeefe66", "team_name": None, "avatar_url": None}})
    apply_name_overrides(entry, {"u_unknown": "Ghost"})
    assert entry.owners["u_tom"]["owner_name"] == "tkeefe66"


def test_apply_name_overrides_preserves_other_fields():
    entry = _make_entry({"u_tom": {"owner_name": "tkeefe66", "team_name": "Eagles", "avatar_url": "http://x.com/a.png"}})
    apply_name_overrides(entry, {"u_tom": "Tom"})
    assert entry.owners["u_tom"]["team_name"] == "Eagles"
    assert entry.owners["u_tom"]["avatar_url"] == "http://x.com/a.png"


def test_apply_name_overrides_empty_overrides_is_noop():
    entry = _make_entry({"u_tom": {"owner_name": "tkeefe66", "team_name": None, "avatar_url": None}})
    apply_name_overrides(entry, {})
    assert entry.owners["u_tom"]["owner_name"] == "tkeefe66"
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd api && pytest tests/test_name_override_store.py -k "apply_name" -v
```

Expected: `ImportError: cannot import name 'apply_name_overrides'`

- [ ] **Step 3: Add apply_name_overrides to identity.py**

Replace the full contents of `api/app/services/identity.py`:

```python
from __future__ import annotations

from app.models.common import OwnerRef
from app.services.chain_cache import ChainCacheEntry


def owner_name(entry: ChainCacheEntry, uid: str) -> str:
    """The owner's handle, falling back to the raw user_id."""
    return (entry.owners.get(uid) or {}).get("owner_name") or uid


def owner_ref(entry: ChainCacheEntry, uid: str) -> OwnerRef:
    o = entry.owners.get(uid) or {}
    return OwnerRef(
        user_id=uid,
        owner_name=o.get("owner_name") or uid,
        team_name=o.get("team_name"),
        avatar_url=o.get("avatar_url"),
    )


def apply_name_overrides(entry: ChainCacheEntry, overrides: dict[str, str]) -> None:
    """Mutate entry.owners in place, applying display name overrides.

    Only touches uids present in both overrides and entry.owners.
    Called once after reading ChainCache, so all downstream services
    (aggregations, trade_view, owner_view, leaderboard) see friendly names.
    """
    for uid, name in overrides.items():
        if uid in entry.owners:
            entry.owners[uid] = {**(entry.owners[uid] or {}), "owner_name": name}
```

- [ ] **Step 4: Run all identity tests**

```bash
cd api && pytest tests/test_name_override_store.py -v
```

Expected: all tests pass (including the 5 from Task 1 + 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add api/app/services/identity.py api/tests/test_name_override_store.py
git commit -m "feat: identity.apply_name_overrides — mutate entry.owners with display name overrides"
```

---

## Task 3: Settings routes + registration

**Files:**
- Create: `api/app/routes/settings.py`
- Modify: `api/app/main.py`
- Create (test): `api/tests/test_settings_route.py`

- [ ] **Step 1: Write failing tests**

```python
# api/tests/test_settings_route.py
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed_entry(cache_dir: Path) -> ChainCacheEntry:
    entry = ChainCacheEntry(
        league_id="L1",
        chain=[{"league_id": "L1", "season": 2024, "name": "Bros",
                "total_rosters": 2, "playoff_week_start": 15}],
        resolved_trades=[],
        grades={},
        owners={
            "u_tom": {"owner_name": "tkeefe66", "team_name": None, "avatar_url": None},
            "u_jake": {"owner_name": "jakeman99", "team_name": None, "avatar_url": None},
        },
        playoff_weeks_by_league={"L1": 15},
        roster_to_user_by_league={"L1": {1: "u_tom", 2: "u_jake"}},
        league_name_by_id={"L1": "Bros"},
        league_season_by_id={"L1": 2024},
        cached_at="2026-01-01T00:00:00Z",
    )
    ChainCache(cache_dir=cache_dir).write("L1", entry)
    return entry


def test_get_owner_names_warm_cache(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L1/owner-names")
    assert resp.status_code == 200
    body = resp.json()
    uids = {o["user_id"] for o in body["owners"]}
    assert uids == {"u_tom", "u_jake"}
    # No overrides yet — display_name should be None
    for o in body["owners"]:
        assert o["display_name"] is None


def test_get_owner_names_cold_cache_returns_409(client, tmp_path):
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L1/owner-names")
    assert resp.status_code == 409


def test_put_owner_names_saves_and_get_reflects_overrides(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        put_resp = client.put(
            "/api/league/L1/owner-names",
            json={"overrides": {"u_tom": "Tom", "u_jake": "Jake"}},
        )
        assert put_resp.status_code == 200
        get_resp = client.get("/api/league/L1/owner-names")
    assert get_resp.status_code == 200
    by_uid = {o["user_id"]: o["display_name"] for o in get_resp.json()["owners"]}
    assert by_uid["u_tom"] == "Tom"
    assert by_uid["u_jake"] == "Jake"


def test_put_owner_names_ignores_unknown_uids(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        client.put(
            "/api/league/L1/owner-names",
            json={"overrides": {"u_ghost": "Ghost", "u_tom": "Tom"}},
        )
        resp = client.get("/api/league/L1/owner-names")
    by_uid = {o["user_id"]: o["display_name"] for o in resp.json()["owners"]}
    assert by_uid["u_tom"] == "Tom"
    assert "u_ghost" not in by_uid


def test_put_owner_names_strips_empty_strings(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        client.put(
            "/api/league/L1/owner-names",
            json={"overrides": {"u_tom": "  ", "u_jake": "Jake"}},
        )
        resp = client.get("/api/league/L1/owner-names")
    by_uid = {o["user_id"]: o["display_name"] for o in resp.json()["owners"]}
    assert by_uid["u_tom"] is None  # whitespace-only stripped
    assert by_uid["u_jake"] == "Jake"
```

- [ ] **Step 2: Run tests — expect 404 (route not registered yet)**

```bash
cd api && pytest tests/test_settings_route.py -v
```

Expected: all fail with 404 (route doesn't exist yet)

- [ ] **Step 3: Create the settings route**

```python
# api/app/routes/settings.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.deps import get_cache_dir
from app.services.chain_cache import ChainCache
from app.services.name_override_store import NameOverrideStore

router = APIRouter()


class OwnerNameEntry(BaseModel):
    user_id: str
    sleeper_name: str
    display_name: str | None = None


class OwnerNamesResp(BaseModel):
    owners: list[OwnerNameEntry]


class OwnerNamesReq(BaseModel):
    overrides: dict[str, str]


def _cache_dir() -> Path:
    return get_cache_dir()


@router.get("/api/league/{league_id}/owner-names", response_model=OwnerNamesResp)
def get_owner_names(league_id: str) -> OwnerNamesResp:
    entry = ChainCache(cache_dir=_cache_dir()).read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    overrides = NameOverrideStore(cache_dir=_cache_dir()).read(league_id)
    owners = sorted(
        [
            OwnerNameEntry(
                user_id=uid,
                sleeper_name=(o or {}).get("owner_name") or uid,
                display_name=overrides.get(uid) or None,
            )
            for uid, o in (entry.owners or {}).items()
        ],
        key=lambda x: x.sleeper_name,
    )
    return OwnerNamesResp(owners=owners)


@router.put("/api/league/{league_id}/owner-names", status_code=200)
def put_owner_names(league_id: str, body: OwnerNamesReq) -> dict:
    entry = ChainCache(cache_dir=_cache_dir()).read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    cleaned = {
        k: v.strip()
        for k, v in body.overrides.items()
        if v and v.strip() and k in (entry.owners or {})
    }
    NameOverrideStore(cache_dir=_cache_dir()).write(league_id, cleaned)
    return {"ok": True}
```

- [ ] **Step 4: Register the router in main.py**

In `api/app/main.py`, add after the `leaderboard` router block (line ~60):

```python
    from app.routes import settings
    app.include_router(settings.router)
```

The full router registration block in `create_app()` should end up as:
```python
    from app.routes import health
    app.include_router(health.router)
    from app.routes import league
    app.include_router(league.router)
    from app.routes import refresh
    app.include_router(refresh.router)
    from app.routes import owner
    app.include_router(owner.router)
    from app.routes import trade
    app.include_router(trade.router)
    from app.routes import profiles
    app.include_router(profiles.router)
    from app.routes import leaderboard
    app.include_router(leaderboard.router)
    from app.routes import settings
    app.include_router(settings.router)
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
cd api && pytest tests/test_settings_route.py -v
```

Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/settings.py api/app/main.py api/tests/test_settings_route.py
git commit -m "feat: GET/PUT /api/league/{id}/owner-names — settings route for display name overrides"
```

---

## Task 4: Apply overrides in read-entry routes

Four routes that read `ChainCacheEntry` and pass it downstream — add 2 lines to each after the `None` check.

**Files:**
- Modify: `api/app/routes/league.py`
- Modify: `api/app/routes/trade.py`
- Modify: `api/app/routes/owner.py`
- Modify: `api/app/routes/leaderboard.py`

- [ ] **Step 1: Update league.py**

Add imports at the top of `api/app/routes/league.py` (after existing imports):
```python
from app.services.identity import apply_name_overrides
from app.services.name_override_store import NameOverrideStore
```

In the `league()` handler, add 2 lines after `if entry is None: raise HTTPException(...)`:
```python
    overrides = NameOverrideStore(cache_dir=_cache_dir()).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
```

- [ ] **Step 2: Update trade.py**

Add imports at the top of `api/app/routes/trade.py`:
```python
from app.services.identity import apply_name_overrides
from app.services.name_override_store import NameOverrideStore
```

trade.py has two handlers. Update **both**:

In `trades()`, add 2 lines after `if entry is None: raise HTTPException(...)`:
```python
    overrides = NameOverrideStore(cache_dir=_cache_dir()).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
```

In `trade()`, add 2 lines after `if entry is None: raise HTTPException(...)`:
```python
    overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
```

Note: `trade()` already has `cache_dir = _cache_dir()` as a local — use that variable, not `_cache_dir()`, to avoid a second call.

- [ ] **Step 3: Update owner.py**

Add imports at the top of `api/app/routes/owner.py`:
```python
from app.services.identity import apply_name_overrides
from app.services.name_override_store import NameOverrideStore
```

In the `owner()` handler, add 2 lines after `if entry is None: raise HTTPException(...)`:
```python
    overrides = NameOverrideStore(cache_dir=_cache_dir()).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
```

- [ ] **Step 4: Update leaderboard.py**

Add imports at the top of `api/app/routes/leaderboard.py`:
```python
from app.services.identity import apply_name_overrides
from app.services.name_override_store import NameOverrideStore
```

In the `leaderboard()` handler, add 2 lines after `if entry is None: raise HTTPException(...)`:
```python
    overrides = NameOverrideStore(cache_dir=_cache_dir()).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
```

- [ ] **Step 5: Run full backend test suite**

```bash
cd api && pytest -v
```

Expected: all existing tests pass (no regressions — overrides are empty in tests, so `if overrides:` is falsy and no mutation occurs)

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/league.py api/app/routes/trade.py api/app/routes/owner.py api/app/routes/leaderboard.py
git commit -m "feat: apply name overrides in all read-entry routes (league, trade, owner, leaderboard)"
```

---

## Task 5: Apply overrides in grader.py (story generation)

**Files:**
- Modify: `api/app/services/grader.py` (around line 217)

- [ ] **Step 1: Locate the owners_display builder**

In `api/app/services/grader.py`, find this block (currently around line 217):
```python
            supporting.setdefault(
                "owners_display",
                {uid: (o.get("owner_name") or uid)
                 for uid, o in supporting["owners"].items()})
```

`current_league_id` and `cache_dir` are both in scope at this point.

- [ ] **Step 2: Replace the block to apply overrides**

```python
            _name_overrides = (
                __import__("app.services.name_override_store",
                           fromlist=["NameOverrideStore"])
                .NameOverrideStore(cache_dir=cache_dir).read(current_league_id)
                if cache_dir else {}
            )
            supporting.setdefault(
                "owners_display",
                {uid: (_name_overrides.get(uid) or o.get("owner_name") or uid)
                 for uid, o in supporting["owners"].items()})
```

> Note: The local `__import__` avoids a top-level import in a file that already uses scattered local imports for optional dependencies. Alternatively, add `from app.services.name_override_store import NameOverrideStore` at the top of the file if you prefer — both work.

The cleaner alternative (add at top of `grader.py` with other imports):
```python
from app.services.name_override_store import NameOverrideStore
```

Then replace just the `supporting.setdefault` block:
```python
            _name_overrides = (
                NameOverrideStore(cache_dir=cache_dir).read(current_league_id)
                if cache_dir else {}
            )
            supporting.setdefault(
                "owners_display",
                {uid: (_name_overrides.get(uid) or o.get("owner_name") or uid)
                 for uid, o in supporting["owners"].items()})
```

Use the second (cleaner) form.

- [ ] **Step 3: Run backend tests**

```bash
cd api && pytest -v
```

Expected: all pass. The existing `test_grader_story_hook.py` test passes `cache_dir=None`, so `_name_overrides` is `{}` and behavior is unchanged.

- [ ] **Step 4: Commit**

```bash
git add api/app/services/grader.py
git commit -m "feat: apply name overrides in grader owners_display so LLM stories use friendly names"
```

---

## Task 6: Frontend types + API functions

**Files:**
- Modify: `web/lib/types.ts`
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add types to web/lib/types.ts**

Append at the end of `web/lib/types.ts`:

```typescript
export interface OwnerNameEntry {
  user_id: string;
  sleeper_name: string;
  display_name: string | null;
}

export interface OwnerNamesResp {
  owners: OwnerNameEntry[];
}
```

- [ ] **Step 2: Add API functions to web/lib/api.ts**

Add the import for new types at the top of `web/lib/api.ts` (extend the existing import):
```typescript
import {
  DashboardResp, LatestTrade, LeaderboardResp, Lens, OwnerDetailResp,
  OwnerNameEntry, OwnerNamesResp, OwnerProfile, ProfilesMap, TradeDetailResp, Year,
} from "./types";
```

Append two new functions at the end of `web/lib/api.ts`:

```typescript
export function getOwnerNames(leagueId: string): Promise<OwnerNamesResp> {
  return jsonFetch<OwnerNamesResp>(`${BASE}/league/${leagueId}/owner-names`);
}

export function putOwnerNames(
  leagueId: string,
  overrides: Record<string, string>,
): Promise<{ ok: boolean }> {
  return jsonFetch<{ ok: boolean }>(`${BASE}/league/${leagueId}/owner-names`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overrides }),
  });
}
```

- [ ] **Step 3: Run frontend type check**

```bash
cd web && npm run build 2>&1 | grep -E "error|Error" | head -20
```

Expected: no TypeScript errors related to the new types

- [ ] **Step 4: Commit**

```bash
git add web/lib/types.ts web/lib/api.ts
git commit -m "feat: add OwnerNamesResp types + getOwnerNames/putOwnerNames API functions"
```

---

## Task 7: OwnerNamesForm component

**Files:**
- Create: `web/components/OwnerNamesForm.tsx`

- [ ] **Step 1: Create the component**

```tsx
// web/components/OwnerNamesForm.tsx
"use client";

import { useState } from "react";
import { OwnerNameEntry } from "@/lib/types";
import { putOwnerNames } from "@/lib/api";

interface Props {
  leagueId: string;
  initial: OwnerNameEntry[];
}

export function OwnerNamesForm({ leagueId, initial }: Props) {
  const [names, setNames] = useState<Record<string, string>>(
    Object.fromEntries(initial.map((o) => [o.user_id, o.display_name ?? ""])),
  );
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  );

  async function save() {
    setStatus("saving");
    try {
      await putOwnerNames(leagueId, names);
      setStatus("saved");
      setTimeout(() => setStatus("idle"), 2000);
    } catch {
      setStatus("error");
    }
  }

  return (
    <div>
      <div className="text-[11px] font-mono uppercase tracking-widest text-dim mb-3">
        Owner Display Names
      </div>
      <div className="flex flex-col gap-2 mb-5">
        {initial.map((o) => (
          <div key={o.user_id} className="flex items-center gap-3">
            <span className="text-dim text-sm w-32 truncate shrink-0">
              {o.sleeper_name}
            </span>
            <input
              type="text"
              className="flex-1 bg-surface border border-divider rounded px-2 py-1 text-sm text-ink focus:outline-none focus:border-ink"
              placeholder={o.sleeper_name}
              value={names[o.user_id] ?? ""}
              onChange={(e) =>
                setNames((prev) => ({ ...prev, [o.user_id]: e.target.value }))
              }
            />
          </div>
        ))}
      </div>
      <button
        onClick={save}
        disabled={status === "saving"}
        className="bg-ink text-bg text-sm font-semibold px-4 py-1.5 rounded disabled:opacity-50 hover:opacity-80 transition-opacity"
      >
        {status === "saving"
          ? "Saving..."
          : status === "saved"
            ? "Saved"
            : "Save names"}
      </button>
      {status === "error" && (
        <p className="text-neg text-sm mt-2">Save failed. Try again.</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run type check**

```bash
cd web && npm run build 2>&1 | grep -E "error|Error" | head -20
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add web/components/OwnerNamesForm.tsx
git commit -m "feat: OwnerNamesForm — client component for editing owner display names"
```

---

## Task 8: Settings page

**Files:**
- Create: `web/app/league/[id]/settings/page.tsx`

- [ ] **Step 1: Create the page**

```tsx
// web/app/league/[id]/settings/page.tsx
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { OwnerNamesForm } from "@/components/OwnerNamesForm";
import { getOwnerNames } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SettingsPage({
  params,
}: {
  params: { id: string };
}) {
  let data;
  try {
    data = await getOwnerNames(params.id);
  } catch {
    data = null;
  }

  return (
    <Shell>
      <TopBar leagueId={params.id} activeNav="settings" />
      <div className="max-w-md">
        <h1 className="text-xl font-bold mb-1">League Settings</h1>
        <p className="text-dim text-sm mb-6">
          Friendly names appear everywhere in the app, including trade stories.
          Leave blank to use the Sleeper handle.
        </p>
        {data ? (
          <OwnerNamesForm leagueId={params.id} initial={data.owners} />
        ) : (
          <p className="text-dim text-sm">
            League not loaded yet. Run a refresh first.
          </p>
        )}
      </div>
    </Shell>
  );
}
```

- [ ] **Step 2: Run type check**

```bash
cd web && npm run build 2>&1 | grep -E "error|Error" | head -20
```

Expected: TypeScript error — `"settings"` is not a valid `NavKey` in TopBar (fix in next task)

- [ ] **Step 3: Commit once TopBar fix is in (do not commit yet — wait for Task 9)**

---

## Task 9: TopBar Settings link

**Files:**
- Modify: `web/components/TopBar.tsx`

- [ ] **Step 1: Update NavKey type and NAV array**

In `web/components/TopBar.tsx`, update the `NavKey` type:
```typescript
type NavKey = "dashboard" | "trades" | "owners" | "gm" | "methodology" | "settings";
```

Add `"settings"` to the `NAV` array (after `"methodology"`):
```typescript
const NAV: { key: NavKey; label: string; tab?: "trades" | "owners" | "gm" }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "gm", label: "GM Ratings", tab: "gm" },
  { key: "trades", label: "Trades", tab: "trades" },
  { key: "owners", label: "Owners", tab: "owners" },
  { key: "methodology", label: "How this works" },
  { key: "settings", label: "Settings" },
];
```

Update `navHref` to handle the `"settings"` key:
```typescript
function navHref(
  n: (typeof NAV)[number],
  leagueId?: string,
  year?: string,
  lens?: string,
): string {
  if (n.key === "methodology") return "/methodology";
  if (n.key === "settings") return leagueId ? `/league/${leagueId}/settings` : "#";
  if (!leagueId) return "#";
  const qs = new URLSearchParams();
  if (year && year !== "all") qs.set("year", year);
  if (lens) qs.set("lens", lens);
  if (n.tab) qs.set("tab", n.tab);
  const s = qs.toString();
  return `/league/${leagueId}${s ? `?${s}` : ""}`;
}
```

Hide "Settings" on mobile by adding the `hidden sm:inline` class in the `<Link>` render. The existing render block already applies `hidden sm:inline` only to `methodology`. Update the className logic:

```tsx
className={`whitespace-nowrap ${
  n.key === "methodology" || n.key === "settings" ? "hidden sm:inline" : ""
} ${
  activeNav === n.key
    ? "text-ink font-semibold"
    : "hover:text-ink transition-colors"
}`}
```

- [ ] **Step 2: Run type check and confirm clean**

```bash
cd web && npm run build 2>&1 | grep -E "error|Error" | head -20
```

Expected: no errors

- [ ] **Step 3: Commit Tasks 8 + 9 together**

```bash
git add web/app/league/[id]/settings/page.tsx web/components/TopBar.tsx
git commit -m "feat: settings page at /league/[id]/settings with TopBar nav link"
```

---

## Task 10: Run full test suite + verify

- [ ] **Step 1: Run backend tests**

```bash
cd api && pytest -v
```

Expected: all pass

- [ ] **Step 2: Run frontend build**

```bash
cd web && npm run build
```

Expected: clean build, no type errors

- [ ] **Step 3: Start dev servers and smoke test**

```bash
make dev-api   # in one terminal
make dev-web   # in another
```

Navigate to `http://localhost:3000/league/<your-league-id>/settings`.

Verify:
- Page loads with a list of owners (Sleeper handles in left column, inputs on right)
- Type a friendly name and click Save
- Navigate to the main dashboard — owner names should reflect the override
- Navigate to a trade detail — owner names in the story header and side panels should reflect the override

- [ ] **Step 4: Final commit (if any last fixes)**

```bash
cd .. && git add -A && git commit -m "fix: post-smoke-test adjustments"
```
