# Owner Name + Team Name Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the owner's name (Sleeper handle) as the primary label everywhere a team identity appears, with the team name as a smaller secondary line and an avatar, via one shared `OwnerRef` shape and one reusable `<OwnerLabel>` component.

**Architecture:** The engine's `get_users` gains an `avatar_url`. The API stops collapsing identity into a single string: `grader_io` builds a per-owner map (`owner_name`/`team_name`/`avatar_url`) that flows through the chain cache, the Pydantic models (`OwnerRef`), the TS types, and a single `<OwnerLabel variant="full"|"compact">` React component. Legacy chain-cache files (missing the new `owners` key) read as a cache-miss → cold-start refresh re-pulls them; the raw-fetch cache bumps its `SCHEMA_VERSION` so sealed-league bundles re-pull too.

**Tech Stack:** Python 3 / pytest / FastAPI / Pydantic v2 (engine + API); Next.js 14 / TypeScript / Tailwind / vitest + React Testing Library (web).

**Spec:** `docs/superpowers/specs/2026-05-31-owner-name-display-design.md`

---

## File Structure

**Engine**
- Modify: `src/sleeper_dynasty/api/sleeper.py` — add `_resolve_avatar_url`; `get_users` returns `avatar_url`.
- Modify: `tests/fixtures/users.json`, `tests/test_sleeper_api.py`.

**API — backend identity refactor**
- Create: `api/app/models/common.py` — `OwnerRef`.
- Create: `api/app/services/identity.py` — `owner_ref()`, `owner_name()` helpers.
- Modify: `api/app/models/league.py`, `api/app/models/owner.py`, `api/app/models/trade.py`.
- Modify: `api/app/services/chain_cache.py` — field rename + legacy guard.
- Modify: `api/app/services/grader.py` — pass `owners=`.
- Modify: `api/app/services/grader_io.py` — build `owners` map; bundle key.
- Modify: `api/app/services/league_raw_cache.py` — bump `SCHEMA_VERSION`.
- Modify: `api/app/services/aggregations.py`, `api/app/services/owner_view.py`, `api/app/services/trade_view.py`.
- Modify backend tests: `test_chain_cache.py`, `test_aggregations.py`, `test_refresh.py`, `test_models.py`, `test_grader_io.py`, `test_grader_service.py`, `test_trade.py`, `test_owner.py`, `test_league.py`, `test_league_raw_cache.py`.

**Web**
- Create: `web/components/OwnerLabel.tsx`; `web/tests/OwnerLabel.test.tsx`.
- Modify: `web/lib/types.ts`, `web/lib/standings-filter.ts`.
- Modify: `web/components/StandingsTable.tsx`, `web/components/OwnersTab.tsx`, `web/components/TradeSidePanel.tsx`, `web/components/TradeCard.tsx`.
- Modify: `web/app/league/[id]/owner/[uid]/page.tsx`, `web/app/league/[id]/trade/[tid]/page.tsx`.
- Modify: `web/tests/standings-filter.test.ts`.

---

