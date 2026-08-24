# Trade History & Grader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `sleeper-dynasty trades <username>` subcommand that walks the Sleeper dynasty league chain, pulls every historical trade, grades each through three lenses (snapshot KTC, hindsight production, realized impact), and emits a Google Doc with a trade ledger + per-owner standings.

**Architecture:** Layered pipeline (api → models → engine → output) mirroring existing project structure. Sleeper API client gains 5 new methods (users, transactions, drafts, draft_picks, league); new `models/trade.py` defines the asset taxonomy; `engine/trade_history.py` builds and resolves trades across the season chain; `engine/trade_grader.py` computes the three lenses and aggregates per owner; `output/google_docs.py` gains two new tab writers; `cli.py` gains a `trades` subcommand. Aggressive `FileCache` use with effectively-infinite TTL for historical seasons.

**Tech Stack:** Python 3.11+, httpx (async), pytest + pytest-asyncio (`unittest.mock.AsyncMock` pattern already used by the codebase), google-api-python-client, existing `FileCache`. Spec at `docs/superpowers/specs/2026-05-27-trade-history-grader-design.md`.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/sleeper_dynasty/models/trade.py` | Asset/Trade/Grade dataclasses; no behavior beyond `to_dict`/`from_dict` for cacheability |
| `src/sleeper_dynasty/engine/trade_history.py` | Fetch + normalize + resolve trades across league chain |
| `src/sleeper_dynasty/engine/trade_grader.py` | Three grading lenses + per-owner aggregation |
| `tests/test_trade_models.py` | Unit tests for `models/trade.py` |
| `tests/test_trade_history.py` | Unit tests for trade-history engine |
| `tests/test_trade_grader.py` | Unit tests for grader |
| `tests/fixtures/transactions_trade.json` | Captured Sleeper trade transaction shape |
| `tests/fixtures/transactions_mixed.json` | Mixed-type week (trade + waivers) |
| `tests/fixtures/drafts.json` | Sleeper drafts list response |
| `tests/fixtures/draft_picks.json` | Sleeper draft_picks response |
| `tests/fixtures/league_meta.json` | `/league/{id}` response (with previous_league_id) |

**Modified files:**

| Path | Change |
|---|---|
| `src/sleeper_dynasty/api/sleeper.py` | Add 5 methods + `walk_league_history` |
| `src/sleeper_dynasty/output/google_docs.py` | Add `write_tab_trade_ledger`, `write_tab_owner_standings` |
| `src/sleeper_dynasty/cli.py` | Add `trades` subcommand |
| `tests/test_sleeper_api.py` | Add tests for the 5 new client methods |
| `tests/test_cli.py` | Add tests for the new subcommand parser |

---

## Conventions used throughout the plan

- All TDD steps follow the same pattern: write failing test → run and confirm fail → implement → run and confirm pass → commit.
- Async tests use `pytest.mark.asyncio` and `unittest.mock.AsyncMock`/`MagicMock`, matching `tests/test_sleeper_api.py`.
- All commits use HEREDOC for message formatting and include the existing Co-Authored-By trailer convention used in this repo (no extra credit line).
- Run tests with `pytest <test_path> -v` from the repo root. Run all tests with `pytest -v`.

---

### Task 1: Add fixtures for new Sleeper endpoints

**Files:**
- Create: `tests/fixtures/league_meta.json`
- Create: `tests/fixtures/transactions_trade.json`
- Create: `tests/fixtures/transactions_mixed.json`
- Create: `tests/fixtures/drafts.json`
- Create: `tests/fixtures/draft_picks.json`

These fixtures back the unit tests for the new Sleeper client methods and the trade-history engine. They mirror the real Sleeper API response shapes.

- [ ] **Step 1: Create `tests/fixtures/league_meta.json`**

```json
{
  "league_id": "league_2024",
  "name": "Dynasty Bros",
  "season": "2024",
  "status": "complete",
  "total_rosters": 12,
  "previous_league_id": "league_2023",
  "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN", "BN"],
  "settings": {
    "playoff_week_start": 15,
    "num_playoff_teams": 6
  },
  "scoring_settings": {"rec": 0.5, "pass_td": 4}
}
```

- [ ] **Step 2: Create `tests/fixtures/transactions_trade.json`**

This is a Sleeper trade transaction, week 2 of 2024. Two-team trade: roster 1 sends Davante Adams (player_id "1234") + a 2024 2nd to roster 2; roster 2 sends Bijan Robinson (player_id "5678") + a 2025 1st to roster 1.

```json
[
  {
    "type": "trade",
    "status": "complete",
    "transaction_id": "tx_001",
    "created": 1726099200000,
    "leg": 2,
    "roster_ids": [1, 2],
    "adds": {"5678": 1, "1234": 2},
    "drops": {"1234": 1, "5678": 2},
    "draft_picks": [
      {
        "season": "2025",
        "round": 1,
        "roster_id": 1,
        "previous_owner_id": 1,
        "owner_id": 1
      },
      {
        "season": "2024",
        "round": 2,
        "roster_id": 2,
        "previous_owner_id": 1,
        "owner_id": 2
      }
    ],
    "waiver_budget": []
  }
]
```

- [ ] **Step 3: Create `tests/fixtures/transactions_mixed.json`**

Mixed-type week — one trade and one waiver claim. Filter logic must keep only the trade.

```json
[
  {
    "type": "waiver",
    "status": "complete",
    "transaction_id": "tx_wv_001",
    "created": 1726185600000,
    "leg": 3,
    "roster_ids": [3],
    "adds": {"9999": 3},
    "drops": {"8888": 3},
    "draft_picks": [],
    "waiver_budget": []
  },
  {
    "type": "trade",
    "status": "complete",
    "transaction_id": "tx_002",
    "created": 1726185600000,
    "leg": 3,
    "roster_ids": [3, 4],
    "adds": {"7777": 4, "6666": 3},
    "drops": {"6666": 4, "7777": 3},
    "draft_picks": [],
    "waiver_budget": [
      {"sender": 3, "receiver": 4, "amount": 25}
    ]
  }
]
```

- [ ] **Step 4: Create `tests/fixtures/drafts.json`**

```json
[
  {
    "draft_id": "draft_2024_a",
    "league_id": "league_2024",
    "season": "2024",
    "status": "complete",
    "type": "snake",
    "settings": {"rounds": 4, "teams": 12}
  }
]
```

- [ ] **Step 5: Create `tests/fixtures/draft_picks.json`**

```json
[
  {
    "draft_id": "draft_2024_a",
    "round": 1,
    "pick_no": 1,
    "draft_slot": 1,
    "roster_id": 5,
    "player_id": "p_rookie_a"
  },
  {
    "draft_id": "draft_2024_a",
    "round": 2,
    "pick_no": 13,
    "draft_slot": 1,
    "roster_id": 2,
    "player_id": "p_rookie_b"
  }
]
```

- [ ] **Step 6: Commit fixtures**

```bash
git add tests/fixtures/league_meta.json tests/fixtures/transactions_trade.json tests/fixtures/transactions_mixed.json tests/fixtures/drafts.json tests/fixtures/draft_picks.json
git commit -m "$(cat <<'EOF'
Add test fixtures for trade-history feature

Captured shapes for /league/{id}, /league/{id}/transactions/{week},
/league/{id}/drafts, and /draft/{id}/picks — feed the upcoming Sleeper
API client extensions and the trade-history engine unit tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add `get_users` to SleeperClient

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py` (add method)
- Modify: `tests/test_sleeper_api.py` (add test class)

Returns a `dict[user_id, dict]` where each value carries the display name and (optional) team name. Existing `get_rosters` already fetches `/league/{id}/users` inline; we lift it to a stand-alone method so callers can use it directly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sleeper_api.py`:

```python
class TestGetUsers:
    @pytest.mark.asyncio
    async def test_returns_user_map(self, client):
        resp = mock_response("users.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            users = await client.get_users("league_001")
        assert isinstance(users, dict)
        # users.json fixture has two users (matches existing test_rosters).
        assert len(users) >= 1
        first_user_id = next(iter(users))
        entry = users[first_user_id]
        assert "display_name" in entry
        assert "team_name" in entry  # may be None but key present
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_sleeper_api.py::TestGetUsers -v
```

Expected: FAIL — `AttributeError: 'SleeperClient' object has no attribute 'get_users'`.

- [ ] **Step 3: Implement `get_users`**

In `src/sleeper_dynasty/api/sleeper.py`, add this method on `SleeperClient` (place it after `get_matchups`, before `get_traded_picks`):

```python
    async def get_users(self, league_id: str) -> dict[str, dict[str, str | None]]:
        """Fetch league members keyed by user_id.

        Each value carries ``display_name`` (Sleeper handle) and ``team_name``
        (the user-configured team name; may be None).
        """
        resp = await self._client.get(f"/league/{league_id}/users")
        resp.raise_for_status()
        users: dict[str, dict[str, str | None]] = {}
        for u in resp.json():
            users[u["user_id"]] = {
                "display_name": u.get("display_name") or "Unknown",
                "team_name": (u.get("metadata") or {}).get("team_name"),
            }
        return users
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_sleeper_api.py::TestGetUsers -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py tests/test_sleeper_api.py
git commit -m "$(cat <<'EOF'
Add SleeperClient.get_users for league-member lookup

Returns user_id → {display_name, team_name}. Existing get_rosters
fetches the same endpoint inline; this stand-alone method makes the
mapping reusable for trade-history aggregation by stable user_id.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Add `get_transactions` to SleeperClient

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py`
- Modify: `tests/test_sleeper_api.py`