## Task 1: Engine — `get_users` returns `avatar_url`

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py:132-146`
- Modify: `tests/fixtures/users.json`
- Test: `tests/test_sleeper_api.py:84-90`

- [ ] **Step 1: Extend the fixture with avatar variants**

Replace the entire contents of `tests/fixtures/users.json` with:

```json
[
  {"user_id": "user_aaa", "display_name": "Alice", "avatar": "acct_aaa", "metadata": {"team_name": "Alice's Aces", "avatar": "https://sleepercdn.com/uploads/team_aaa.png"}},
  {"user_id": "user_bbb", "display_name": "Bob", "avatar": "acct_bbb", "metadata": {"team_name": "Bob's Bombers"}},
  {"user_id": "user_ccc", "display_name": "Carol", "metadata": {}}
]
```

(`user_aaa` = custom team avatar URL; `user_bbb` = account avatar id only; `user_ccc` = no avatar, no team name.)

- [ ] **Step 2: Update the `get_users` test (write the failing assertions)**

In `tests/test_sleeper_api.py`, replace the body of `TestGetUsers.test_returns_user_map` (lines 84-90) with:

```python
        assert len(users) == 3
        # Custom team avatar (a full URL) wins.
        assert users["user_aaa"]["display_name"] == "Alice"
        assert users["user_aaa"]["team_name"] == "Alice's Aces"
        assert users["user_aaa"]["avatar_url"] == "https://sleepercdn.com/uploads/team_aaa.png"
        # Falls back to the account avatar id → thumbs URL.
        assert users["user_bbb"]["avatar_url"] == "https://sleepercdn.com/avatars/thumbs/acct_bbb"
        # No avatar anywhere → None; no team name → None.
        assert users["user_ccc"]["avatar_url"] is None
        assert users["user_ccc"]["team_name"] is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_sleeper_api.py::TestGetUsers -v`
Expected: FAIL — `KeyError: 'avatar_url'` (and len assertion).

- [ ] **Step 4: Implement avatar resolution**

In `src/sleeper_dynasty/api/sleeper.py`, add near the top after `BASE_URL = ...` (line 11):

```python
AVATAR_THUMB_BASE = "https://sleepercdn.com/avatars/thumbs"


def _resolve_avatar_url(u: dict) -> str | None:
    """Prefer a custom team avatar (a full URL in metadata.avatar), else the
    account avatar id rendered to a thumbnail URL, else None."""
    team_avatar = (u.get("metadata") or {}).get("avatar")
    if team_avatar:
        return team_avatar
    account_avatar = u.get("avatar")
    if account_avatar:
        return f"{AVATAR_THUMB_BASE}/{account_avatar}"
    return None
```

Then in `get_users` (lines 141-145), add the `avatar_url` key:

```python
        for u in resp.json():
            users[u["user_id"]] = {
                "display_name": u.get("display_name") or "Unknown",
                "team_name": (u.get("metadata") or {}).get("team_name"),
                "avatar_url": _resolve_avatar_url(u),
            }
```

Also widen the return annotation on line 132 from `dict[str, dict[str, str | None]]` to `dict[str, dict[str, str | None]]` (unchanged — `avatar_url` is still `str | None`).

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_sleeper_api.py -v`
Expected: PASS (including the unchanged `TestGetRosters`).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py tests/fixtures/users.json tests/test_sleeper_api.py
git commit -m "feat(engine): resolve owner/team avatar_url in get_users"
```

---

## Task 2: Backend identity refactor (atomic)

This is one cohesive refactor: the chain-cache field rename, the new model shape, and the service updates must land together to keep the backend suite green. Intermediate steps leave the suite red; the final step runs the full backend suite green.

**Files:** see File Structure (API section).

- [ ] **Step 1: Add the `OwnerRef` model**

Create `api/app/models/common.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class OwnerRef(BaseModel):
    """Owner identity for display: handle (always present), optional team name,
    optional avatar URL."""

    user_id: str
    owner_name: str
    team_name: str | None = None
    avatar_url: str | None = None
```

- [ ] **Step 2: Update the league models**

In `api/app/models/league.py`:
- Add to the imports block (after `from pydantic import BaseModel, Field`):

```python
from app.models.common import OwnerRef
```

- In `StandingRow` (lines 41-49), replace `display_name: str` with `owner: OwnerRef`.
- In `LatestTrade` (lines 52-59), replace `parties: list[str]` with `parties: list[OwnerRef]`.

(Leave `HeroStat.owner: str | None` and `Records.*_owner: str | None` unchanged.)

- [ ] **Step 3: Update the owner + trade models**

In `api/app/models/owner.py`, add `from app.models.common import OwnerRef`, then in `OwnerDetailResp` (lines 13-20) replace `display_name: str` with `owner: OwnerRef`.

In `api/app/models/trade.py`, in `TradeSideView` (lines 8-15) replace `display_name: str` with:

```python
    owner_name: str
    team_name: str | None = None
    avatar_url: str | None = None
```

- [ ] **Step 4: Add the identity helpers**

Create `api/app/services/identity.py`:

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
```

- [ ] **Step 5: Rename the chain-cache field + add the legacy guard**

In `api/app/services/chain_cache.py`:
- In `ChainCacheEntry` (line 24) replace `display_names: dict[str, str]` with `owners: dict[str, dict[str, Any]]`.
- In `read()`, immediately after `raw = json.load(f)` (line 53), add:

```python
        # Pre-migration entries lack `owners`; treat as a miss so the
        # cold-start flow re-pulls and re-grades them.
        if "owners" not in raw:
            return None
```

- [ ] **Step 6: Pass `owners=` from the grader**

In `api/app/services/grader.py:127`, replace `display_names=supporting["display_names"],` with `owners=supporting["owners"],`.

- [ ] **Step 7: Build the `owners` map in grader_io + bump raw schema**

In `api/app/services/grader_io.py`:
- In `_league_matchup_bundle` (lines 69-72), replace the `display_names = {...}` comprehension with:

```python
    owners = {
        uid: {
            "owner_name": info.get("display_name") or uid,
            "team_name": info.get("team_name"),
            "avatar_url": info.get("avatar_url"),
        }
        for uid, info in users.items()
    }
```

- In the same function's `bundle` dict (line 86), replace `"display_names": display_names,` with `"owners": owners,`.
- In `pull_supporting_data`: rename the local on line 156 from `display_names: dict[str, str] = {}` to `owners: dict[str, dict[str, Any]] = {}`; replace the merge loop (lines 164-165):

```python
        for uid, ident in b["owners"].items():
            owners.setdefault(uid, ident)
```

- In the returned dict (line 176), replace `"display_names": display_names,` with `"owners": owners,`.

In `api/app/services/league_raw_cache.py:21`, bump `SCHEMA_VERSION = 1` to `SCHEMA_VERSION = 2` (invalidates old sealed-league bundles that still carry `display_names`).

- [ ] **Step 8: Update the aggregations service**

In `api/app/services/aggregations.py`:
- Add to imports: `from app.services.identity import owner_name, owner_ref`. Add `OwnerRef` is not needed here directly.
- In `_aggregate_owner_rows`, change the seeding loop (lines 57-63) to iterate ids and drop the stored name:

```python
    for uid in entry.owners:
        rows[uid] = {
            "user_id": uid,
            "net_ktc": 0.0, "net_production": 0.0,
            "trades": 0, "decisive_starts_gained": 0, "playoff_starts_gained": 0,
            "starter_weeks_received": 0, "starter_weeks_given_phantom": 0,
        }
```

and the `setdefault` inside the trades loop (lines 67-72):

```python
            row = rows.setdefault(uid, {
                "user_id": uid,
                "net_ktc": 0.0, "net_production": 0.0,
                "trades": 0, "decisive_starts_gained": 0, "playoff_starts_gained": 0,
                "starter_weeks_received": 0, "starter_weeks_given_phantom": 0,
            })
```

- In `_hero_stats`: line 132 `entry.display_names.get(other_uids[0], "?")` → `owner_name(entry, other_uids[0])`; line 136 `entry.display_names.get(uid, uid)` → `owner_name(entry, uid)`; line 150 `entry.display_names.get(top_uid, top_uid)` → `owner_name(entry, top_uid)`.
- In `_latest_trades`: replace the `parties = [...]` block (lines 184-186) with:

```python
        parties = [
            owner_ref(entry, uid) for uid in (rt["sides"] or {}).keys()
        ][:3]
```

- In `_records` (lines 218-225): replace each `*_owner=top_*["display_name"]` with `owner_name(entry, top_*["user_id"])`, e.g. `biggest_value_swing_owner=owner_name(entry, top_v["user_id"]),` and likewise for `top_p`, `top_d`, `top_t`.
- In `build_dashboard`, the `StandingRow(...)` construction (lines 241-248): replace `display_name=r["display_name"],` with `owner=owner_ref(entry, r["user_id"]),`.

- [ ] **Step 9: Update the owner + trade views**

In `api/app/services/owner_view.py`:
- Add `from app.services.identity import owner_ref`.
- Line 10 guard: `if user_id not in entry.display_names:` → `if user_id not in entry.owners:`.
- Line 53: `display_name=entry.display_names[user_id],` → `owner=owner_ref(entry, user_id),`.