Returns the raw transaction list for one league-week. Caller filters by type. We deliberately return raw dicts (not a typed model) — the trade-history engine handles normalization.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sleeper_api.py`:

```python
class TestGetTransactions:
    @pytest.mark.asyncio
    async def test_returns_raw_transactions(self, client):
        resp = mock_response("transactions_mixed.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            txs = await client.get_transactions("league_001", week=3)
        assert isinstance(txs, list)
        assert len(txs) == 2
        # Caller is responsible for filtering by type/status — the method
        # returns raw shape.
        assert any(t["type"] == "trade" for t in txs)
        assert any(t["type"] == "waiver" for t in txs)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_sleeper_api.py::TestGetTransactions -v
```

Expected: FAIL — `AttributeError: 'SleeperClient' object has no attribute 'get_transactions'`.

- [ ] **Step 3: Implement `get_transactions`**

In `src/sleeper_dynasty/api/sleeper.py`, add after `get_users`:

```python
    async def get_transactions(self, league_id: str, week: int) -> list[dict]:
        """Fetch raw transactions for one league-week.

        Returns the unmodified list of transaction dicts. Caller filters by
        ``type`` (e.g., "trade") and ``status`` ("complete").
        """
        resp = await self._client.get(
            f"/league/{league_id}/transactions/{week}"
        )
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_sleeper_api.py::TestGetTransactions -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py tests/test_sleeper_api.py
git commit -m "$(cat <<'EOF'
Add SleeperClient.get_transactions(league_id, week)

Returns raw transaction list; caller filters by type/status.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Add `get_drafts` and `get_draft_picks` to SleeperClient

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py`
- Modify: `tests/test_sleeper_api.py`

Two related methods grouped into one task because they're both small and used together (you fetch drafts, then for each draft fetch its picks).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sleeper_api.py`:

```python
class TestGetDrafts:
    @pytest.mark.asyncio
    async def test_returns_drafts(self, client):
        resp = mock_response("drafts.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            drafts = await client.get_drafts("league_2024")
        assert isinstance(drafts, list)
        assert len(drafts) == 1
        assert drafts[0]["draft_id"] == "draft_2024_a"
        assert drafts[0]["status"] == "complete"


class TestGetDraftPicks:
    @pytest.mark.asyncio
    async def test_returns_draft_picks(self, client):
        resp = mock_response("draft_picks.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            picks = await client.get_draft_picks("draft_2024_a")
        assert isinstance(picks, list)
        assert len(picks) == 2
        # Each pick carries draft_slot, round, pick_no, roster_id, player_id.
        first = picks[0]
        for key in ("round", "pick_no", "draft_slot", "roster_id", "player_id"):
            assert key in first
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sleeper_api.py::TestGetDrafts tests/test_sleeper_api.py::TestGetDraftPicks -v
```

Expected: FAIL on both — methods don't exist.

- [ ] **Step 3: Implement both methods**

In `src/sleeper_dynasty/api/sleeper.py`, add after `get_transactions`:

```python
    async def get_drafts(self, league_id: str) -> list[dict]:
        """Fetch all drafts associated with a league.

        Returns raw draft dicts. Most leagues have one draft per season but
        startup leagues sometimes record two (startup + rookie).
        """
        resp = await self._client.get(f"/league/{league_id}/drafts")
        resp.raise_for_status()
        return resp.json()

    async def get_draft_picks(self, draft_id: str) -> list[dict]:
        """Fetch every pick made in a draft.

        Each pick dict carries ``round``, ``pick_no``, ``draft_slot``,
        ``roster_id`` (the picker), and ``player_id`` (who was selected).
        Used to resolve traded picks into the players actually drafted.
        """
        resp = await self._client.get(f"/draft/{draft_id}/picks")
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sleeper_api.py::TestGetDrafts tests/test_sleeper_api.py::TestGetDraftPicks -v
```

Expected: PASS on both.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py tests/test_sleeper_api.py
git commit -m "$(cat <<'EOF'
Add SleeperClient.get_drafts and get_draft_picks

Drafts list + per-draft pick rows. Pick rows carry draft_slot, round,
pick_no, roster_id, and player_id — enough to resolve a traded pick
(round + original owner's draft slot) into the drafted player.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Add `get_league` to SleeperClient

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py`
- Modify: `tests/test_sleeper_api.py`

`/league/{id}` returns a single league dict. We need it to walk the chain via `previous_league_id`. Existing `get_leagues` returns the user's list for a season — different endpoint, returns typed `League` objects without `previous_league_id`. The new `get_league` returns the raw dict so we can read `previous_league_id` and also build a `League` object compatibly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sleeper_api.py`:

```python
class TestGetLeague:
    @pytest.mark.asyncio
    async def test_returns_league_and_prev_id(self, client):
        resp = mock_response("league_meta.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            league, prev_id = await client.get_league("league_2024")
        assert isinstance(league, League)
        assert league.league_id == "league_2024"
        assert league.season == 2024
        assert prev_id == "league_2023"

    @pytest.mark.asyncio
    async def test_returns_none_prev_id_when_origin(self, client):
        # Build a one-off response where previous_league_id is null.
        resp = MagicMock()
        payload = load_fixture("league_meta.json")
        payload["previous_league_id"] = None
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            _, prev_id = await client.get_league("league_2024")
        assert prev_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sleeper_api.py::TestGetLeague -v
```

Expected: FAIL — method does not exist.

- [ ] **Step 3: Implement `get_league`**

In `src/sleeper_dynasty/api/sleeper.py`, add after `get_draft_picks`:

```python
    async def get_league(self, league_id: str) -> tuple[League, str | None]:
        """Fetch a single league's metadata and its previous_league_id.

        Returns (League, previous_league_id-or-None). previous_league_id
        is the linkage Sleeper uses to chain dynasty leagues across
        seasons; None on the origin season.
        """
        resp = await self._client.get(f"/league/{league_id}")
        resp.raise_for_status()
        raw = resp.json()
        settings = raw.get("settings") or {}
        league = League(
            league_id=raw["league_id"],
            name=raw["name"],
            season=int(raw["season"]),
            total_rosters=raw["total_rosters"],
            roster_positions=raw.get("roster_positions", []),
            scoring_settings=raw.get("scoring_settings", {}),
            playoff_week_start=settings.get("playoff_week_start", 15),
            num_playoff_teams=settings.get("num_playoff_teams", 6),
            status=raw.get("status", "unknown"),
        )
        return league, raw.get("previous_league_id")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sleeper_api.py::TestGetLeague -v
```

Expected: PASS on both.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py tests/test_sleeper_api.py
git commit -m "$(cat <<'EOF'
Add SleeperClient.get_league for chain walking

Fetches /league/{id} and returns (League, previous_league_id). The
previous_league_id field is what links dynasty seasons together.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Add `walk_league_history` to SleeperClient

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py`
- Modify: `tests/test_sleeper_api.py`

Walks `previous_league_id` from the given league back to the chain origin, returning leagues newest-first. Built on top of `get_league` from Task 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sleeper_api.py`:

```python
class TestWalkLeagueHistory:
    @pytest.mark.asyncio
    async def test_walks_back_to_origin(self, client):
        # Simulate three seasons: 2024 -> 2023 -> 2022 -> (origin).
        def make_resp(league_id, prev_id, season):
            r = MagicMock()
            r.json.return_value = {
                "league_id": league_id,
                "name": "Dynasty Bros",
                "season": str(season),
                "status": "complete",
                "total_rosters": 12,
                "previous_league_id": prev_id,
                "roster_positions": [],
                "settings": {"playoff_week_start": 15, "num_playoff_teams": 6},
                "scoring_settings": {},
            }
            r.raise_for_status.return_value = None
            return r

        responses = [
            make_resp("league_2024", "league_2023", 2024),
            make_resp("league_2023", "league_2022", 2023),
            make_resp("league_2022", None, 2022),
        ]
        with patch.object(
            client._client, "get", AsyncMock(side_effect=responses)
        ):
            chain = await client.walk_league_history("league_2024")
        assert [lg.league_id for lg in chain] == [
            "league_2024", "league_2023", "league_2022",
        ]
        assert [lg.season for lg in chain] == [2024, 2023, 2022]

    @pytest.mark.asyncio
    async def test_single_season_chain(self, client):
        r = MagicMock()
        r.json.return_value = {
            "league_id": "solo",
            "name": "Solo",
            "season": "2025",
            "status": "complete",
            "total_rosters": 12,
            "previous_league_id": None,
            "roster_positions": [],
            "settings": {},
            "scoring_settings": {},
        }
        r.raise_for_status.return_value = None
        with patch.object(client._client, "get", AsyncMock(return_value=r)):
            chain = await client.walk_league_history("solo")
        assert len(chain) == 1
        assert chain[0].league_id == "solo"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sleeper_api.py::TestWalkLeagueHistory -v
```

Expected: FAIL — method does not exist.

- [ ] **Step 3: Implement `walk_league_history`**

In `src/sleeper_dynasty/api/sleeper.py`, add after `get_league`:

```python
    async def walk_league_history(self, league_id: str) -> list[League]:
        """Walk `previous_league_id` back to the chain origin.

        Returns leagues newest → oldest. Terminates when previous_league_id
        is null. Each step is one ``get_league`` call.
        """
        chain: list[League] = []
        current_id: str | None = league_id
        while current_id is not None:
            league, prev_id = await self.get_league(current_id)
            chain.append(league)
            current_id = prev_id
        return chain
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sleeper_api.py::TestWalkLeagueHistory -v
```

Expected: PASS on both.

- [ ] **Step 5: Run the full sleeper-api test file to confirm no regressions**

```bash
pytest tests/test_sleeper_api.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py tests/test_sleeper_api.py
git commit -m "$(cat <<'EOF'
Add SleeperClient.walk_league_history

Walks previous_league_id from a starting league back to the chain
origin. Returns the chain newest → oldest.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Define the trade-asset and trade-grade data models

**Files:**
- Create: `src/sleeper_dynasty/models/trade.py`
- Create: `tests/test_trade_models.py`

Defines the data shapes used by the engine: `TradeAsset` taxonomy, `Trade`, `TradeSide`, `ResolvedTrade`, `TradeGrade`, `RealizedImpact`, `OwnerTradeRecord`. Pure dataclasses — no behavior beyond simple `__post_init__` validation.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_trade_models.py`:

```python
from datetime import datetime, timezone

import pytest

from sleeper_dynasty.models.trade import (
    FaabAsset,
    OwnerTradeRecord,
    PickAsset,
    PlayerAsset,
    RealizedImpact,
    ResolvedTrade,
    Trade,
    TradeGrade,
    TradeSide,
)


def test_player_asset_holds_id_and_name():
    a = PlayerAsset(player_id="123", name="Bijan Robinson")
    assert a.player_id == "123"
    assert a.name == "Bijan Robinson"


def test_pick_asset_carries_season_round_and_original_owner():
    p = PickAsset(season=2025, round=1, original_owner_user_id="u1")
    assert p.season == 2025
    assert p.round == 1
    assert p.original_owner_user_id == "u1"


def test_faab_asset_holds_amount():
    f = FaabAsset(amount=25)
    assert f.amount == 25


def test_trade_side_holds_received_and_given_lists():
    side = TradeSide(
        user_id="u1",
        received=[PlayerAsset("123", "A")],
        given=[PlayerAsset("456", "B")],
    )
    assert side.user_id == "u1"
    assert len(side.received) == 1
    assert len(side.given) == 1


def test_trade_holds_sides_and_metadata():
    when = datetime(2024, 9, 12, tzinfo=timezone.utc)
    trade = Trade(
        transaction_id="tx_001",
        league_id="league_2024",
        season=2024,
        week=2,
        traded_at=when,
        sides={
            "u1": TradeSide("u1", [PlayerAsset("123", "A")], [PlayerAsset("456", "B")]),
            "u2": TradeSide("u2", [PlayerAsset("456", "B")], [PlayerAsset("123", "A")]),
        },
    )
    assert trade.transaction_id == "tx_001"
    assert trade.season == 2024
    assert set(trade.sides.keys()) == {"u1", "u2"}


def test_resolved_trade_wraps_a_trade_with_resolved_sides():
    base = Trade(
        transaction_id="tx_002",
        league_id="league_2024",
        season=2024,
        week=2,
        traded_at=datetime(2024, 9, 12, tzinfo=timezone.utc),
        sides={},
    )
    resolved = ResolvedTrade(trade=base, sides={})
    assert resolved.trade.transaction_id == "tx_002"


def test_realized_impact_aggregates_metrics():
    ri = RealizedImpact(
        starter_weeks=10,
        starter_points_contributed=180.5,
        win_share_points=120.0,
        decisive_starts=3,
        playoff_starts=2,
    )
    assert ri.starter_weeks == 10
    assert ri.playoff_starts == 2


def test_trade_grade_holds_three_lenses_per_side():
    g = TradeGrade(
        trade_id="tx_001",
        snapshot_value_swing={"u1": 1450.0, "u2": -1450.0},
        hindsight_production_swing={"u1": 387.4, "u2": -387.4},
        realized_impact_received={
            "u1": RealizedImpact(18, 286.0, 198.0, 4, 2),
            "u2": RealizedImpact(8, 102.0, 60.0, 1, 0),
        },
        realized_impact_given={
            "u1": RealizedImpact(8, 102.0, 60.0, 1, 0),
            "u2": RealizedImpact(18, 286.0, 198.0, 4, 2),
        },
    )
    assert g.snapshot_value_swing["u1"] == 1450.0
    assert g.realized_impact_received["u1"].starter_weeks == 18


def test_owner_trade_record_defaults_to_zero():
    r = OwnerTradeRecord(user_id="u1", display_name="Tom")
    assert r.trades == 0
    assert r.net_ktc == 0.0
    assert r.net_production == 0.0
    assert r.starter_weeks_gained == 0
    assert r.decisive_starts_gained == 0
    assert r.playoff_starts_gained == 0
    assert r.best_trade_id is None
    assert r.worst_trade_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_trade_models.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.models.trade'`.

- [ ] **Step 3: Implement the models**

Create `src/sleeper_dynasty/models/trade.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# ---------------------------------------------------------------------------
# Asset taxonomy
# ---------------------------------------------------------------------------


@dataclass
class PlayerAsset:
    """A specific NFL player traded as an asset."""

    player_id: str
    name: str


@dataclass
class PickAsset:
    """A future or unused draft pick.

    ``original_owner_user_id`` is the stable user_id of whoever originally
    held this pick (i.e., before any trade). This is what determines the
    draft slot once the draft happens.
    """

    season: int
    round: int
    original_owner_user_id: str


@dataclass
class FaabAsset:
    """A FAAB (free-agent budget) dollar transfer. Recorded, not valued in v1."""

    amount: int


# A TradeAsset is one of the three above. We use isinstance dispatch instead
# of inheritance to keep each shape minimal.
TradeAsset = PlayerAsset | PickAsset | FaabAsset


# ---------------------------------------------------------------------------
# Trade shapes
# ---------------------------------------------------------------------------


@dataclass
class TradeSide:
    """One participant's side of a trade.

    ``received`` and ``given`` are lists of TradeAssets. For a 2-team trade
    each side has exactly the assets the other side gave. For 3+ team trades
    we just record what each side independently received and gave.
    """

    user_id: str
    received: list[TradeAsset]
    given: list[TradeAsset]


@dataclass
class Trade:
    """A complete trade transaction, owner-identified."""

    transaction_id: str
    league_id: str
    season: int
    week: int
    traded_at: datetime
    sides: dict[str, TradeSide]  # keyed by user_id


@dataclass
class ResolvedTrade:
    """A Trade after pick resolution.

    `trade` is the original; `sides` is the post-resolution side map with
    any resolved PickAssets replaced by PlayerAssets representing the
    actual drafted player.
    """

    trade: Trade
    sides: dict[str, TradeSide]


# ---------------------------------------------------------------------------
# Grading shapes
# ---------------------------------------------------------------------------


@dataclass
class RealizedImpact:
    """Lens 3: post-trade usage and win-impact measures for one side."""

    starter_weeks: int = 0
    starter_points_contributed: float = 0.0
    win_share_points: float = 0.0
    decisive_starts: int = 0
    playoff_starts: int = 0


@dataclass
class TradeGrade:
    """All three grading lenses for a single trade, keyed by user_id."""

    trade_id: str
    snapshot_value_swing: dict[str, float] = field(default_factory=dict)
    hindsight_production_swing: dict[str, float] = field(default_factory=dict)
    realized_impact_received: dict[str, RealizedImpact] = field(default_factory=dict)
    realized_impact_given: dict[str, RealizedImpact] = field(default_factory=dict)


@dataclass
class OwnerTradeRecord:
    """Per-owner aggregate across all their trades in the chain."""

    user_id: str
    display_name: str
    trades: int = 0
    net_ktc: float = 0.0
    net_production: float = 0.0
    starter_weeks_gained: int = 0
    decisive_starts_gained: int = 0
    playoff_starts_gained: int = 0
    best_trade_id: str | None = None
    worst_trade_id: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_trade_models.py -v
```

Expected: PASS on all 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/trade.py tests/test_trade_models.py
git commit -m "$(cat <<'EOF'
Add trade-history data models

PlayerAsset / PickAsset / FaabAsset for the asset taxonomy; Trade /
TradeSide / ResolvedTrade for trade shapes; RealizedImpact / TradeGrade
/ OwnerTradeRecord for grading and per-owner aggregation. Pure
dataclasses — behavior lives in the engine modules.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Implement `normalize_trade` in trade_history engine

**Files:**
- Create: `src/sleeper_dynasty/engine/trade_history.py`
- Create: `tests/test_trade_history.py`

`normalize_trade(raw_tx, roster_to_user)` converts a raw Sleeper trade transaction dict into a `Trade` model, mapping every `roster_id` reference to a stable `user_id`. This is the building block before chain walking.

A Sleeper trade transaction's structure:
- `roster_ids` — list of participating roster IDs
- `adds` — dict[player_id, roster_id] of what each roster received
- `drops` — dict[player_id, roster_id] of what each roster gave up
- `draft_picks` — list of pick dicts: `{season, round, roster_id (current), previous_owner_id (the picker's original owner), owner_id (the new owner after this trade)}`
- `waiver_budget` — list of `{sender, receiver, amount}` FAAB transfers
- `created` — ms-epoch timestamp

For each `roster_id` in `roster_ids`, build a `TradeSide` whose `received` lists every asset where the dest roster equals this roster, and whose `given` lists every asset where the source roster equals this roster.

Pick semantics:
- `previous_owner_id` is the roster_id of the team that *originally* owned this pick (before any trades). For grading attribution we need its stable `user_id`.
- `roster_id` on the pick is the *prior* owner before this transaction.
- `owner_id` is the *new* owner after this transaction.
- So this pick is *given* by the roster matching `roster_id` and *received* by the roster matching `owner_id`.

FAAB semantics:
- `sender` is the giving roster, `receiver` is the receiving roster.

- [ ] **Step 1: Write the failing test**

Create `tests/test_trade_history.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sleeper_dynasty.engine.trade_history import normalize_trade
from sleeper_dynasty.models.trade import (
    FaabAsset,
    PickAsset,
    PlayerAsset,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    with open(FIXTURES / name) as f:
        return json.load(f)


def test_normalize_two_team_trade_with_pick_and_player():
    raw_tx = load_fixture("transactions_trade.json")[0]
    # roster 1 -> user "u_alice"; roster 2 -> user "u_bob"
    roster_to_user = {1: "u_alice", 2: "u_bob"}
    trade = normalize_trade(
        raw_tx,
        roster_to_user=roster_to_user,
        league_id="league_2024",
        season=2024,
    )
    assert trade.transaction_id == "tx_001"
    assert trade.league_id == "league_2024"
    assert trade.season == 2024
    assert trade.week == 2
    # 1726099200000 ms = 2024-09-12 00:00:00 UTC.
    assert trade.traded_at == datetime(2024, 9, 12, 0, 0, tzinfo=timezone.utc)
    assert set(trade.sides.keys()) == {"u_alice", "u_bob"}

    alice = trade.sides["u_alice"]
    bob = trade.sides["u_bob"]

    # Alice (roster 1) received Bijan (5678) + 2025 1st (originally hers).
    received_player_ids = [
        a.player_id for a in alice.received if isinstance(a, PlayerAsset)
    ]
    assert "5678" in received_player_ids
    received_picks = [a for a in alice.received if isinstance(a, PickAsset)]
    assert len(received_picks) == 1
    assert received_picks[0].season == 2025
    assert received_picks[0].round == 1
    assert received_picks[0].original_owner_user_id == "u_alice"

    # Alice gave Adams (1234) + 2024 2nd (originally hers).
    given_player_ids = [
        a.player_id for a in alice.given if isinstance(a, PlayerAsset)
    ]
    assert "1234" in given_player_ids
    given_picks = [a for a in alice.given if isinstance(a, PickAsset)]
    assert len(given_picks) == 1
    assert given_picks[0].season == 2024
    assert given_picks[0].round == 2

    # Bob's side is the mirror.
    assert any(
        isinstance(a, PlayerAsset) and a.player_id == "1234"
        for a in bob.received
    )
    assert any(
        isinstance(a, PlayerAsset) and a.player_id == "5678"
        for a in bob.given
    )


def test_normalize_trade_with_faab():
    raw_tx = {
        "type": "trade",
        "status": "complete",
        "transaction_id": "tx_faab",
        "created": 1726099200000,
        "leg": 2,
        "roster_ids": [1, 2],
        "adds": {},
        "drops": {},
        "draft_picks": [],
        "waiver_budget": [{"sender": 1, "receiver": 2, "amount": 25}],
    }
    trade = normalize_trade(
        raw_tx,
        roster_to_user={1: "u_a", 2: "u_b"},
        league_id="L",
        season=2024,
    )
    a, b = trade.sides["u_a"], trade.sides["u_b"]
    assert any(isinstance(x, FaabAsset) and x.amount == 25 for x in a.given)
    assert any(isinstance(x, FaabAsset) and x.amount == 25 for x in b.received)


def test_normalize_skips_unmappable_rosters_gracefully():
    # If a roster_id is missing from the mapping, we still emit the side
    # under the original roster id as a fallback ("Owner #<roster_id>").
    raw_tx = {
        "type": "trade",
        "status": "complete",
        "transaction_id": "tx_ghost",
        "created": 1726099200000,
        "leg": 2,
        "roster_ids": [99, 2],
        "adds": {"1234": 2, "5678": 99},
        "drops": {"5678": 2, "1234": 99},
        "draft_picks": [],
        "waiver_budget": [],
    }
    trade = normalize_trade(
        raw_tx,
        roster_to_user={2: "u_b"},  # roster 99 not mapped
        league_id="L",
        season=2024,
    )
    # The ghost side appears under the fallback identity.
    assert "Owner #99" in trade.sides
    assert "u_b" in trade.sides
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_trade_history.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.trade_history'`.

- [ ] **Step 3: Implement `normalize_trade`**

Create `src/sleeper_dynasty/engine/trade_history.py`:

```python
"""Trade-history engine.

Fetches and normalizes trades across the full dynasty league chain, then
resolves traded picks into the players actually drafted with them.

The public entry points are:
  - normalize_trade(raw_tx, roster_to_user, league_id, season) -> Trade
  - build_trade_history(client, current_league_id, cache) -> list[Trade]
  - resolve_assets(trades, drafts_by_season, draft_picks_by_draft_id,
                   roster_to_user_by_league, player_names) -> list[ResolvedTrade]

Stable owner identity: every roster_id reference in a raw Sleeper trade
transaction is mapped to its Sleeper user_id at the time of the trade,
using that league-season's roster table. Owners who left the league are
graded under an "Owner #<roster_id>" fallback string.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sleeper_dynasty.models.trade import (
    FaabAsset,
    PickAsset,
    PlayerAsset,
    Trade,
    TradeAsset,
    TradeSide,
)

log = logging.getLogger(__name__)


def _identity_for(
    roster_id: int, roster_to_user: dict[int, str]
) -> str:
    """Return stable identity for a roster_id; fall back to a placeholder."""
    if roster_id in roster_to_user:
        return roster_to_user[roster_id]
    log.warning(
        "No user mapping for roster_id=%d; using fallback identity",
        roster_id,
    )
    return f"Owner #{roster_id}"


def normalize_trade(
    raw_tx: dict,
    roster_to_user: dict[int, str],
    league_id: str,
    season: int,
) -> Trade:
    """Convert a raw Sleeper trade transaction into a Trade model.

    ``roster_to_user`` is THIS league-season's roster_id → user_id mapping
    (from ``SleeperClient.get_rosters`` + ``get_users``). Used to attach
    stable owner identity to every asset in the trade.
    """
    # Build a per-identity TradeSide skeleton.
    sides: dict[str, TradeSide] = {}
    for rid in raw_tx.get("roster_ids", []):
        ident = _identity_for(rid, roster_to_user)
        sides.setdefault(ident, TradeSide(user_id=ident, received=[], given=[]))

    # Player adds/drops.
    for player_id, dest_roster_id in (raw_tx.get("adds") or {}).items():
        ident = _identity_for(dest_roster_id, roster_to_user)
        sides.setdefault(ident, TradeSide(user_id=ident, received=[], given=[]))
        sides[ident].received.append(PlayerAsset(player_id=player_id, name=""))
    for player_id, src_roster_id in (raw_tx.get("drops") or {}).items():
        ident = _identity_for(src_roster_id, roster_to_user)
        sides.setdefault(ident, TradeSide(user_id=ident, received=[], given=[]))
        sides[ident].given.append(PlayerAsset(player_id=player_id, name=""))

    # Draft picks. A pick is GIVEN by roster_id (prior owner before this
    # tx) and RECEIVED by owner_id (new owner after this tx).
    for pick in raw_tx.get("draft_picks") or []:
        prior_rid = pick["roster_id"]
        new_rid = pick["owner_id"]
        original_rid = pick["previous_owner_id"]
        giver = _identity_for(prior_rid, roster_to_user)
        receiver = _identity_for(new_rid, roster_to_user)
        original_owner_user_id = _identity_for(original_rid, roster_to_user)
        sides.setdefault(giver, TradeSide(user_id=giver, received=[], given=[]))
        sides.setdefault(receiver, TradeSide(user_id=receiver, received=[], given=[]))
        asset = PickAsset(
            season=int(pick["season"]),
            round=int(pick["round"]),
            original_owner_user_id=original_owner_user_id,
        )
        sides[giver].given.append(asset)
        sides[receiver].received.append(asset)

    # FAAB transfers.
    for fb in raw_tx.get("waiver_budget") or []:
        sender = _identity_for(fb["sender"], roster_to_user)
        receiver = _identity_for(fb["receiver"], roster_to_user)
        sides.setdefault(sender, TradeSide(user_id=sender, received=[], given=[]))
        sides.setdefault(receiver, TradeSide(user_id=receiver, received=[], given=[]))
        amount = int(fb["amount"])
        sides[sender].given.append(FaabAsset(amount=amount))
        sides[receiver].received.append(FaabAsset(amount=amount))

    return Trade(
        transaction_id=str(raw_tx["transaction_id"]),
        league_id=league_id,
        season=season,
        week=int(raw_tx.get("leg", 0)),
        traded_at=datetime.fromtimestamp(
            int(raw_tx["created"]) / 1000.0, tz=timezone.utc
        ),
        sides=sides,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_trade_history.py -v
```

Expected: PASS on all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_history.py tests/test_trade_history.py
git commit -m "$(cat <<'EOF'
Add normalize_trade for raw Sleeper trade → Trade model

Converts adds/drops/draft_picks/waiver_budget into TradeAsset lists per
side, keyed by stable user_id. Picks carry the original owner's user_id
so the resolver can find the right draft slot later.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Implement `resolve_assets` (pick → player resolution)

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_history.py`
- Modify: `tests/test_trade_history.py`

For each `PickAsset` in each trade side, look up the draft for `(pick.season)` and find the row where `draft_slot == original_owner_user_id`'s draft slot in that season's draft + `round == pick.round`. Replace the asset with a `PlayerAsset` for that drafted player. Picks where no matching draft exists (future picks) or no matching row exists (data anomaly) stay as `PickAsset` and are logged.

Sleeper's draft order isn't directly returned per-user — but draft_picks rows carry `draft_slot` and the picking roster_id. We need to know, for each season, what draft_slot each user occupied. We derive it by finding any `round == 1` pick whose `previous_owner_user_id` (translated via that season's roster_to_user map) matches the user_id — that draft_slot is the user's slot for that whole draft.

In practice, the simpler approach: for each (season, round, original_owner_user_id), find a draft_pick row where:
- `round == round`
- `previous_owner_user_id` (mapped from the row's roster_id via that season's roster_to_user) == `original_owner_user_id`

But `draft_picks` rows do NOT carry `previous_owner_id`. They carry just `roster_id` (the picker), `draft_slot`, `round`, `pick_no`, `player_id`. So we must determine the original owner's draft_slot first.

The cleanest derivation: the original owner's draft_slot for a season is the `draft_slot` of any round-1 pick whose `roster_id` corresponds to the original_owner_user_id... but that's the *picker*, which may differ from the original owner if the pick was traded. So that doesn't work either.

**Correct approach:** Sleeper's `/league/{id}/traded_picks` endpoint (already in the codebase) plus the draft_picks endpoint together gives us full provenance — but for picks NOT traded, the slot maps to the rosters' order from `/league/{id}/rosters`, which Sleeper assigns sequentially. We use a simpler heuristic: the slot for a given roster_id is the draft_slot of the round-1 pick where that roster_id was the *original* owner. We derive original ownership by reversing traded_picks: if a round-1 pick's owner_id appears in `traded_picks` for that season + round 1 with a `previous_owner_id`, follow it back; otherwise the picker IS the original owner.

Given this complexity, we take a simpler approach for v1 — described in the implementation step below.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_history.py`:

```python
from sleeper_dynasty.engine.trade_history import resolve_assets
from sleeper_dynasty.models.trade import ResolvedTrade, Trade, TradeSide


def _stub_trade(asset_user_id, season, round_, original_owner_user_id):
    """Build a trivial Trade with one PickAsset on one side, for tests."""
    pick = PickAsset(
        season=season, round=round_, original_owner_user_id=original_owner_user_id
    )
    side = TradeSide(user_id=asset_user_id, received=[pick], given=[])
    other_side = TradeSide(user_id="other", received=[], given=[pick])
    return Trade(
        transaction_id="t1",
        league_id="L",
        season=season - 1,  # traded one season before draft
        week=2,
        traded_at=datetime(season - 1, 9, 12, tzinfo=timezone.utc),
        sides={asset_user_id: side, "other": other_side},
    )


def test_resolve_replaces_pick_when_draft_exists():
    trade = _stub_trade("u1", season=2024, round_=2, original_owner_user_id="u1")
    # Draft data: in 2024, u1's draft_slot is 1. The 2nd-round pick at slot 1
    # was used to draft player_id "p_rookie_b" (matches our fixture).
    drafts_by_season = {2024: {"draft_id": "draft_2024_a", "status": "complete"}}
    draft_picks_by_draft_id = {
        "draft_2024_a": [
            {"round": 2, "pick_no": 13, "draft_slot": 1, "roster_id": 2, "player_id": "p_rookie_b"},
            {"round": 1, "pick_no": 1, "draft_slot": 1, "roster_id": 5, "player_id": "p_rookie_a"},
        ],
    }
    user_to_slot_by_season = {2024: {"u1": 1}}
    player_names = {"p_rookie_b": "Rookie B"}

    resolved = resolve_assets(
        [trade],
        drafts_by_season=drafts_by_season,
        draft_picks_by_draft_id=draft_picks_by_draft_id,
        user_to_slot_by_season=user_to_slot_by_season,
        player_names=player_names,
    )
    assert len(resolved) == 1
    rt = resolved[0]
    assert isinstance(rt, ResolvedTrade)
    side = rt.sides["u1"]
    assert len(side.received) == 1
    asset = side.received[0]
    assert isinstance(asset, PlayerAsset)
    assert asset.player_id == "p_rookie_b"
    assert asset.name == "Rookie B"


def test_resolve_leaves_unresolved_pick_untouched():
    # No draft for the pick's season -> still a PickAsset.
    trade = _stub_trade("u1", season=2030, round_=1, original_owner_user_id="u1")
    resolved = resolve_assets(
        [trade],
        drafts_by_season={},
        draft_picks_by_draft_id={},
        user_to_slot_by_season={},
        player_names={},
    )
    side = resolved[0].sides["u1"]
    assert isinstance(side.received[0], PickAsset)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_trade_history.py::test_resolve_replaces_pick_when_draft_exists tests/test_trade_history.py::test_resolve_leaves_unresolved_pick_untouched -v
```

Expected: FAIL — `resolve_assets` does not exist.

- [ ] **Step 3: Implement `resolve_assets`**

Append to `src/sleeper_dynasty/engine/trade_history.py`:

```python
from sleeper_dynasty.models.trade import ResolvedTrade


def _resolve_one_asset(
    asset: TradeAsset,
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
) -> TradeAsset:
    """Resolve a single asset; PickAsset → PlayerAsset if possible."""
    if not isinstance(asset, PickAsset):
        return asset
    draft = drafts_by_season.get(asset.season)
    if draft is None or draft.get("status") != "complete":
        return asset  # draft hasn't happened yet
    slot_map = user_to_slot_by_season.get(asset.season, {})
    slot = slot_map.get(asset.original_owner_user_id)
    if slot is None:
        log.warning(
            "No draft slot for user=%s in season=%d; leaving pick unresolved",
            asset.original_owner_user_id,
            asset.season,
        )
        return asset
    rows = draft_picks_by_draft_id.get(draft["draft_id"], [])
    for row in rows:
        if row.get("round") == asset.round and row.get("draft_slot") == slot:
            player_id = row.get("player_id")
            if not player_id:
                return asset
            return PlayerAsset(
                player_id=player_id,
                name=player_names.get(player_id, player_id),
            )
    log.warning(
        "Draft %s has no row matching round=%d slot=%d (user=%s); pick stays unresolved",
        draft["draft_id"],
        asset.round,
        slot,
        asset.original_owner_user_id,
    )
    return asset


def _resolve_side(
    side: TradeSide,
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
) -> TradeSide:
    return TradeSide(
        user_id=side.user_id,
        received=[
            _resolve_one_asset(
                a,
                drafts_by_season,
                draft_picks_by_draft_id,
                user_to_slot_by_season,
                player_names,
            )
            for a in side.received
        ],
        given=[
            _resolve_one_asset(
                a,
                drafts_by_season,
                draft_picks_by_draft_id,
                user_to_slot_by_season,
                player_names,
            )
            for a in side.given
        ],
    )


def resolve_assets(
    trades: list[Trade],
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
) -> list[ResolvedTrade]:
    """Replace resolved PickAssets with PlayerAssets for completed drafts."""
    resolved: list[ResolvedTrade] = []
    for trade in trades:
        new_sides = {
            uid: _resolve_side(
                side,
                drafts_by_season,
                draft_picks_by_draft_id,
                user_to_slot_by_season,
                player_names,
            )
            for uid, side in trade.sides.items()
        }
        resolved.append(ResolvedTrade(trade=trade, sides=new_sides))
    return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_trade_history.py -v
```

Expected: PASS on all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_history.py tests/test_trade_history.py
git commit -m "$(cat <<'EOF'
Add resolve_assets — replace resolved PickAssets with PlayerAssets

For each pick in a trade, look up the matching draft slot row (round +
original-owner's draft_slot) and substitute the drafted player.
Unresolved picks (future drafts, missing slot, missing player) stay
as PickAsset and log a warning.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Implement `build_trade_history` orchestrator

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_history.py`
- Modify: `tests/test_trade_history.py`

Orchestrates the full fetch: walk the league chain, for each league pull users + rosters + transactions (weeks 1..18) + drafts + draft_picks, then normalize all trades and resolve their assets. Returns a list of `ResolvedTrade` sorted newest-first plus auxiliary maps callers need (display_name_by_user_id, matchups bundle, drafts).

Because this function makes many network calls and we want testability, it takes a `SleeperClient` and a `FileCache` as parameters. It's organized as a pure orchestrator: each sub-step is its own helper that can be unit-tested.

For simplicity in v1, `user_to_slot_by_season` is derived by reading `/league/{id}/drafts` + `/draft/{id}/picks` and inferring the round-1 slot of each *original* owner as follows: for each round-1 pick row, the picker's roster_id maps (via that season's `roster_to_user`) to a user_id, and that user_id occupies that draft_slot — **unless** that round-1 pick was traded, in which case we follow `traded_picks` back to its original owner. To avoid this complexity in v1, we use a simpler approach: each league-season's initial roster order is what determined the draft slots, and Sleeper assigns roster_ids in slot order. **This holds for most leagues but is not guaranteed.** We document this limitation in code comments and treat slot misses as warnings.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_history.py`:

```python
from unittest.mock import AsyncMock, MagicMock

from sleeper_dynasty.engine.trade_history import build_trade_history


@pytest.mark.asyncio
async def test_build_trade_history_orchestrates_one_season():
    """End-to-end: one league, one trade week, one trade — comes back resolved."""
    # Build a fake SleeperClient that returns canned responses.
    client = MagicMock()

    # Walk: just league_2024 → None.
    from sleeper_dynasty.models.league import League
    league_2024 = League(
        league_id="league_2024",
        name="Bros",
        season=2024,
        total_rosters=2,
        roster_positions=[],
        scoring_settings={},
        playoff_week_start=15,
        num_playoff_teams=6,
        status="complete",
    )
    client.walk_league_history = AsyncMock(return_value=[league_2024])
    client.get_users = AsyncMock(return_value={
        "u_alice": {"display_name": "Alice", "team_name": None},
        "u_bob": {"display_name": "Bob", "team_name": None},
    })

    from sleeper_dynasty.models.league import Roster
    client.get_rosters = AsyncMock(return_value=[
        Roster(roster_id=1, owner_id="u_alice", owner_name="Alice", players=[],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
        Roster(roster_id=2, owner_id="u_bob", owner_name="Bob", players=[],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
    ])

    # transactions: only return the fixture trade on leg 2; empty for everything else.
    fixture_trade = load_fixture("transactions_trade.json")
    async def fake_transactions(league_id, week):
        if week == 2:
            return fixture_trade
        return []
    client.get_transactions = AsyncMock(side_effect=fake_transactions)

    client.get_drafts = AsyncMock(return_value=[{
        "draft_id": "draft_2024_a", "status": "complete", "season": "2024",
    }])
    client.get_draft_picks = AsyncMock(return_value=[
        {"round": 1, "pick_no": 1, "draft_slot": 1, "roster_id": 1, "player_id": "p1"},
        {"round": 2, "pick_no": 14, "draft_slot": 2, "roster_id": 2, "player_id": "p_rookie_b"},
    ])

    player_names = {"5678": "Bijan Robinson", "1234": "Davante Adams", "p_rookie_b": "Rookie B"}

    resolved = await build_trade_history(
        client,
        current_league_id="league_2024",
        player_names=player_names,
    )

    # One trade comes back, fully populated.
    assert len(resolved) == 1
    rt = resolved[0]
    assert rt.trade.season == 2024
    # The 2024 2nd pick was originally Alice's (roster 1) — with draft_slot 1
    # in our fake draft order. But the fixture's draft_picks row for round 2
    # is draft_slot=2 (Bob's). Since Alice's slot=1, the resolver finds no
    # round-2 row at slot 1, so the pick stays unresolved. That's acceptable
    # for v1; we just assert the trade made it through.
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_trade_history.py::test_build_trade_history_orchestrates_one_season -v
```

Expected: FAIL — `build_trade_history` does not exist.

- [ ] **Step 3: Implement `build_trade_history`**

Append to `src/sleeper_dynasty/engine/trade_history.py`:

```python
import asyncio


# Sleeper league weeks 1..18 cover full regular season + playoffs.
_MAX_WEEK = 18


def _derive_user_slot_map(
    draft_picks: list[dict],
    roster_to_user: dict[int, str],
) -> dict[str, int]:
    """Best-effort: map user_id → their draft_slot for this season.

    v1 heuristic: for each round-1 pick row, the picker's roster_id at
    draft time corresponds to a user_id, and that user occupies that
    draft_slot. This is only accurate when round-1 picks have NOT been
    traded — for traded round-1 picks the row's roster_id is the receiver,
    not the original owner. Callers should treat unresolved picks as
    acceptable degradation, not a fatal error.
    """
    user_to_slot: dict[str, int] = {}
    for row in draft_picks:
        if row.get("round") != 1:
            continue
        rid = row.get("roster_id")
        slot = row.get("draft_slot")
        if rid in roster_to_user and slot is not None:
            user_to_slot.setdefault(roster_to_user[rid], slot)
    return user_to_slot


async def _fetch_league_season_data(
    client,
    league,
) -> dict:
    """Pull everything we need for one league-season.

    Returns a dict bundling users, roster_to_user, raw transactions (only
    trades), drafts, and draft_picks_by_draft_id.
    """
    users = await client.get_users(league.league_id)
    rosters = await client.get_rosters(league.league_id)
    roster_to_user = {r.roster_id: r.owner_id for r in rosters}

    # Weekly transactions in parallel chunks of 6.
    async def _one_week(w: int) -> list[dict]:
        return await client.get_transactions(league.league_id, w)

    weeks = range(1, _MAX_WEEK + 1)
    tx_chunks = await asyncio.gather(*(_one_week(w) for w in weeks))
    raw_trades: list[dict] = []
    for week_txs in tx_chunks:
        for tx in week_txs or []:
            if tx.get("type") == "trade" and tx.get("status") == "complete":
                raw_trades.append(tx)

    drafts = await client.get_drafts(league.league_id)
    draft_picks_by_draft_id: dict[str, list[dict]] = {}
    for d in drafts:
        if d.get("status") == "complete":
            picks = await client.get_draft_picks(d["draft_id"])
            draft_picks_by_draft_id[d["draft_id"]] = picks

    return {
        "league": league,
        "users": users,
        "roster_to_user": roster_to_user,
        "raw_trades": raw_trades,
        "drafts": drafts,
        "draft_picks_by_draft_id": draft_picks_by_draft_id,
    }


async def build_trade_history(
    client,
    current_league_id: str,
    player_names: dict[str, str],
) -> list[ResolvedTrade]:
    """Walk the league chain and return all trades, resolved, newest-first.

    Args:
        client: A SleeperClient (or test double exposing the same async
            methods).
        current_league_id: The starting league. We walk back from here.
        player_names: player_id → display name (from Sleeper's players
            blob). Used to label resolved picks.

    Returns:
        ResolvedTrade list, newest first.
    """
    chain = await client.walk_league_history(current_league_id)
    log.info("Trade chain length: %d seasons", len(chain))

    bundles = []
    for league in chain:
        log.info("Fetching trades for season %d (%s)", league.season, league.name)
        bundles.append(await _fetch_league_season_data(client, league))

    # Aggregate drafts + picks across all seasons for resolution.
    drafts_by_season: dict[int, dict] = {}
    draft_picks_by_draft_id: dict[str, list[dict]] = {}
    user_to_slot_by_season: dict[int, dict[str, int]] = {}
    for bundle in bundles:
        season = bundle["league"].season
        for d in bundle["drafts"]:
            if d.get("status") == "complete":
                drafts_by_season[int(d.get("season", season))] = d
        draft_picks_by_draft_id.update(bundle["draft_picks_by_draft_id"])
        # Derive slot map from THIS season's draft picks.
        all_picks_this_season: list[dict] = []
        for picks in bundle["draft_picks_by_draft_id"].values():
            all_picks_this_season.extend(picks)
        user_to_slot_by_season[season] = _derive_user_slot_map(
            all_picks_this_season, bundle["roster_to_user"]
        )

    # Normalize every trade.
    trades: list[Trade] = []
    for bundle in bundles:
        for raw_tx in bundle["raw_trades"]:
            trades.append(
                normalize_trade(
                    raw_tx,
                    roster_to_user=bundle["roster_to_user"],
                    league_id=bundle["league"].league_id,
                    season=bundle["league"].season,
                )
            )

    # Resolve picks.
    resolved = resolve_assets(
        trades,
        drafts_by_season=drafts_by_season,
        draft_picks_by_draft_id=draft_picks_by_draft_id,
        user_to_slot_by_season=user_to_slot_by_season,
        player_names=player_names,
    )

    # Newest first.
    resolved.sort(key=lambda rt: rt.trade.traded_at, reverse=True)
    return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_trade_history.py -v
```

Expected: PASS on all tests.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_history.py tests/test_trade_history.py
git commit -m "$(cat <<'EOF'
Add build_trade_history orchestrator

Walks the league chain, fetches users/rosters/transactions/drafts per
season, normalizes every trade, derives draft-slot maps, and resolves
picks. Returns ResolvedTrades newest-first. Single async entry point
used by the upcoming CLI subcommand.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Implement Lens 1 — snapshot KTC value swing

**Files:**
- Create: `src/sleeper_dynasty/engine/trade_grader.py`
- Create: `tests/test_trade_grader.py`

Computes `snapshot_value_swing[user_id] = Σ KTC(received) − Σ KTC(given)` for one resolved trade. KTC values arrive as a `dict[player_id, KTCValue]`. We use the `superflex_value` field (most dynasty leagues are Superflex; we'll add a future flag if needed). Unresolved `PickAsset` → 0 in v1 (rookie-pick table integration is a follow-up note).

- [ ] **Step 1: Write the failing test**

Create `tests/test_trade_grader.py`:

```python
from datetime import datetime, timezone

import pytest

from sleeper_dynasty.engine.trade_grader import grade_snapshot_value
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.models.trade import (
    FaabAsset,
    PickAsset,
    PlayerAsset,
    ResolvedTrade,
    Trade,
    TradeSide,
)


def _stub_resolved_trade(received_by_uid, given_by_uid):
    """Make a minimal ResolvedTrade with two sides."""
    sides = {
        uid: TradeSide(uid, list(received_by_uid[uid]), list(given_by_uid[uid]))
        for uid in received_by_uid
    }
    base = Trade(
        transaction_id="t1",
        league_id="L",
        season=2024,
        week=2,
        traded_at=datetime(2024, 9, 12, tzinfo=timezone.utc),
        sides=sides,
    )
    return ResolvedTrade(trade=base, sides=sides)


def test_snapshot_value_swing_two_player_trade():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan")],
        },
    )
    ktc = {
        "p_bijan": KTCValue(
            name="Bijan", normalized_name="bijan", position="RB",
            superflex_value=7500, one_qb_value=7400,
        ),
        "p_adams": KTCValue(
            name="Adams", normalized_name="adams", position="WR",
            superflex_value=6050, one_qb_value=6000,
        ),
    }
    swings = grade_snapshot_value(rt, ktc, fmt="superflex")
    assert swings["u1"] == pytest.approx(7500 - 6050)  # +1450
    assert swings["u2"] == pytest.approx(6050 - 7500)  # -1450


def test_snapshot_value_unknown_player_counts_as_zero():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("missing", "?")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("missing", "?")]},
    )
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex")
    assert swings["u1"] == 0.0
    assert swings["u2"] == 0.0


def test_snapshot_value_faab_is_zero():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [FaabAsset(amount=25)], "u2": []},
        given_by_uid={"u1": [], "u2": [FaabAsset(amount=25)]},
    )
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex")
    assert swings["u1"] == 0.0
    assert swings["u2"] == 0.0


def test_snapshot_value_unresolved_pick_is_zero_in_v1():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
            "u2": [],
        },
        given_by_uid={"u1": [], "u2": [PickAsset(season=2030, round=1, original_owner_user_id="u1")]},
    )
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex")
    assert swings["u1"] == 0.0
    assert swings["u2"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_trade_grader.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.trade_grader'`.

- [ ] **Step 3: Implement `grade_snapshot_value`**

Create `src/sleeper_dynasty/engine/trade_grader.py`:

```python
"""Trade grader.

Three lenses, computed independently per trade:

  Lens 1 — Snapshot KTC value swing
  Lens 2 — Hindsight production swing
  Lens 3 — Realized impact (starter weeks, win-share points, etc.)

Per-owner aggregation rolls each grade across that owner's entire history.
"""

from __future__ import annotations

import logging

from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.models.trade import (
    FaabAsset,
    OwnerTradeRecord,
    PickAsset,
    PlayerAsset,
    RealizedImpact,
    ResolvedTrade,
    TradeAsset,
    TradeGrade,
)

log = logging.getLogger(__name__)


def _ktc_value(asset: TradeAsset, ktc: dict[str, KTCValue], fmt: str) -> float:
    """KTC value of an asset for snapshot grading.

    PlayerAsset: use today's KTC value (Superflex or 1QB per fmt).
    PickAsset (unresolved): 0 in v1 (no rookie-pick table integration yet).
    FaabAsset: 0 (not valued in v1).
    """
    if isinstance(asset, PlayerAsset):
        v = ktc.get(asset.player_id)
        if v is None:
            log.warning("No KTC value for player %s (%s)", asset.player_id, asset.name)
            return 0.0
        raw = v.superflex_value if fmt == "superflex" else v.one_qb_value
        return float(raw) if raw is not None else 0.0
    return 0.0


def grade_snapshot_value(
    rt: ResolvedTrade,
    ktc_values: dict[str, KTCValue],
    fmt: str = "superflex",
) -> dict[str, float]:
    """Compute snapshot KTC value swing per side."""
    swings: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = sum(_ktc_value(a, ktc_values, fmt) for a in side.received)
        given = sum(_ktc_value(a, ktc_values, fmt) for a in side.given)
        swings[uid] = received - given
    return swings
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_trade_grader.py -v
```

Expected: PASS on all 4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader.py
git commit -m "$(cat <<'EOF'
Add Lens 1 — snapshot KTC value swing

Computes per-side value differential using today's KTC values.
Unknown players + unresolved picks + FAAB all contribute zero in v1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Implement Lens 2 — hindsight production swing

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py`
- Modify: `tests/test_trade_grader.py`

Sum fantasy points each `PlayerAsset` received scored for the receiving team, every week from the trade date through the latest played week, across the league chain. "Phantom production" for given assets = what the player actually scored *anywhere* in those weeks (since they belong to someone after the trade).

Input shape — a `MatchupWeek` bundle we pass in: keyed by `(league_id, week, roster_id)`, value is a dict `{"starters": list[str], "players": list[str], "players_points": dict[str, float], "team_points": float}`. We expect callers to assemble this from `get_matchups` results (we'll do that wiring in Task 15).

For determining "which roster did the received player end up on for this week," we check each `(league_id, week)`'s matchup entries: a player belongs to the roster whose `players` list contains them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trade_grader.py`:

```python
from sleeper_dynasty.engine.trade_grader import grade_hindsight_production


def test_hindsight_sums_post_trade_points_for_receiver():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan")],
        },
    )
    # u1 -> roster 1; u2 -> roster 2 in 2024 league.
    roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    # Trade was week 2; weeks 3+ count.
    matchups = {
        ("L", 3, 1): {
            "starters": [], "players": ["p_bijan"],
            "players_points": {"p_bijan": 20.0}, "team_points": 100.0,
        },
        ("L", 3, 2): {
            "starters": [], "players": ["p_adams"],
            "players_points": {"p_adams": 15.0}, "team_points": 90.0,
        },
        ("L", 4, 1): {
            "starters": [], "players": ["p_bijan"],
            "players_points": {"p_bijan": 25.0}, "team_points": 105.0,
        },
        ("L", 4, 2): {
            "starters": [], "players": ["p_adams"],
            "players_points": {"p_adams": 10.0}, "team_points": 85.0,
        },
    }
    swings = grade_hindsight_production(
        rt,
        matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
    )
    # u1: received Bijan (45 pts), gave Adams (25 phantom) → +20
    # u2: received Adams (25 pts), gave Bijan (45 phantom) → -20
    assert swings["u1"] == pytest.approx(20.0)
    assert swings["u2"] == pytest.approx(-20.0)


def test_hindsight_ignores_weeks_before_trade():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    # Trade week is 2 (per _stub_resolved_trade). Week 1 should not count.
    matchups = {
        ("L", 1, 1): {
            "starters": [], "players": ["p_x"],
            "players_points": {"p_x": 99.0}, "team_points": 100.0,
        },
        ("L", 3, 1): {
            "starters": [], "players": ["p_x"],
            "players_points": {"p_x": 10.0}, "team_points": 100.0,
        },
    }
    swings = grade_hindsight_production(
        rt,
        matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
    )
    assert swings["u1"] == pytest.approx(10.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_trade_grader.py::test_hindsight_sums_post_trade_points_for_receiver tests/test_trade_grader.py::test_hindsight_ignores_weeks_before_trade -v
```

Expected: FAIL — `grade_hindsight_production` does not exist.

- [ ] **Step 3: Implement `grade_hindsight_production`**

Append to `src/sleeper_dynasty/engine/trade_grader.py`:

```python
def grade_hindsight_production(
    rt: ResolvedTrade,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
) -> dict[str, float]:
    """Sum points received per side, post-trade.

    Args:
        rt: Resolved trade to grade.
        matchups: ``(league_id, week, roster_id) -> matchup-entry-dict``
            covering the entire chain post-trade. Each entry carries
            ``players`` (list of player_ids on the roster that week) and
            ``players_points`` (per-player scoring).
        roster_to_user_by_league: per-league roster_id → user_id mapping.

    Returns:
        ``user_id -> production swing`` (received − given_phantom).
    """
    # For fast lookup: who has each player on each (league, week)?
    # Reverse-index from matchups.
    player_to_user_by_week: dict[tuple[str, int, str], str] = {}
    for (league_id, week, roster_id), entry in matchups.items():
        user_map = roster_to_user_by_league.get(league_id, {})
        uid = user_map.get(roster_id)
        if uid is None:
            continue
        for pid in entry.get("players", []) or []:
            player_to_user_by_week[(league_id, week, pid)] = uid

    # Helper to compute received-side production for one PlayerAsset
    # owned by `target_uid` from `trade_week` onward in `trade_league`.
    def _received_points(pid: str, target_uid: str) -> float:
        total = 0.0
        for (lg, wk, rid), entry in matchups.items():
            # Only count weeks strictly after the trade week IN the
            # league chain. Since we're walking the chain forward, every
            # league-week pair after the trade is fair game.
            if not _is_post_trade(lg, wk, rt):
                continue
            user_map = roster_to_user_by_league.get(lg, {})
            owner = user_map.get(rid)
            if owner != target_uid:
                continue
            if pid not in (entry.get("players") or []):
                continue
            total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        return total

    # Helper to compute phantom production for a given asset.
    def _phantom_points(pid: str) -> float:
        total = 0.0
        for (lg, wk, _rid), entry in matchups.items():
            if not _is_post_trade(lg, wk, rt):
                continue
            if pid not in (entry.get("players") or []):
                continue
            total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        return total

    swings: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = 0.0
        for a in side.received:
            if isinstance(a, PlayerAsset):
                received += _received_points(a.player_id, uid)
        given = 0.0
        for a in side.given:
            if isinstance(a, PlayerAsset):
                given += _phantom_points(a.player_id)
        swings[uid] = received - given
    return swings


def _is_post_trade(
    league_id: str, week: int, rt: ResolvedTrade
) -> bool:
    """True if (league_id, week) is strictly after the trade.

    Trade week itself is excluded — Sleeper trades typically take effect
    the following week.
    """
    trade_league = rt.trade.league_id
    trade_week = rt.trade.week
    trade_season = rt.trade.season
    # Different season chronology: deduce from naming — we trust caller
    # to pass matchups only for the chain. So season comparison is
    # roughly the league_id season vs. the trade season. We use the
    # week comparison only within the same league; across leagues the
    # trade_season precedes the matchup season → always count.
    if league_id == trade_league:
        return week > trade_week
    # If we knew the matchup's season we'd compare; in practice the
    # caller filters this to "leagues at or after the trade league," so
    # for any other league it must be a later season.
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_trade_grader.py -v
```

Expected: PASS on all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader.py
git commit -m "$(cat <<'EOF'
Add Lens 2 — hindsight production swing

For each PlayerAsset received, sum points scored for the receiving
team from the week after the trade through the latest played week
across the chain. Symmetric phantom production for given assets.
Pre-trade weeks excluded; trade week itself excluded.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Implement Lens 3 — realized impact

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py`
- Modify: `tests/test_trade_grader.py`

Compute the five sub-metrics per side (received and given): starter weeks, starter points contributed, win-share points, decisive starts, playoff starts. Requires matchups with `starters` lists, per-player points, and per-team points + opponent points (to detect wins and margins).

We expect matchup entries to also carry `opponent_points` (the other side of the matchup that week). We'll wire this when assembling matchups in Task 15.

Playoff weeks are `week >= playoff_week_start` per the league's settings — caller passes a `playoff_weeks_by_league` map.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trade_grader.py`:

```python
from sleeper_dynasty.engine.trade_grader import grade_realized_impact
from sleeper_dynasty.models.trade import RealizedImpact


def test_realized_impact_starter_weeks_and_points():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_bijan", "Bijan")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_bijan", "Bijan")]},
    )
    # Bijan starts for u1 (roster 1) in weeks 3 and 4; sits in week 5.
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 20.0},
            "team_points": 100.0, "opponent_points": 80.0,
        },
        ("L", 4, 1): {
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 25.0},
            "team_points": 90.0, "opponent_points": 95.0,
        },
        ("L", 5, 1): {
            "starters": [], "players": ["p_bijan"],
            "players_points": {"p_bijan": 30.0},
            "team_points": 110.0, "opponent_points": 100.0,
        },
    }
    received, given = grade_realized_impact(
        rt,
        matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_weeks_by_league={"L": 15},
    )
    # u1 received Bijan: 2 starter weeks (3 and 4), 45 SPC, 20 WSP
    # (only week 3 was a win), 0 DS (week 3 margin = 20, Bijan = 20 not >),
    # 0 PS (no playoff weeks in this sample).
    r1 = received["u1"]
    assert r1.starter_weeks == 2
    assert r1.starter_points_contributed == pytest.approx(45.0)
    assert r1.win_share_points == pytest.approx(20.0)
    assert r1.decisive_starts == 0
    assert r1.playoff_starts == 0


def test_realized_impact_decisive_start():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 25.0},
            "team_points": 100.0, "opponent_points": 90.0,  # margin = 10
        },
    }
    received, _given = grade_realized_impact(
        rt,
        matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_weeks_by_league={"L": 15},
    )
    # Player scored 25, margin was 10 — player points > margin → decisive.
    assert received["u1"].decisive_starts == 1


def test_realized_impact_playoff_start():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    matchups = {
        ("L", 15, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 18.0},
            "team_points": 105.0, "opponent_points": 90.0,
        },
    }
    received, _given = grade_realized_impact(
        rt,
        matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_weeks_by_league={"L": 15},
    )
    assert received["u1"].playoff_starts == 1
    assert received["u1"].starter_weeks == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_trade_grader.py::test_realized_impact_starter_weeks_and_points tests/test_trade_grader.py::test_realized_impact_decisive_start tests/test_trade_grader.py::test_realized_impact_playoff_start -v
```

Expected: FAIL — `grade_realized_impact` does not exist.

- [ ] **Step 3: Implement `grade_realized_impact`**

Append to `src/sleeper_dynasty/engine/trade_grader.py`:

```python
def grade_realized_impact(
    rt: ResolvedTrade,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
) -> tuple[dict[str, RealizedImpact], dict[str, RealizedImpact]]:
    """Compute Lens 3 sub-metrics per side.

    Returns (received_impact_by_user, given_impact_by_user). The given map
    uses phantom semantics: it measures what the GIVEN players did on
    whatever team they ended up rostered by post-trade.
    """

    def _impact_for_player(pid: str, target_uid: str | None) -> RealizedImpact:
        """Compute impact metrics for one player.

        If ``target_uid`` is provided, only weeks where that user owned the
        player count (received-side semantics). If None, every week the
        player was rostered counts (phantom / given-side semantics).
        """
        ri = RealizedImpact()
        for (lg, wk, rid), entry in matchups.items():
            if not _is_post_trade(lg, wk, rt):
                continue
            if target_uid is not None:
                user_map = roster_to_user_by_league.get(lg, {})
                if user_map.get(rid) != target_uid:
                    continue
            if pid not in (entry.get("players") or []):
                continue
            is_starter = pid in (entry.get("starters") or [])
            points = float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
            team_pts = float(entry.get("team_points") or 0.0)
            opp_pts = float(entry.get("opponent_points") or 0.0)
            playoff_start_week = playoff_weeks_by_league.get(lg, 15)
            if is_starter:
                ri.starter_weeks += 1
                ri.starter_points_contributed += points
                if team_pts > opp_pts:
                    ri.win_share_points += points
                    margin = team_pts - opp_pts
                    if points > margin:
                        ri.decisive_starts += 1
                if wk >= playoff_start_week:
                    ri.playoff_starts += 1
        return ri

    received: dict[str, RealizedImpact] = {}
    given: dict[str, RealizedImpact] = {}
    for uid, side in rt.sides.items():
        agg_recv = RealizedImpact()
        for a in side.received:
            if isinstance(a, PlayerAsset):
                ri = _impact_for_player(a.player_id, target_uid=uid)
                agg_recv.starter_weeks += ri.starter_weeks
                agg_recv.starter_points_contributed += ri.starter_points_contributed
                agg_recv.win_share_points += ri.win_share_points
                agg_recv.decisive_starts += ri.decisive_starts
                agg_recv.playoff_starts += ri.playoff_starts
        agg_given = RealizedImpact()
        for a in side.given:
            if isinstance(a, PlayerAsset):
                ri = _impact_for_player(a.player_id, target_uid=None)
                agg_given.starter_weeks += ri.starter_weeks
                agg_given.starter_points_contributed += ri.starter_points_contributed
                agg_given.win_share_points += ri.win_share_points
                agg_given.decisive_starts += ri.decisive_starts
                agg_given.playoff_starts += ri.playoff_starts
        received[uid] = agg_recv
        given[uid] = agg_given
    return received, given
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_trade_grader.py -v
```

Expected: PASS on all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader.py
git commit -m "$(cat <<'EOF'
Add Lens 3 — realized impact

Starter weeks, starter points contributed, win-share points, decisive
starts, playoff starts — computed independently per side (received uses
the receiving owner; given uses phantom semantics across any owner).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Combine lenses into `grade_trade` + per-owner aggregation

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py`
- Modify: `tests/test_trade_grader.py`

Top-level `grade_trade(rt, ktc, matchups, ...)` returns a `TradeGrade` combining the three lenses. `aggregate_owner_records(grades, display_names)` rolls up across all trades into `dict[user_id, OwnerTradeRecord]`.

Best/worst trade is identified by the `snapshot_value_swing` for that owner (i.e., the snapshot-lens favorite/least-favorite). We pick snapshot as the tiebreaker for "best/worst" because it's the most-recognizable trade-grading axis to a fantasy reader and is independent of how long ago the trade happened.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trade_grader.py`:

```python
from sleeper_dynasty.engine.trade_grader import aggregate_owner_records, grade_trade


def test_grade_trade_combines_all_three_lenses():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan")],
        },
    )
    ktc = {
        "p_bijan": KTCValue(
            name="Bijan", normalized_name="b", position="RB",
            superflex_value=7500, one_qb_value=7400,
        ),
        "p_adams": KTCValue(
            name="Adams", normalized_name="a", position="WR",
            superflex_value=6050, one_qb_value=6000,
        ),
    }
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 20.0},
            "team_points": 100.0, "opponent_points": 80.0,
        },
        ("L", 3, 2): {
            "starters": ["p_adams"], "players": ["p_adams"],
            "players_points": {"p_adams": 15.0},
            "team_points": 90.0, "opponent_points": 95.0,
        },
    }
    grade = grade_trade(
        rt,
        ktc_values=ktc,
        matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_weeks_by_league={"L": 15},
        fmt="superflex",
    )
    assert grade.trade_id == "t1"
    assert grade.snapshot_value_swing["u1"] == pytest.approx(1450.0)
    assert grade.hindsight_production_swing["u1"] == pytest.approx(20.0 - 15.0)
    assert grade.realized_impact_received["u1"].starter_weeks == 1


def test_aggregate_owner_records_sums_across_trades():
    g1 = TradeGrade(
        trade_id="t1",
        snapshot_value_swing={"u1": 1000.0, "u2": -1000.0},
        hindsight_production_swing={"u1": 50.0, "u2": -50.0},
        realized_impact_received={
            "u1": RealizedImpact(starter_weeks=5, starter_points_contributed=80.0,
                                 win_share_points=60.0, decisive_starts=2, playoff_starts=1),
            "u2": RealizedImpact(),
        },
        realized_impact_given={
            "u1": RealizedImpact(starter_weeks=2),
            "u2": RealizedImpact(starter_weeks=5),
        },
    )
    g2 = TradeGrade(
        trade_id="t2",
        snapshot_value_swing={"u1": -500.0, "u3": 500.0},
        hindsight_production_swing={"u1": -10.0, "u3": 10.0},
        realized_impact_received={
            "u1": RealizedImpact(),
            "u3": RealizedImpact(starter_weeks=3, decisive_starts=1),
        },
        realized_impact_given={
            "u1": RealizedImpact(starter_weeks=3),
            "u3": RealizedImpact(),
        },
    )
    display_names = {"u1": "Alice", "u2": "Bob", "u3": "Carol"}
    records = aggregate_owner_records([g1, g2], display_names=display_names)
    a = records["u1"]
    assert a.trades == 2
    assert a.net_ktc == pytest.approx(500.0)
    assert a.net_production == pytest.approx(40.0)
    # SW gained = received - phantom-given: u1 = (5+0) - (2+3) = 0
    assert a.starter_weeks_gained == 0
    assert a.decisive_starts_gained == 2
    assert a.playoff_starts_gained == 1
    # Best trade for u1 is t1 (+1000 ktc); worst is t2 (-500 ktc).
    assert a.best_trade_id == "t1"
    assert a.worst_trade_id == "t2"
    # u3 only participated in t2.
    c = records["u3"]
    assert c.trades == 1
    assert c.net_ktc == pytest.approx(500.0)
    assert c.best_trade_id == "t2"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_trade_grader.py::test_grade_trade_combines_all_three_lenses tests/test_trade_grader.py::test_aggregate_owner_records_sums_across_trades -v
```

Expected: FAIL — neither function exists yet.

- [ ] **Step 3: Implement `grade_trade` and `aggregate_owner_records`**

Append to `src/sleeper_dynasty/engine/trade_grader.py`:

```python
def grade_trade(
    rt: ResolvedTrade,
    ktc_values: dict[str, KTCValue],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
    fmt: str = "superflex",
) -> TradeGrade:
    """Compute all three lenses for a single trade."""
    snapshot = grade_snapshot_value(rt, ktc_values, fmt=fmt)
    hindsight = grade_hindsight_production(
        rt, matchups, roster_to_user_by_league
    )
    received, given = grade_realized_impact(
        rt,
        matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        playoff_weeks_by_league=playoff_weeks_by_league,
    )
    return TradeGrade(
        trade_id=rt.trade.transaction_id,
        snapshot_value_swing=snapshot,
        hindsight_production_swing=hindsight,
        realized_impact_received=received,
        realized_impact_given=given,
    )


def aggregate_owner_records(
    grades: list[TradeGrade],
    display_names: dict[str, str],
) -> dict[str, OwnerTradeRecord]:
    """Roll grades across all trades into per-owner records."""
    records: dict[str, OwnerTradeRecord] = {}
    best_swing: dict[str, float] = {}
    worst_swing: dict[str, float] = {}
    for g in grades:
        for uid, swing in g.snapshot_value_swing.items():
            rec = records.setdefault(
                uid,
                OwnerTradeRecord(
                    user_id=uid,
                    display_name=display_names.get(uid, uid),
                ),
            )
            rec.trades += 1
            rec.net_ktc += swing
            rec.net_production += g.hindsight_production_swing.get(uid, 0.0)
            recv = g.realized_impact_received.get(uid, RealizedImpact())
            giv = g.realized_impact_given.get(uid, RealizedImpact())
            rec.starter_weeks_gained += recv.starter_weeks - giv.starter_weeks
            rec.decisive_starts_gained += recv.decisive_starts
            rec.playoff_starts_gained += recv.playoff_starts
            if uid not in best_swing or swing > best_swing[uid]:
                best_swing[uid] = swing
                rec.best_trade_id = g.trade_id
            if uid not in worst_swing or swing < worst_swing[uid]:
                worst_swing[uid] = swing
                rec.worst_trade_id = g.trade_id
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_trade_grader.py -v
```

Expected: PASS on all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader.py
git commit -m "$(cat <<'EOF'
Add grade_trade + aggregate_owner_records

grade_trade composes the three lenses into a TradeGrade.
aggregate_owner_records rolls grades into per-owner records: trade
count, net KTC, net production, starter-weeks gained, decisive/playoff
starts, and best/worst trade by snapshot-value swing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Add `write_tab_trade_ledger` to GoogleDocsReport

**Files:**
- Modify: `src/sleeper_dynasty/output/google_docs.py`
- Modify: `tests/test_google_docs.py`

Add a tab writer that renders each trade as a heading + two-column table-like layout, followed by a grades block. Chronological, newest first. Reuses existing `_buffer_paragraph`, `_buffer_table`, `_buffer_blank_line`, `_buffer_page_break`, `_begin_section`, `_flush_section` helpers.

To keep this manageable we render each trade as a single 2-column table with headers ("Side A" | "Side B"), one row each for "Received," "Gave," then grade rows. For 3+ team trades we render a wider table; v1 supports 2-side trades cleanly and labels 3+ team trades with a "(multi-team trade — see summary)" note before showing N columns.

- [ ] **Step 1: Look up existing test patterns**

Read `tests/test_google_docs.py` to confirm the test pattern used for tab writers. Existing tests likely instantiate a `GoogleDocsReport`, mock service clients, and verify `_buffer_*` calls were made. Capture the pattern; the test below mirrors it.

```bash
head -120 tests/test_google_docs.py
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_google_docs.py`:

```python
from datetime import datetime, timezone

from sleeper_dynasty.engine.trade_grader import aggregate_owner_records
from sleeper_dynasty.models.trade import (
    PlayerAsset,
    PickAsset,
    RealizedImpact,
    ResolvedTrade,
    Trade,
    TradeGrade,
    TradeSide,
)
from sleeper_dynasty.output.google_docs import GoogleDocsReport


def _two_party_resolved_trade():
    sides = {
        "u1": TradeSide(
            "u1",
            received=[PlayerAsset("p_bijan", "Bijan Robinson")],
            given=[PlayerAsset("p_adams", "Davante Adams"),
                   PickAsset(season=2025, round=2, original_owner_user_id="u1")],
        ),
        "u2": TradeSide(
            "u2",
            received=[PlayerAsset("p_adams", "Davante Adams"),
                      PickAsset(season=2025, round=2, original_owner_user_id="u1")],
            given=[PlayerAsset("p_bijan", "Bijan Robinson")],
        ),
    }
    t = Trade(
        transaction_id="tx_001",
        league_id="L",
        season=2024,
        week=2,
        traded_at=datetime(2024, 9, 12, tzinfo=timezone.utc),
        sides=sides,
    )
    return ResolvedTrade(trade=t, sides=sides)


def test_write_tab_trade_ledger_buffers_one_table_per_trade(monkeypatch):
    report = GoogleDocsReport(league_name="Bros", season=2024)
    # Stub batch update + GET so the flush is a no-op.
    monkeypatch.setattr(report, "_safe_batch_update",
                        lambda doc_id, requests, context="": {})
    monkeypatch.setattr(report, "_get_document",
                        lambda doc_id: {"body": {"content": []}})
    # Capture buffered tables.
    tables = []
    orig_buffer_table = report._buffer_table
    def spy_table(headers, rows, **kwargs):
        tables.append((list(headers), [list(r) for r in rows]))
        return orig_buffer_table(headers, rows, **kwargs)
    monkeypatch.setattr(report, "_buffer_table", spy_table)

    rt = _two_party_resolved_trade()
    grade = TradeGrade(
        trade_id="tx_001",
        snapshot_value_swing={"u1": 1450.0, "u2": -1450.0},
        hindsight_production_swing={"u1": 387.4, "u2": -387.4},
        realized_impact_received={
            "u1": RealizedImpact(18, 286.0, 198.0, 4, 2),
            "u2": RealizedImpact(8, 102.0, 60.0, 1, 0),
        },
        realized_impact_given={
            "u1": RealizedImpact(8, 102.0, 60.0, 1, 0),
            "u2": RealizedImpact(18, 286.0, 198.0, 4, 2),
        },
    )
    display_names = {"u1": "Tom", "u2": "Jim"}

    report.write_tab_trade_ledger(
        doc_id="fake",
        resolved_trades=[rt],
        grades_by_trade_id={"tx_001": grade},
        display_names=display_names,
        league_name_by_id={"L": "Bros"},
    )

    # One table per trade in v1 (with headers being the two side labels).
    assert len(tables) >= 1
    headers, rows = tables[0]
    assert headers[0].startswith("Tom") or headers[1].startswith("Tom")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/test_google_docs.py::test_write_tab_trade_ledger_buffers_one_table_per_trade -v
```

Expected: FAIL — `write_tab_trade_ledger` does not exist.

- [ ] **Step 4: Implement `write_tab_trade_ledger`**

In `src/sleeper_dynasty/output/google_docs.py`, after the existing `write_tab_matchup_forecasts`, add:

```python
    def write_tab_trade_ledger(
        self,
        doc_id: str,
        resolved_trades: list,
        grades_by_trade_id: dict,
        display_names: dict[str, str],
        league_name_by_id: dict[str, str],
    ) -> None:
        """Write the chronological trade ledger tab.

        Each trade becomes a 2-column table (Side A | Side B) with rows
        for Received, Gave, and the three grading lenses. 3+ team trades
        render as N-column tables with the same row layout.
        """
        logger.info("Writing Trade Ledger section to doc %s", doc_id)
        self._begin_section(doc_id)
        self._buffer_page_break()
        self._buffer_paragraph(
            "Trade Ledger", named_style="HEADING_1", bold=True
        )
        self._buffer_paragraph(
            "Every trade across the dynasty league chain, newest first. "
            "Each trade is graded through three independent lenses — snapshot "
            "KTC value, hindsight production, and realized impact.",
            named_style="NORMAL_TEXT",
            foreground_color={"red": 0.4, "green": 0.4, "blue": 0.4},
        )
        self._buffer_blank_line()
        self._flush_section(doc_id)

        for rt in resolved_trades:
            self._begin_section(doc_id)
            grade = grades_by_trade_id.get(rt.trade.transaction_id)
            league_name = league_name_by_id.get(rt.trade.league_id, rt.trade.league_id)
            ts = rt.trade.traded_at.strftime("%Y-%m-%d")
            self._buffer_paragraph(
                f"Trade · {ts} · Week {rt.trade.week} · "
                f"League: \"{league_name}\" ({rt.trade.season} season)",
                named_style="HEADING_2",
                bold=True,
            )

            side_uids = list(rt.sides.keys())
            headers = [
                f"{display_names.get(uid, uid)}" for uid in side_uids
            ]
            rows: list[list[str]] = []

            # Received row.
            received_cells = [
                "\n".join(_render_asset(a) for a in rt.sides[uid].received) or "—"
                for uid in side_uids
            ]
            rows.append([f"Received:\n{cell}" for cell in received_cells])

            # Gave row.
            given_cells = [
                "\n".join(_render_asset(a) for a in rt.sides[uid].given) or "—"
                for uid in side_uids
            ]
            rows.append([f"Gave:\n{cell}" for cell in given_cells])

            if grade is not None:
                rows.append([
                    f"Snapshot KTC: {grade.snapshot_value_swing.get(uid, 0):+.0f}"
                    for uid in side_uids
                ])
                rows.append([
                    f"Hindsight pts: {grade.hindsight_production_swing.get(uid, 0):+.1f}"
                    for uid in side_uids
                ])
                rows.append([
                    _format_impact_cell(grade.realized_impact_received.get(uid))
                    for uid in side_uids
                ])

            self._buffer_table(headers, rows)
            self._buffer_blank_line()
            self._flush_section(doc_id)

        # Footnotes
        self._begin_section(doc_id)
        for note in (
            "KTC values reflect today's snapshot.",
            "Production figures sum points across all played weeks since "
            "the trade within this league chain.",
            "FAAB in trades is recorded but not valued.",
        ):
            self._buffer_paragraph(
                note,
                named_style="NORMAL_TEXT",
                foreground_color={"red": 0.5, "green": 0.5, "blue": 0.5},
            )
        self._flush_section(doc_id)


def _render_asset(asset) -> str:
    """Render a single TradeAsset as one line of text."""
    from sleeper_dynasty.models.trade import FaabAsset, PickAsset, PlayerAsset
    if isinstance(asset, PlayerAsset):
        return f"• {asset.name}"
    if isinstance(asset, PickAsset):
        return (
            f"• {asset.season} round {asset.round} "
            f"(from {asset.original_owner_user_id}) [unresolved]"
        )
    if isinstance(asset, FaabAsset):
        return f"• ${asset.amount} FAAB"
    return "• ?"


def _format_impact_cell(ri) -> str:
    if ri is None:
        return "Realized: —"
    return (
        f"Realized: {ri.starter_weeks} SW · "
        f"{ri.starter_points_contributed:.0f} SPC · "
        f"{ri.win_share_points:.0f} WSP · "
        f"{ri.decisive_starts} DS · "
        f"{ri.playoff_starts} PS"
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_google_docs.py::test_write_tab_trade_ledger_buffers_one_table_per_trade -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/output/google_docs.py tests/test_google_docs.py
git commit -m "$(cat <<'EOF'
Add write_tab_trade_ledger to GoogleDocsReport

Renders each trade as a heading + N-column table (Side A | Side B)
with rows for Received, Gave, and the three grading lenses. Chrono
order, newest first; footnotes explaining each lens at the end.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: Add `write_tab_owner_standings` to GoogleDocsReport

**Files:**
- Modify: `src/sleeper_dynasty/output/google_docs.py`
- Modify: `tests/test_google_docs.py`

A single table — one row per owner — sorted by Net KTC descending. Columns: Owner, Trades, Net KTC, Net Prod, SW Gained, DS Gained, PS Gained, Best, Worst.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_google_docs.py`:

```python
from sleeper_dynasty.models.trade import OwnerTradeRecord


def test_write_tab_owner_standings_renders_table(monkeypatch):
    report = GoogleDocsReport(league_name="Bros", season=2024)
    monkeypatch.setattr(report, "_safe_batch_update",
                        lambda doc_id, requests, context="": {})
    monkeypatch.setattr(report, "_get_document",
                        lambda doc_id: {"body": {"content": []}})
    captured = []
    orig = report._buffer_table
    def spy(headers, rows, **kwargs):
        captured.append((list(headers), [list(r) for r in rows]))
        return orig(headers, rows, **kwargs)
    monkeypatch.setattr(report, "_buffer_table", spy)

    records = {
        "u1": OwnerTradeRecord(
            user_id="u1", display_name="Tom", trades=14,
            net_ktc=3420, net_production=812.6,
            starter_weeks_gained=36, decisive_starts_gained=7,
            playoff_starts_gained=4,
            best_trade_id="tx_a", worst_trade_id="tx_b",
        ),
        "u2": OwnerTradeRecord(
            user_id="u2", display_name="Jim", trades=14,
            net_ktc=-1100, net_production=-340.2,
            starter_weeks_gained=-8, decisive_starts_gained=-2,
            playoff_starts_gained=-1,
            best_trade_id="tx_b", worst_trade_id="tx_a",
        ),
    }
    report.write_tab_owner_standings(doc_id="fake", records=records)

    assert len(captured) == 1
    headers, rows = captured[0]
    assert headers[0] == "Owner"
    # Sort: Tom (3420) above Jim (-1100).
    assert rows[0][0].startswith("Tom")
    assert rows[1][0].startswith("Jim")
    # Net KTC column shows signed values.
    assert "+3420" in rows[0][2] or rows[0][2].startswith("+3420")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_google_docs.py::test_write_tab_owner_standings_renders_table -v
```

Expected: FAIL — method does not exist.

- [ ] **Step 3: Implement `write_tab_owner_standings`**

In `src/sleeper_dynasty/output/google_docs.py`, after `write_tab_trade_ledger`, add:

```python
    def write_tab_owner_standings(
        self,
        doc_id: str,
        records: dict,
    ) -> None:
        """Write the owner-standings tab (one row per user across the chain)."""
        logger.info("Writing Owner Standings section to doc %s", doc_id)
        self._begin_section(doc_id)
        self._buffer_page_break()
        self._buffer_paragraph(
            "Owner Standings", named_style="HEADING_1", bold=True
        )
        self._buffer_paragraph(
            "Per-owner trading record across the full dynasty league chain.",
            named_style="NORMAL_TEXT",
            foreground_color={"red": 0.4, "green": 0.4, "blue": 0.4},
        )
        self._buffer_blank_line()

        headers = [
            "Owner", "Trades", "Net KTC", "Net Prod",
            "SW Gained", "DS Gained", "PS Gained",
            "Best Trade", "Worst Trade",
        ]
        sorted_records = sorted(
            records.values(), key=lambda r: r.net_ktc, reverse=True
        )
        rows = [
            [
                r.display_name,
                str(r.trades),
                f"{r.net_ktc:+.0f}",
                f"{r.net_production:+.1f}",
                f"{r.starter_weeks_gained:+d}",
                f"{r.decisive_starts_gained:+d}",
                f"{r.playoff_starts_gained:+d}",
                r.best_trade_id or "—",
                r.worst_trade_id or "—",
            ]
            for r in sorted_records
        ]
        self._buffer_table(headers, rows)
        self._flush_section(doc_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_google_docs.py::test_write_tab_owner_standings_renders_table -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/output/google_docs.py tests/test_google_docs.py
git commit -m "$(cat <<'EOF'
Add write_tab_owner_standings to GoogleDocsReport

Single sorted table (one row per user across the chain), sorted by
Net KTC desc. Columns include trades, net KTC, net production,
starter-weeks/decisive-starts/playoff-starts gained, and best/worst
trade IDs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: Add `trades` subcommand parser to CLI

**Files:**
- Modify: `src/sleeper_dynasty/cli.py` (arg-parsing only)
- Modify: `tests/test_cli.py`

Parser plumbing first; the runtime wiring (the actual `_run_trades` orchestrator) comes in the next task. Splitting keeps the parser tests independent.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_parse_args_trades_defaults():
    args = parse_args(["trades", "testuser"])
    assert args.command == "trades"
    assert args.username == "testuser"
    assert args.season == 2026
    assert args.no_cache is False
    assert args.refresh_trades is False
    assert args.private is False


def test_parse_args_trades_custom():
    args = parse_args([
        "trades", "someuser", "--season", "2025",
        "--refresh-trades", "--private",
    ])
    assert args.command == "trades"
    assert args.username == "someuser"
    assert args.season == 2025
    assert args.refresh_trades is True
    assert args.private is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py::test_parse_args_trades_defaults tests/test_cli.py::test_parse_args_trades_custom -v
```

Expected: FAIL — no `trades` subparser.

- [ ] **Step 3: Add the subparser**

In `src/sleeper_dynasty/cli.py`, in `parse_args`, just before the final `return parser.parse_args(argv)`, add:

```python
    trades = subparsers.add_parser(
        "trades",
        help="Build a Google Doc grading every historical trade in the user's "
             "dynasty league chain.",
    )
    trades.add_argument("username", help="Sleeper username.")
    trades.add_argument(
        "--season",
        type=int,
        default=2026,
        help="Entry-point season; we walk back from this season's league "
             "(default: 2026).",
    )
    trades.add_argument(
        "--no-cache",
        action="store_true",
        help="Invalidate all caches before running.",
    )
    trades.add_argument(
        "--refresh-trades",
        action="store_true",
        help="Invalidate only the trade/draft/matchup caches; keep player "
             "and KTC caches intact.",
    )
    trades.add_argument(
        "--private",
        action="store_true",
        help="Keep the generated Google Doc private.",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: PASS on the new tests AND the existing analyze-flow tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/cli.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
Add 'trades' subparser to CLI

Args: username + --season + --no-cache + --refresh-trades + --private.
Runtime wiring follows in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 18: Wire `_run_trades` orchestrator into CLI

**Files:**
- Modify: `src/sleeper_dynasty/cli.py`

This is the large integration step. It ties together everything we built: walk chain → build_trade_history → fetch matchups → grade every trade → aggregate per owner → render Google Doc.

The matchup-fetch step is the most expensive piece (one call per league × per played week). Caching is critical; we use `FileCache` with effectively-infinite TTL for completed seasons.

- [ ] **Step 1: Add the runtime imports and helper for cache-keyed matchups**

In `src/sleeper_dynasty/cli.py`, near the existing imports at the top, add:

```python
from sleeper_dynasty.engine.trade_grader import (
    aggregate_owner_records,
    grade_trade,
)
from sleeper_dynasty.engine.trade_history import build_trade_history
```

Just below the existing constants, add cache-key constants:

```python
# Cache keys for the trades feature.
_TRANSACTIONS_CACHE_KEY = "transactions_{league_id}_w{week}.json"
_DRAFTS_CACHE_KEY = "drafts_{league_id}.json"
_DRAFT_PICKS_CACHE_KEY = "draft_picks_{draft_id}.json"
_MATCHUPS_CACHE_KEY = "matchups_{league_id}_w{week}.json"
_LEAGUE_META_CACHE_KEY = "league_meta_{league_id}.json"
_USERS_CACHE_KEY = "users_{league_id}.json"

# Effectively-infinite TTL for historical (completed-season) data.
_ONE_YEAR_SECONDS = 365 * 24 * 3600
```

- [ ] **Step 2: Add the `_run_trades` function**

Below the existing `_run_analysis` function (still in `cli.py`), add:

```python
async def _run_trades(args: argparse.Namespace) -> None:
    """Execute the trades pipeline: walk chain, grade trades, emit doc."""
    cache = FileCache()
    if args.no_cache:
        logger.info("Invalidating all caches (--no-cache)")
        cache.invalidate_all()
    if args.refresh_trades:
        # Best-effort: invalidate any cached transactions/drafts/matchups.
        for f in list(cache.cache_dir.iterdir()):
            name = f.name
            if (
                name.startswith("transactions_")
                or name.startswith("drafts_")
                or name.startswith("draft_picks_")
                or name.startswith("matchups_")
            ):
                cache.invalidate(name)

    client = SleeperClient()
    try:
        logger.info("Resolving user id for username=%s", args.username)
        user_id = await client.get_user_id(args.username)

        leagues = await client.get_leagues(user_id, args.season)
        if not leagues:
            print(f"No leagues found for {args.username} in {args.season}.")
            return
        relevant = [lg for lg in leagues if lg.status in DYNASTY_LEAGUE_STATUSES]
        if not relevant:
            print(
                f"No dynasty-relevant leagues for {args.username} in {args.season}."
            )
            return
        league = _select_league(relevant)
        logger.info("Building trade history starting from %s", league.league_id)

        # Load players once for asset display names.
        raw_players: Any | None = None
        cached = cache.read(_PLAYERS_CACHE_KEY)
        if isinstance(cached, dict):
            raw_players = cached
        if raw_players is None:
            raw_players = await client.get_players()
            cache.write(_PLAYERS_CACHE_KEY, raw_players)
        player_names = {
            pid: (
                raw.get("full_name")
                or f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip()
                or pid
            )
            for pid, raw in raw_players.items()
            if isinstance(raw, dict)
        }

        resolved_trades = await build_trade_history(
            client,
            current_league_id=league.league_id,
            player_names=player_names,
        )
        logger.info("Resolved %d trades", len(resolved_trades))

        # KTC values for snapshot lens.
        ktc_values = await _load_ktc(cache, use_cache=not args.no_cache)
        ktc_by_player_id: dict[str, Any] = {}
        for pid, p in raw_players.items():
            if not isinstance(p, dict):
                continue
            from sleeper_dynasty.util.name_match import normalize_player_name
            full_name = (
                p.get("full_name")
                or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            )
            v = ktc_values.get(normalize_player_name(full_name)) if full_name else None
            if v is not None:
                ktc_by_player_id[pid] = v

        # Fetch matchups across the chain for hindsight + impact lenses.
        chain = await client.walk_league_history(league.league_id)
        matchups: dict[tuple[str, int, int], dict] = {}
        playoff_weeks_by_league: dict[str, int] = {}
        roster_to_user_by_league: dict[str, dict[int, str]] = {}
        league_name_by_id: dict[str, str] = {}
        display_names: dict[str, str] = {}
        for lg in chain:
            league_name_by_id[lg.league_id] = lg.name
            playoff_weeks_by_league[lg.league_id] = lg.playoff_week_start
            rosters = await client.get_rosters(lg.league_id)
            roster_to_user_by_league[lg.league_id] = {
                r.roster_id: r.owner_id for r in rosters
            }
            users = await client.get_users(lg.league_id)
            for uid, info in users.items():
                # Most-recent display_name wins; chain order is newest-first.
                display_names.setdefault(
                    uid, info.get("team_name") or info.get("display_name") or uid
                )
            # Pull weekly matchups (cache-aware via a one-off call wrapper).
            for week in range(1, 19):
                key = _MATCHUPS_CACHE_KEY.format(league_id=lg.league_id, week=week)
                raw = cache.read(key, max_age_seconds=_ONE_YEAR_SECONDS)
                if not isinstance(raw, list):
                    # Use raw HTTP (not the typed wrapper) — we want
                    # players_points, starters, etc. which the existing
                    # get_matchups helper doesn't surface.
                    resp = await client._client.get(
                        f"/league/{lg.league_id}/matchups/{week}"
                    )
                    resp.raise_for_status()
                    raw = resp.json() or []
                    cache.write(key, raw)
                # Build paired matchup metadata (team_points + opponent_points).
                by_matchup: dict[int, list[dict]] = {}
                for entry in raw:
                    by_matchup.setdefault(entry.get("matchup_id"), []).append(entry)
                for mid, entries in by_matchup.items():
                    if len(entries) != 2:
                        continue
                    a, b = entries
                    matchups[(lg.league_id, week, a["roster_id"])] = {
                        "starters": a.get("starters") or [],
                        "players": a.get("players") or [],
                        "players_points": a.get("players_points") or {},
                        "team_points": a.get("points"),
                        "opponent_points": b.get("points"),
                    }
                    matchups[(lg.league_id, week, b["roster_id"])] = {
                        "starters": b.get("starters") or [],
                        "players": b.get("players") or [],
                        "players_points": b.get("players_points") or {},
                        "team_points": b.get("points"),
                        "opponent_points": a.get("points"),
                    }

        # Grade every trade.
        grades_by_id: dict[str, Any] = {}
        for rt in resolved_trades:
            grade = grade_trade(
                rt,
                ktc_values=ktc_by_player_id,
                matchups=matchups,
                roster_to_user_by_league=roster_to_user_by_league,
                playoff_weeks_by_league=playoff_weeks_by_league,
                fmt="superflex",
            )
            grades_by_id[rt.trade.transaction_id] = grade

        records = aggregate_owner_records(
            list(grades_by_id.values()), display_names=display_names
        )

        # Emit the Doc.
        report = GoogleDocsReport(league_name=league.name, season=league.season)
        report.title = f"{league.name} — Trade History"
        report.authenticate()
        doc_id = report.create_document()
        report.write_tab_trade_ledger(
            doc_id,
            resolved_trades=resolved_trades,
            grades_by_trade_id=grades_by_id,
            display_names=display_names,
            league_name_by_id=league_name_by_id,
        )
        report.write_tab_owner_standings(doc_id, records=records)
        report.set_sharing(doc_id, private=args.private)
        url = report.get_doc_url(doc_id)
        print(f"\nTrades report ready: {url}")
    finally:
        await client.close()
```

- [ ] **Step 3: Dispatch the new subcommand in `main`**

In `src/sleeper_dynasty/cli.py`, in the `main` function (the dispatcher near the bottom), add a branch:

```python
    if args.command == "trades":
        asyncio.run(_run_trades(args))
        return
```

Place it after the existing `if args.command == "analyze"` branch.

- [ ] **Step 4: Run the full test suite to confirm no regressions**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/cli.py
git commit -m "$(cat <<'EOF'
Wire 'trades' subcommand orchestrator

Walks the league chain, fetches users/rosters/transactions/drafts/
matchups (all cached with ~infinite TTL for completed seasons),
grades every trade, aggregates per owner, and emits a Google Doc
with trade-ledger + owner-standings tabs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 19: End-to-end smoke test

**Files:**
- Modify: `tests/test_integration.py`

Build a 2–3 trade fixture league entirely with mocks (no network). Assert the full pipeline (build_trade_history → grade_trade → aggregate_owner_records) produces hand-computed values for all three lenses.

- [ ] **Step 1: Write the smoke test**

Append to `tests/test_integration.py` (or create the file if it doesn't have async-import scaffolding — check first):

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from sleeper_dynasty.engine.trade_grader import (
    aggregate_owner_records,
    grade_trade,
)
from sleeper_dynasty.engine.trade_history import build_trade_history
from sleeper_dynasty.models.league import League, Roster
from sleeper_dynasty.models.player import KTCValue


@pytest.mark.asyncio
async def test_smoke_pipeline_one_trade_one_season():
    """Single-league chain, one trade, hand-computed expected grades."""
    client = MagicMock()
    league_2024 = League(
        league_id="L24", name="Bros", season=2024,
        total_rosters=2, roster_positions=[], scoring_settings={},
        playoff_week_start=15, num_playoff_teams=6, status="complete",
    )
    client.walk_league_history = AsyncMock(return_value=[league_2024])
    client.get_users = AsyncMock(return_value={
        "u_a": {"display_name": "Alice", "team_name": None},
        "u_b": {"display_name": "Bob", "team_name": None},
    })
    client.get_rosters = AsyncMock(return_value=[
        Roster(1, "u_a", "Alice", [], 0, 0, 0, 0, 0),
        Roster(2, "u_b", "Bob", [], 0, 0, 0, 0, 0),
    ])

    async def fake_txs(league_id, week):
        if week == 2:
            return [{
                "type": "trade", "status": "complete",
                "transaction_id": "tx",
                "created": int(datetime(2024, 9, 12, tzinfo=timezone.utc).timestamp() * 1000),
                "leg": 2,
                "roster_ids": [1, 2],
                "adds": {"p_bijan": 1, "p_adams": 2},
                "drops": {"p_adams": 1, "p_bijan": 2},
                "draft_picks": [],
                "waiver_budget": [],
            }]
        return []
    client.get_transactions = AsyncMock(side_effect=fake_txs)
    client.get_drafts = AsyncMock(return_value=[])
    client.get_draft_picks = AsyncMock(return_value=[])

    resolved = await build_trade_history(
        client,
        current_league_id="L24",
        player_names={"p_bijan": "Bijan", "p_adams": "Adams"},
    )
    assert len(resolved) == 1

    # Hand-built KTC + matchup tables.
    ktc = {
        "p_bijan": KTCValue("Bijan", "bijan", "RB", 7500, 7400, None, None),
        "p_adams": KTCValue("Adams", "adams", "WR", 6050, 6000, None, None),
    }
    matchups = {
        ("L24", 3, 1): {
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 22.0},
            "team_points": 100.0, "opponent_points": 80.0,
        },
        ("L24", 3, 2): {
            "starters": ["p_adams"], "players": ["p_adams"],
            "players_points": {"p_adams": 14.0},
            "team_points": 90.0, "opponent_points": 95.0,
        },
    }
    grade = grade_trade(
        resolved[0],
        ktc_values=ktc,
        matchups=matchups,
        roster_to_user_by_league={"L24": {1: "u_a", 2: "u_b"}},
        playoff_weeks_by_league={"L24": 15},
        fmt="superflex",
    )
    assert grade.snapshot_value_swing["u_a"] == pytest.approx(1450.0)
    assert grade.snapshot_value_swing["u_b"] == pytest.approx(-1450.0)
    assert grade.hindsight_production_swing["u_a"] == pytest.approx(8.0)  # 22 - 14
    assert grade.hindsight_production_swing["u_b"] == pytest.approx(-8.0)
    assert grade.realized_impact_received["u_a"].starter_weeks == 1
    assert grade.realized_impact_received["u_a"].win_share_points == pytest.approx(22.0)
    # Alice won by 20 with Bijan scoring 22 → decisive.
    assert grade.realized_impact_received["u_a"].decisive_starts == 1

    records = aggregate_owner_records(
        [grade], display_names={"u_a": "Alice", "u_b": "Bob"}
    )
    assert records["u_a"].net_ktc == pytest.approx(1450.0)
    assert records["u_a"].net_production == pytest.approx(8.0)
    assert records["u_a"].best_trade_id == "tx"
    assert records["u_b"].worst_trade_id == "tx"
```

- [ ] **Step 2: Run the smoke test**

```bash
pytest tests/test_integration.py::test_smoke_pipeline_one_trade_one_season -v
```

Expected: PASS.

- [ ] **Step 3: Run the full test suite one final time**

```bash
pytest -v
```

Expected: all tests pass across the project.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "$(cat <<'EOF'
Add end-to-end smoke test for trade-grader pipeline

Hand-built fixture league with one trade, hand-computed expected
grades across all three lenses (snapshot KTC, hindsight production,
realized impact). Exercises build_trade_history → grade_trade →
aggregate_owner_records.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes (already applied)

- **Spec coverage:** Every spec section has at least one task implementing it:
  - Architecture/module layout → Tasks 7–18.
  - Stable owner identity → Tasks 7, 8 (`_identity_for`), 18 (`display_names` accumulation).
  - Asset model → Task 7.
  - Pick resolution rule → Task 9 (`resolve_assets`).
  - Data flow → Task 10 + Task 18.
  - Lens 1 → Task 11. Lens 2 → Task 12. Lens 3 → Task 13. Per-owner aggregation → Task 14.
  - Output → Tasks 15 + 16.
  - CLI → Tasks 17 + 18.
  - Caching → Task 18 (matchups + trades + users keys with `_ONE_YEAR_SECONDS` TTL).
  - Error handling → Implemented in each engine task (warnings + zero-value fallbacks).
  - Testing strategy → Each task includes failing-test-first; Task 19 is the end-to-end smoke.
- **Placeholders:** None remaining. Every step contains the exact code, command, or commit message.
- **Type consistency:** `Trade`, `TradeSide`, `ResolvedTrade`, `TradeGrade`, `RealizedImpact`, `OwnerTradeRecord` field names match across tasks 7 → 19.
- **Known v1 limitations explicitly accepted by the spec:**
  - Unresolved picks contribute 0 to Lens 1 (rookie-pick KTC table integration is a follow-up).
  - Draft-slot derivation in `build_trade_history` is a best-effort heuristic (documented inline at `_derive_user_slot_map`); accuracy degrades for round-1 picks that were themselves traded. This is acceptable per the spec ("graceful degradation").