In `api/app/services/trade_view.py`:
- Add `from app.services.identity import owner_ref`.
- In the `TradeSideView(...)` construction (lines 21-23), replace `display_name=entry.display_names.get(uid, uid),` with:

```python
            owner_name=owner_ref(entry, uid).owner_name,
            team_name=owner_ref(entry, uid).team_name,
            avatar_url=owner_ref(entry, uid).avatar_url,
```

- [ ] **Step 10: Update backend test fixtures + assertions**

In every file below, replace the `display_names={...}` keyword in `ChainCacheEntry(...)` / supporting-dict / bundle constructions with the `owners=` form, mapping each `uid: "Name"` to `uid: {"owner_name": "Name", "team_name": None, "avatar_url": None}`. Then fix the listed assertions.

`api/tests/test_chain_cache.py`:
- Lines 19, 37, 54: `display_names={"u1": "Tom"}` → `owners={"u1": {"owner_name": "Tom", "team_name": None, "avatar_url": None}}`; the two empty ones `display_names={}` → `owners={}`.
- Line 31 assertion → `assert got.owners["u1"]["owner_name"] == "Tom"`.
- Add a new test:

```python
def test_chain_cache_legacy_entry_without_owners_is_a_miss(cache, tmp_path):
    import json
    path = tmp_path / "chain_Llegacy.json"
    path.write_text(json.dumps({
        "league_id": "Llegacy", "chain": [], "resolved_trades": [], "grades": {},
        "display_names": {"u1": "Tom"}, "playoff_weeks_by_league": {},
        "roster_to_user_by_league": {}, "league_name_by_id": {},
        "league_season_by_id": {}, "cached_at": "2026-05-28T12:00:00Z", "warnings": [],
    }))
    assert cache.read("Llegacy") is None
```

`api/tests/test_aggregations.py`:
- Line 77 → `owners={"u_alice": {"owner_name": "Alice", "team_name": None, "avatar_url": None}, "u_bob": {"owner_name": "Bob", "team_name": None, "avatar_url": None}},`.
- Line 94 assertion → `assert resp.standings[0].owner.owner_name == "Alice"`.

`api/tests/test_refresh.py`:
- Line 13 `display_names={}` → `owners={}`.

`api/tests/test_models.py`:
- Add import: `from app.models.common import OwnerRef`.
- Lines 49-51 `StandingRow(... display_name="Tom" ...)` → replace `display_name="Tom",` with `owner=OwnerRef(user_id="u1", owner_name="Tom", team_name="Tom's Team", avatar_url=None),`.
- Lines 54-57 `LatestTrade(... parties=["Tom", "Mike"] ...)` → `parties=[OwnerRef(user_id="u1", owner_name="Tom"), OwnerRef(user_id="u2", owner_name="Mike")],`.
- Line 77 (OwnerDetailResp) `display_name="Tom",` → `owner=OwnerRef(user_id="u1", owner_name="Tom"),`.
- Line 103 (TradeSideView) `display_name="Tom",` → `owner_name="Tom",`.

`api/tests/test_grader_io.py`:
- Line 69 `"display_names": {"u_a": "Alice"},` → `"owners": {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}},`.
- Line 92 assertion → `assert out["owners"]["u_a"]["owner_name"] == "Alice"`.

`api/tests/test_grader_service.py`:
- Line 42 `"display_names": {"u_a": "Alice"},` → `"owners": {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}},`.
- Line 55 assertion → `assert entry.owners == {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}}`.
- Line 79 `"display_names": {}, "warnings": ["empty chain"],` → `"owners": {}, "warnings": ["empty chain"],`.
- (Lines 120-121 and 233-234 `get_users` fakes return `{"u_a": {"display_name": "Alice"}, ...}`. Leave unchanged — `grader_io` reads them with `.get()`.)

`api/tests/test_trade.py`:
- Line 50 → `owners={"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}, "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None}},`.

`api/tests/test_owner.py`:
- Line 44 → same `owners={...}` form as test_trade.
- Line 61 assertion → `assert body["owner"]["owner_name"] == "Alice"`.

`api/tests/test_league.py`:
- Line 18 → same `owners={...}` form (`u_alice`/`u_bob`).

`api/tests/test_league_raw_cache.py`:
- Line 30 (in `_matchup_bundle`) `"display_names": {"u_a": "Alice", "u_b": "Bob"},` → `"owners": {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}, "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None}},`.

`api/tests/test_grader_io.py` sealed-cache test:
- Line 69 already handled above; also update its assertion at line 92 already handled.

- [ ] **Step 11: Run the full backend suite**

Run: `pytest api/tests -q`
Expected: PASS (all). If a `display_names` reference remains, fix it where flagged.

- [ ] **Step 12: Run the engine suite (no regressions)**

Run: `pytest tests -q`
Expected: PASS — engine consumers of `get_users` (trade_history, grader) are untouched.

- [ ] **Step 13: Commit**

```bash
git add api/app src/sleeper_dynasty api/tests
git commit -m "refactor(api): carry owner_name/team_name/avatar via OwnerRef instead of collapsed display_name"
```

---

## Task 3: Web — `OwnerRef` type + `<OwnerLabel>` component (additive)

**Files:**
- Modify: `web/lib/types.ts`
- Create: `web/components/OwnerLabel.tsx`
- Test: `web/tests/OwnerLabel.test.tsx`

- [ ] **Step 1: Add the `OwnerRef` type (additive only)**

In `web/lib/types.ts`, add after line 2 (`export type Year = ...`):

```ts
export interface OwnerRef {
  user_id: string;
  owner_name: string;
  team_name?: string;
  avatar_url?: string;
}
```

- [ ] **Step 2: Write the failing OwnerLabel test**

Create `web/tests/OwnerLabel.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OwnerLabel } from "../components/OwnerLabel";

describe("OwnerLabel", () => {
  it("full variant shows owner name and team name when present", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "mike_t", team_name: "Dynasty Warriors" }} />);
    expect(screen.getByText("mike_t")).toBeInTheDocument();
    expect(screen.getByText("Dynasty Warriors")).toBeInTheDocument();
  });

  it("full variant omits the team line when team_name is absent", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "mike_t" }} />);
    expect(screen.getByText("mike_t")).toBeInTheDocument();
    expect(screen.queryByText("Dynasty Warriors")).not.toBeInTheDocument();
  });

  it("renders an initial monogram when there is no avatar_url", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "carol" }} />);
    expect(screen.getByText("C")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders the avatar image when avatar_url is set", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "alice", avatar_url: "https://x/y.png" }} />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "https://x/y.png");
  });

  it("compact variant never shows the team line", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "mike_t", team_name: "Dynasty Warriors" }} variant="compact" />);
    expect(screen.getByText("mike_t")).toBeInTheDocument();
    expect(screen.queryByText("Dynasty Warriors")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd web && npx vitest run tests/OwnerLabel.test.tsx`
Expected: FAIL — cannot resolve `../components/OwnerLabel`.

- [ ] **Step 4: Implement the component**

Create `web/components/OwnerLabel.tsx`:

```tsx
import { OwnerRef } from "@/lib/types";

interface Props {
  owner: OwnerRef;
  variant?: "full" | "compact";
}

export function OwnerLabel({ owner, variant = "full" }: Props) {
  const initial = (owner.owner_name || "?").charAt(0).toUpperCase();
  const avatarSize = variant === "compact" ? "h-5 w-5 text-[9px]" : "h-8 w-8 text-[12px]";
  return (
    <span className={variant === "compact" ? "inline-flex items-center gap-1.5 min-w-0" : "flex items-center gap-2.5 min-w-0"}>
      {owner.avatar_url ? (
        <img
          src={owner.avatar_url}
          alt=""
          className={`${avatarSize} rounded-full object-cover bg-surface shrink-0`}
        />
      ) : (
        <span
          className={`${avatarSize} rounded-full bg-surface border border-divider text-dim grid place-items-center font-semibold shrink-0`}
        >
          {initial}
        </span>
      )}
      <span className="min-w-0">
        <span className="block font-sans font-medium text-ink leading-tight truncate">
          {owner.owner_name}
        </span>
        {variant === "full" && owner.team_name && (
          <span className="block font-mono text-[10px] text-dim leading-tight truncate">
            {owner.team_name}
          </span>
        )}
      </span>
    </span>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd web && npx vitest run tests/OwnerLabel.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add web/lib/types.ts web/components/OwnerLabel.tsx web/tests/OwnerLabel.test.tsx
git commit -m "feat(web): add OwnerRef type and reusable OwnerLabel component"
```

---

## Task 4: Web — wire `OwnerRef` through types, sites, and the filter (atomic)

Flip the data model (remove `display_name`, add `owner`) and update every consumer in one task so the suite stays green.

**Files:** see File Structure (web section).

- [ ] **Step 1: Flip the TS types**

In `web/lib/types.ts`:
- `StandingRow` (line 39): replace `display_name: string;` with `owner: OwnerRef;`.
- `OwnerDetailResp` (line 89): replace `display_name: string;` with `owner: OwnerRef;`.
- `TradeSideView` (line 98): replace `display_name: string;` with:

```ts
  owner_name: string;
  team_name?: string;
  avatar_url?: string;
```

- `LatestTrade` (line 51): replace `parties: string[];` with `parties: OwnerRef[];`.

- [ ] **Step 2: Update the standings filter to key off `owner.owner_name`**

In `web/lib/standings-filter.ts`:
- Add a value accessor above `applyStandingsState` (after line 17):

```ts
function cellValue(r: StandingRow, col: string): unknown {
  if (col === "owner_name") return r.owner.owner_name;
  return (r as Record<string, unknown>)[col];
}
```

- In the name-filter branch (lines 30-37), change the column key and the read:

```ts
      } else if (col === "owner_name") {
        const term = sv[0];
        const chars = term.split("");
        out = out.filter((r) => {
          const lower = r.owner.owner_name.toLowerCase();
          return chars.every((ch) => lower.includes(ch));
        });
      }
```

- In the sort comparator (lines 52-53), use the accessor:

```ts
    const av = cellValue(a, state.sort.column);
    const bv = cellValue(b, state.sort.column);
```

- [ ] **Step 3: Update the standings-filter test**

In `web/tests/standings-filter.test.ts`:
- Replace each row in `ROWS` (lines 6-9) `display_name: "X"` with `owner: { user_id: "uN", owner_name: "X" }` (keep the existing `user_id` field too). Example for line 6:

```ts
  { rank: 1, user_id: "u1", owner: { user_id: "u1", owner_name: "Tom" },  net_ktc: 2755, net_production: 406.8, trades: 5, ps_plus: 2,  grade: "A" },
```

Apply the same shape to Mike (u2), Jim (u3), Sarah (u4).
- Replace every `r.display_name` / `out[i].display_name` read with `r.owner.owner_name` / `out[i].owner.owner_name` (lines 17-18, 26, 34, 42).
- Replace the filter key `display_name: ["mi"]` (line 24) with `owner_name: ["mi"]`.

- [ ] **Step 4: Update StandingsTable**

In `web/components/StandingsTable.tsx`:
- Add import: `import { OwnerLabel } from "./OwnerLabel";`.
- Change the COLS type (line 17) to `key: keyof StandingRow | "owner_name" | "owner_search";`.
- Change the owner column (line 23) to `{ key: "owner_name", plain: "Owner", jargon: "league member" },`.
- Replace the owner cell (lines 121-123):

```tsx
            <div className="min-w-0">
              <OwnerLabel owner={r.owner} variant="full" />
            </div>
```

- [ ] **Step 5: Update OwnersTab**

In `web/components/OwnersTab.tsx`:
- Add import: `import { OwnerLabel } from "./OwnerLabel";`.
- Replace the name span (lines 48-50) with:

```tsx
                <OwnerLabel owner={o.owner} variant="full" />
```

(Keep the surrounding `#rank` span and grade pill.)

- [ ] **Step 6: Update the owner detail page header**

In `web/app/league/[id]/owner/[uid]/page.tsx`:
- Add import: `import { OwnerLabel } from "@/components/OwnerLabel";`.
- Replace the `<h1>` (lines 41-43) with:

```tsx
        <div className="mt-2 text-2xl font-extrabold tracking-tight">
          <OwnerLabel owner={data.owner} variant="full" />
        </div>
```

- [ ] **Step 7: Update the trade detail page (header + displayNames map)**

In `web/app/league/[id]/trade/[tid]/page.tsx`:
- Replace the `displayNames` map (lines 30-32) with:

```tsx
  const displayNames: Record<string, string> = Object.fromEntries(
    data.sides.map((s) => [s.user_id, s.owner_name]),
  );
```

- Replace the header join (line 47) with `{data.sides.map((s) => s.owner_name).join(" ↔ ")}`.

- [ ] **Step 8: Update TradeSidePanel**

In `web/components/TradeSidePanel.tsx`:
- Add import: `import { OwnerLabel } from "./OwnerLabel";`.
- Replace the side name block (lines 15-17) with:

```tsx
      <div className="mt-1">
        <OwnerLabel
          owner={{ user_id: side.user_id, owner_name: side.owner_name, team_name: side.team_name, avatar_url: side.avatar_url }}
          variant="full"
        />
      </div>
```

- [ ] **Step 9: Update TradeCard parties (compact, with avatars)**

In `web/components/TradeCard.tsx`:
- Add import: `import { OwnerLabel } from "./OwnerLabel";` and `import { Fragment } from "react";`.
- Replace the parties line (lines 19-21) with:

```tsx
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] font-semibold mb-1">
        {trade.parties.map((p, i) => (
          <Fragment key={p.user_id}>
            {i > 0 && <span className="text-dim font-normal">↔</span>}
            <OwnerLabel owner={p} variant="compact" />
          </Fragment>
        ))}
      </div>
```

- [ ] **Step 10: Run the web unit tests**

Run: `cd web && npx vitest run`
Expected: PASS — `standings-filter.test.ts`, `OwnerLabel.test.tsx`, and the rest.

- [ ] **Step 11: Typecheck the web app**

Run: `cd web && npx tsc --noEmit`
Expected: no errors. (`RecordsPanel.tsx`, `HeroStatsRow.tsx`, `AssetRender.tsx` are untouched and still compile — they consume string owner fields that are unchanged.)

- [ ] **Step 12: Commit**

```bash
git add web/lib web/components web/app web/tests
git commit -m "feat(web): render owner + team + avatar via OwnerLabel across all sites"
```

---

## Task 5: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Run the entire backend + engine suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 2: Run the entire web suite + typecheck**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Run `make dev-api` and `make dev-web`, open a league, click **Refresh** to repopulate the cache (legacy entries are treated as cold), and confirm: standings rows, owners grid, owner page, trade cards, and trade detail show the owner handle as the primary label with the team name beneath (or absent when unset) and an avatar/monogram.

- [ ] **Step 4: Final commit (only if Step 3 surfaced fixes)**

```bash
git add -A
git commit -m "fix(web): owner/team display polish from smoke test"
```

---

## Self-Review Notes

- **Spec coverage:** engine avatar (Task 1) ✓; cache rename + legacy-miss guard + raw schema bump (Task 2) ✓; `OwnerRef` + model changes (Task 2) ✓; service helpers + compact-spot handle strings (Task 2) ✓; `OwnerLabel` + full/compact variants + monogram fallback (Tasks 3-4) ✓; all render sites + standings filter (Task 4) ✓; tests at each layer ✓.
- **Type consistency:** `owners` map shape `{owner_name, team_name, avatar_url}` is identical in engine (`grader_io`), cache, helpers, and test fixtures. `OwnerRef` fields match between `api/app/models/common.py` and `web/lib/types.ts`. `TradeSideView` uses `owner_name` (not `display_name`) in model, service, type, and the trade page/panel.
- **Out of scope (unchanged):** CLI `Roster.owner_name` / `get_rosters`; `RecordsPanel`, `HeroStatsRow`, `AssetRender` markup; pick-origin owners absent from a trade's sides.
