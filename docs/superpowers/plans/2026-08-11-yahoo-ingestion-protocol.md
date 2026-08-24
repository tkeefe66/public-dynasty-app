# Yahoo Ingestion Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read a real Yahoo redraft/keeper league end-to-end through the existing engine — chain, rosters, matchups, playoff phases, trades, draft results — behind one ingestion protocol that Sleeper also implements.

**Architecture:** A `LeaguePlatform` protocol defines every read the grader needs. `SleeperClient` is refactored to satisfy it with zero behavior change, then `YahooAdapter` is added as the second implementation. Platform routing is derived from the league id's shape (Sleeper ids are all digits; Yahoo league keys look like `461.l.123456`), so no cache file, membership row, or URL changes. Yahoo player ids are mapped to Sleeper ids at the adapter boundary, keeping Sleeper ID canonical everywhere inside.

**Tech Stack:** Python 3.11 / httpx / dataclasses / pytest. No frontend work in this plan.

## Scope

**In:** the ingestion protocol, the Sleeper refactor, the Yahoo read adapter, Yahoo→Sleeper player id mapping, and an end-to-end read of a real Yahoo league using a hand-supplied developer access token.

**Out — deferred to Plan 2 (the auth half):** OAuth authorization-code flow, the `yahoo_connection` record, Fernet token encryption, background/scheduled refresh of Yahoo leagues, the *stale — reconnect* UI state, and league discovery for Yahoo in `routes/me.py`. This plan deliberately stops at "a developer with a pasted token can grade a Yahoo league," because Plan 2's shape should be informed by a working adapter.

## Blocker: Yahoo Fantasy API access is separately gated (2026-08-11)

**Tasks 6–9 cannot start until Yahoo grants Fantasy API access.** Registering an
app at `developer.yahoo.com/apps/create` is *not* sufficient — Fantasy Sports is
a restricted API requiring a separate application at
<https://sports.yahoo.com/developer/access/>. Submitted 2026-08-11; approval
time unknown.

How it presents, so nobody re-diagnoses it:

- The app-creation form offers **no Fantasy Sports permission checkbox** — only
  OpenID Connect and TW Auction. Every older tutorial says to tick one. They
  predate the gate.
- Requesting the documented fantasy scope fails at the authorize step with
  `?error=invalid_scope&error_description=invalid+scope`. Omitting the scope
  parameter lets authorization succeed and issues a perfectly valid token.
- That valid token then 401s on **every** fantasy endpoint with
  `oauth_problem="additional_authorization_required"` — including `/game/nfl`,
  which carries no user data. That last detail is the diagnostic: a scope or
  token problem would not fail a public metadata endpoint. It is an
  app-entitlement failure.

The token-minting and fixture-recording scripts are written and working; they
were verified as far as the entitlement allows. Resume at Task 5 Step 1 the day
access is granted.

## Two corrections to the design spec

Both were found while researching this plan. They are recorded here because the spec (`docs/superpowers/specs/2026-08-11-yahoo-adapter-design.md`) is wrong on each, and an implementer reading the spec alone would build to the wrong facts.

**1. Yahoo access tokens last one hour, not six minutes.** The spec's central claim — "Yahoo access tokens expire after **6 minutes**" — does not match Yahoo's documented token response, which advertises `"expires_in":3600`. This does not change the decision to store refresh tokens (unattended refresh needs one at any TTL), but it does mean a single access token comfortably covers one refresh run and an entire browsing session. Do not build token-refresh machinery that assumes a 6-minute ceiling.

**2. The capability model *does* have a Sleeper-specific branch today, exactly where the handoff predicted.** `League.league_type: int | None` is a raw Sleeper `settings.type` (0/1/2) sitting on the supposedly platform-neutral domain model, and `derive_capabilities` reads it via `format_for_type`. Yahoo has no such integer. Per the handoff's instruction — *"If describing a Yahoo league needs a Yahoo-specific branch in it, the capability model was drawn wrong — fix it there rather than special-casing"* — Task 1 moves the model to a neutral `League.format` string and makes the int-to-format mapping a Sleeper adapter detail. This is the single most important task in the plan and everything else depends on it.

## Global Constraints

- **`format` values are exactly** `"dynasty" | "keeper" | "redraft"`.
- **Weight-tree names are exactly** `"results_led" | "redraft_led" | "keeper_led"`. This plan adds no tree — a Yahoo league routes to an existing one.
- **Yahoo is redraft/keeper only.** No dynasty support on Yahoo; it cannot trade future picks.
- **Sleeper player_id stays the internal canonical key.** Yahoo ids are translated at the adapter boundary and never reach the engine, the chain cache, or lineage.
- **Leagues are self-contained.** Nothing pooled, compared, ranked, or averaged across leagues or across platforms.
- **Never render "KTC"** anywhere in `web/`. `web/tests/agate-rules.test.ts` enforces this.
- **No `SCHEMA_VERSION` bump in this plan.** No new field is persisted on `ChainCacheEntry`. If a task appears to need one, stop and run the `chain-cache-field` skill before proceeding.
- **Never fall back to dynasty values** to fill gaps in a redraft value set.
- Backend tests: `pytest tests/` (engine) and `pytest api/tests/` (API) — **never bare `pytest` from root**, it breaks on the duplicate `tests` package name.
- Frontend tests: `cd web && npx vitest --config tests/vitest.config.ts run` — **never bare `npx vitest run`**.
- Explicit-path `git add` — never `git add -A`. Another session's worktree shares this repo.
- A `Skill candidate: <name> - <desc>` or `Skill candidate: none.` line immediately before every commit.
- Current green baseline: **engine 527, api 484, frontend 329, tsc clean.** Every task must leave it green or higher.

## File Structure

| File | Responsibility |
|---|---|
| `src/sleeper_dynasty/models/league.py` | *(modify)* `League.format: str` replaces `League.league_type: int \| None` |
| `src/sleeper_dynasty/api/platform.py` | *(create)* the `LeaguePlatform` protocol + `platform_for_league_id` routing |
| `src/sleeper_dynasty/api/sleeper.py` | *(modify)* satisfies the protocol; owns the Sleeper `settings.type` → format mapping |
| `src/sleeper_dynasty/api/yahoo_ids.py` | *(create)* `yahoo_id` → `sleeper_id` map from `db_playerids.csv` |
| `src/sleeper_dynasty/api/yahoo_json.py` | *(create)* Yahoo's XML-shaped JSON → plain dicts/lists |
| `src/sleeper_dynasty/api/yahoo.py` | *(create)* `YahooAdapter` — the second protocol implementation |
| `src/sleeper_dynasty/engine/capabilities.py` | *(modify)* reads `league.format`; `format_for_type` moves out |
| `api/app/services/grader_io.py` | *(modify)* drops the `client._client` reach-through |
| `api/app/routes/me.py` | *(modify)* uses the adapter's format directly |

---

### Task 1: Platform-neutral `League.format`

The capability-model fix. `League.league_type` is a raw Sleeper integer on a model the spec calls platform-neutral; every downstream format decision reads it. Replace it with the vocabulary the app already speaks, and push the int mapping down into the Sleeper adapter where it belongs.

**Files:**
- Modify: `src/sleeper_dynasty/models/league.py:18`
- Modify: `src/sleeper_dynasty/api/sleeper.py:56,224`
- Modify: `src/sleeper_dynasty/engine/capabilities.py:25-38,71`
- Modify: `api/app/services/grader_io.py:29-41`
- Modify: `api/app/routes/me.py:32-33,70`
- Test: `tests/test_league_format.py`

**Interfaces:**
- Produces: `League.format: str` (defaults `"dynasty"`), and `sleeper_dynasty.api.sleeper.format_for_type(league_type) -> str`. `engine.capabilities.format_for_type` is **removed** — `derive_capabilities` reads `league.format` directly.
- Consumed by: every later task. Task 6 populates `League.format` for Yahoo from keeper settings.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_league_format.py`:

```python
from sleeper_dynasty.api.sleeper import format_for_type
from sleeper_dynasty.engine.capabilities import derive_capabilities
from sleeper_dynasty.models.league import League


def _league(fmt="dynasty"):
    return League(
        league_id="L1", name="Test", season=2025, total_rosters=12,
        roster_positions=["QB"], scoring_settings={}, playoff_week_start=15,
        num_playoff_teams=6, status="in_season", format=fmt,
    )


def test_league_defaults_to_dynasty_format():
    """An adapter that forgets to set format must not demote a league."""
    lg = League(
        league_id="L1", name="Test", season=2025, total_rosters=12,
        roster_positions=["QB"], scoring_settings={}, playoff_week_start=15,
        num_playoff_teams=6, status="in_season",
    )
    assert lg.format == "dynasty"


def test_league_has_no_platform_specific_type_field():
    """The Sleeper settings.type int must not live on the neutral model."""
    assert not hasattr(_league(), "league_type")


def test_capabilities_read_format_off_the_league():
    for fmt in ("dynasty", "keeper", "redraft"):
        assert derive_capabilities(
            _league(fmt), chain_length=1, observed_pick_assets=False
        ).format == fmt


def test_capabilities_need_no_platform_knowledge():
    """Any object with a .format string must work — that is the portability
    contract. A Yahoo league is described by the same call."""

    class NotASleeperLeague:
        format = "keeper"

    caps = derive_capabilities(
        NotASleeperLeague(), chain_length=2, observed_pick_assets=False)
    assert caps.format == "keeper"
    assert caps.roster_continuity is True
    assert caps.multiyear_history is True


def test_sleeper_owns_the_type_mapping():
    assert format_for_type(0) == "redraft"
    assert format_for_type(1) == "keeper"
    assert format_for_type(2) == "dynasty"


def test_unknown_sleeper_type_defaults_to_dynasty():
    for bad in (None, 7, -1):
        assert format_for_type(bad) == "dynasty"


def test_capabilities_module_no_longer_exports_format_for_type():
    """The mapping is a Sleeper detail; leaving a copy in the engine invites
    drift the moment a second platform exists."""
    import sleeper_dynasty.engine.capabilities as caps
    assert not hasattr(caps, "format_for_type")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_league_format.py -v`
Expected: FAIL — `TypeError: League.__init__() got an unexpected keyword argument 'format'`

- [ ] **Step 3: Change the domain model**

In `src/sleeper_dynasty/models/league.py`, replace line 18:

```python
    league_type: int | None = None  # Sleeper settings.type: 0=redraft, 1=keeper, 2=dynasty
```

with:

```python
    # "dynasty" | "keeper" | "redraft". Platform-neutral by design: each
    # adapter maps its own native representation (Sleeper's settings.type
    # int, Yahoo's keeper settings) onto this vocabulary, so the engine never
    # learns a platform's encoding. Defaults to dynasty — this app was
    # dynasty-only until recently and an adapter that omits it must never
    # silently demote a league.
    format: str = "dynasty"
```

- [ ] **Step 4: Move the type mapping into the Sleeper adapter**

In `src/sleeper_dynasty/api/sleeper.py`, add at module level (below `AVATAR_THUMB_BASE`):

```python
# Sleeper settings.type -> the app's format vocabulary. This is a Sleeper
# encoding and lives with the Sleeper adapter; the engine reads League.format.
_TYPE_TO_FORMAT = {0: "redraft", 1: "keeper", 2: "dynasty"}


def format_for_type(league_type) -> str:
    """Sleeper ``settings.type`` -> "dynasty" | "keeper" | "redraft".

    Anything unrecognized (``None``, an unknown int) is dynasty: an unknown
    value must never silently demote an existing league.
    """
    return _TYPE_TO_FORMAT.get(league_type, "dynasty")
```

Then at **both** `League(...)` constructions (line 56 in `get_leagues` and line 224 in `get_league`), replace:

```python
                league_type=settings.get("type"),
```

with:

```python
                format=format_for_type(settings.get("type")),
```

(Note the indentation differs between the two call sites — match the surrounding block.)

- [ ] **Step 5: Simplify the capability module**

In `src/sleeper_dynasty/engine/capabilities.py`, delete the `_TYPE_TO_FORMAT` constant and the whole `format_for_type` function (lines 17-19 and 25-38). Replace the `fmt = ...` line inside `derive_capabilities` (line 71):

```python
    fmt = format_for_type(league.league_type)
```

with:

```python
    fmt = getattr(league, "format", None) or _DEFAULT_FORMAT
```

Update the module docstring's second paragraph to read:

```python
"""What a league supports, derived from its format plus observed evidence.

Pure — no I/O, no platform knowledge. The format comes off the league itself
(each adapter maps its own encoding onto the shared vocabulary); the three
booleans come from what the data actually shows rather than what the declared
format implies, so a dynasty league with pick trading disabled reports no
future picks and a first-season dynasty league reports no multiyear history.
That is what makes this portable: a non-Sleeper league is described by asking
the same questions of its data, with no branch for where it came from.
"""
```

- [ ] **Step 6: Update the two remaining readers**

In `api/app/services/grader_io.py`, replace the `format_for_type` import (line 17) — delete it — and rewrite `is_redraft_chain` (lines 29-41):

```python
def is_redraft_chain(chain) -> bool:
    """Is this league redraft *now*? Judged by the latest season in the chain,
    so a league that converted formats is priced by where it currently is.
    An empty chain is never redraft — never demote without positive evidence.

    Reads ``League.format``, which every adapter populates, so this is
    platform-agnostic: a Yahoo redraft league prices the same way.
    """
    if not chain:
        return False
    latest = max(chain, key=lambda lg: lg.season)
    return getattr(latest, "format", "dynasty") == "redraft"
```

In `api/app/routes/me.py`, delete the `_TYPE_TO_FORMAT` constant and `_format_for_type` helper (lines 32-33 and the function beneath), and change line 70 from:

```python
                "format": _format_for_type(lg.league_type),
```

to:

```python
                "format": lg.format,
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_league_format.py -v`
Expected: PASS — 7 passed

- [ ] **Step 8: Fix the existing tests that construct `League(league_type=...)`**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && grep -rn "league_type" tests/ api/tests/`

Every hit is a test constructing a `League` with the old kwarg or importing the removed `engine.capabilities.format_for_type`. Rewrite each: `league_type=0` → `format="redraft"`, `league_type=1` → `format="keeper"`, `league_type=2` → `format="dynasty"`, and `league_type=None`/garbage → `format="dynasty"`. Tests that specifically asserted "an unknown int defaults to dynasty" now belong to `format_for_type` and are already covered by `tests/test_league_format.py` — delete the duplicates rather than porting them.

- [ ] **Step 9: Run the full backend suites**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/ -q && pytest api/tests/ -q`
Expected: PASS — no failures.

- [ ] **Step 10: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/models/league.py src/sleeper_dynasty/api/sleeper.py src/sleeper_dynasty/engine/capabilities.py api/app/services/grader_io.py api/app/routes/me.py tests/ api/tests/
git commit -m "refactor: platform-neutral League.format replaces Sleeper's league_type int"
```

---

### Task 2: The ingestion protocol and platform routing

**Files:**
- Create: `src/sleeper_dynasty/api/platform.py`
- Test: `tests/test_platform_protocol.py`

**Interfaces:**
- Produces: `LeaguePlatform` (a `typing.Protocol`, runtime-checkable), `platform_for_league_id(league_id) -> str` returning `"sleeper"` or `"yahoo"`, and `PhaseMap = dict[tuple[int, int], str]`.
- Consumed by: Task 3 (Sleeper conforms), Tasks 6-8 (Yahoo conforms), Task 9 (routing).

**Why routing by id shape rather than a stored column:** Sleeper league ids are all digits (`"1048178156025733120"`); Yahoo league keys are `{game_key}.l.{league_id}` (`"461.l.123456"`). The shapes are disjoint, so the platform is derivable from the id already stored in every membership row, every `chain_<id>.json` filename, and every URL. A stored discriminator would mean a migration, a cache-key change, and a second source of truth that can disagree with the id it sits beside.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_platform_protocol.py`:

```python
import pytest

from sleeper_dynasty.api.platform import (
    LeaguePlatform, PLATFORM_SLEEPER, PLATFORM_YAHOO, platform_for_league_id,
)


def test_all_digit_ids_are_sleeper():
    assert platform_for_league_id("1048178156025733120") == PLATFORM_SLEEPER
    assert platform_for_league_id("123") == PLATFORM_SLEEPER


def test_yahoo_league_keys_are_yahoo():
    assert platform_for_league_id("461.l.123456") == PLATFORM_YAHOO
    assert platform_for_league_id("nfl.l.98765") == PLATFORM_YAHOO


def test_routing_is_case_insensitive_and_whitespace_tolerant():
    assert platform_for_league_id("  461.L.123456 ") == PLATFORM_YAHOO


def test_empty_id_is_rejected_loudly():
    """A silent default here would send a Yahoo league to the Sleeper client
    and fail deep inside an HTTP call with an unrelated message."""
    with pytest.raises(ValueError, match="empty league id"):
        platform_for_league_id("")


def test_unrecognized_shape_is_rejected_loudly():
    with pytest.raises(ValueError, match="unrecognized league id"):
        platform_for_league_id("not-a-league")


def test_sleeper_client_satisfies_the_protocol():
    from sleeper_dynasty.api.sleeper import SleeperClient
    assert isinstance(SleeperClient(), LeaguePlatform)


def test_protocol_names_every_read_the_grader_makes():
    """Guard: the protocol is the contract. If the grader learns to call
    something new on its client, it must be added here first."""
    required = {
        "walk_league_history", "get_rosters", "get_users", "get_players",
        "get_raw_matchups", "get_phase_map", "get_trade_transactions",
        "get_drop_transactions", "get_draft_results", "get_traded_picks",
        "get_nfl_state", "get_stats", "close",
    }
    assert required <= set(dir(LeaguePlatform))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_platform_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.api.platform'`

- [ ] **Step 3: Write the protocol**

Create `src/sleeper_dynasty/api/platform.py`:

```python
"""The ingestion contract every fantasy platform implements.

One interface, two implementations (``SleeperClient``, ``YahooAdapter``) —
rather than one client plus a special case. Everything the grader needs to
read is named here; anything not on this protocol is not available to the
engine, which is what keeps a platform's encoding from leaking inward.

Three normalizations are worth calling out because they are where the two
platforms differ most:

* **Phases.** Sleeper publishes winners/losers brackets and the engine derives
  a phase map from them. Yahoo publishes no bracket resource — its scoreboard
  marks each matchup as playoff or consolation directly. So the protocol asks
  for the *phase map*, the thing both can produce, rather than for brackets,
  which only one has.
* **Transactions.** Sleeper returns one mixed feed filtered by ``type``.
  Yahoo has a typed collection. The protocol asks for trades and drops
  separately so neither caller has to know how the other platform slices them.
* **Player ids.** Every ``player_id`` crossing this boundary is a *Sleeper*
  player id, whatever the source platform calls it internally. Sleeper ID is
  the canonical key for KTC, FantasyCalc, nflverse, the chain cache, and
  lineage; translating at the boundary keeps all of them untouched.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

PLATFORM_SLEEPER = "sleeper"
PLATFORM_YAHOO = "yahoo"

# (week, roster_id) -> "playoff" | "toilet". Weeks absent from the map are
# regular season, a bye, or a placement game — see engine/playoff_phase.py.
PhaseMap = dict[tuple[int, int], str]


def platform_for_league_id(league_id: str) -> str:
    """Which platform owns ``league_id``, from the id's shape.

    Sleeper ids are all digits; Yahoo league keys are ``{game_key}.l.{id}``.
    The shapes are disjoint, so the id already stored in every membership row
    and cache filename is its own discriminator — no column, no migration, no
    second source of truth that can disagree with the id beside it.

    Raises ValueError on anything unrecognized rather than defaulting. A
    silent default would hand a Yahoo league to the Sleeper client and surface
    as a confusing 404 deep inside an HTTP call.
    """
    lid = (league_id or "").strip().lower()
    if not lid:
        raise ValueError("empty league id")
    if lid.isdigit():
        return PLATFORM_SLEEPER
    if ".l." in lid:
        return PLATFORM_YAHOO
    raise ValueError(f"unrecognized league id shape: {league_id!r}")


@runtime_checkable
class LeaguePlatform(Protocol):
    """Every read the grader performs. See the module docstring."""

    async def walk_league_history(self, league_id: str) -> list:
        """The league chain, newest season first, back to its origin."""
        ...

    async def get_rosters(self, league_id: str) -> list:
        """``Roster`` records for one league-season."""
        ...

    async def get_users(self, league_id: str) -> dict:
        """user_id -> {"display_name", "team_name", "avatar_url"}."""
        ...

    async def get_players(self) -> dict:
        """The player universe, keyed by Sleeper player_id."""
        ...

    async def get_raw_matchups(self, league_id: str, week: int) -> list[dict]:
        """Per-roster rows for one league-week.

        Each row carries ``matchup_id``, ``roster_id``, ``points``,
        ``starters``, ``players``, ``players_points`` — the shape
        ``grader_io._assemble_played_matchups`` consumes. Player ids inside
        ``starters``/``players``/``players_points`` are Sleeper ids.
        """
        ...

    async def get_phase_map(self, league) -> PhaseMap:
        """(week, roster_id) -> "playoff" | "toilet" for one league-season."""
        ...

    async def get_trade_transactions(self, league_id: str) -> list[dict]:
        """Completed trades, normalized to the Sleeper transaction shape that
        ``engine/trade_history.normalize_trade`` consumes: ``transaction_id``,
        ``roster_ids``, ``adds``, ``drops``, ``draft_picks``,
        ``waiver_budget``, ``created`` (epoch ms), ``leg`` (week)."""
        ...

    async def get_drop_transactions(self, league_id: str) -> list[dict]:
        """Non-trade transactions that dropped a player, same shape, used by
        ``engine/trade_history.build_drop_index``."""
        ...

    async def get_draft_results(self, league_id: str) -> list[dict]:
        """One row per pick made: ``round``, ``pick_no``, ``draft_slot``,
        ``roster_id``, ``player_id`` (Sleeper id), ``season``."""
        ...

    async def get_traded_picks(self, league_id: str) -> list:
        """``DraftPick`` records for picks that changed hands. Platforms
        without future-pick trading return []."""
        ...

    async def get_nfl_state(self) -> dict:
        """``{"season": int, "week": int, "season_type": str}``."""
        ...

    async def get_stats(self, season: int, week: int) -> dict:
        """Raw NFL stats for one week keyed by Sleeper player_id."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        ...
```

- [ ] **Step 4: Run the tests**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_platform_protocol.py -v`
Expected: 6 passed, 1 failed — only `test_sleeper_client_satisfies_the_protocol` fails, because `SleeperClient` does not implement the new methods until Task 3.

To keep this task's commit green, mark the Sleeper test as expected-to-fail for now by adding above it:

```python
@pytest.mark.xfail(reason="SleeperClient conforms in Task 3", strict=True)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_platform_protocol.py -v`
Expected: PASS — 6 passed, 1 xfailed

- [ ] **Step 6: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/api/platform.py tests/test_platform_protocol.py
git commit -m "feat: LeaguePlatform ingestion protocol and id-shape platform routing"
```

---

### Task 3: Refactor `SleeperClient` onto the protocol

Zero behavior change. This lands before any Yahoo code exists so a future bisect can tell "the refactor broke it" from "the adapter broke it."

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py`
- Modify: `api/app/services/grader_io.py:161,166-167`
- Modify: `src/sleeper_dynasty/engine/trade_history.py:378-395`
- Test: `tests/test_sleeper_protocol_conformance.py`

**Interfaces:**
- Consumes: `LeaguePlatform`, `PhaseMap` (Task 2).
- Produces: `SleeperClient.get_raw_matchups`, `.get_phase_map`, `.get_trade_transactions`, `.get_drop_transactions`, `.get_draft_results`. The existing `get_transactions`, `get_drafts`, `get_draft_picks`, `get_winners_bracket`, `get_losers_bracket` stay as Sleeper-native helpers the new methods build on — they are not on the protocol.

**The reach-through to fix:** `api/app/services/grader_io.py:161` calls `client._client.get(f"/league/{lg.league_id}/matchups/{week}")` — reaching past the client into its private httpx instance. That line alone makes the protocol unimplementable by anything that is not Sleeper, and it is the reason `get_raw_matchups` exists.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sleeper_protocol_conformance.py`:

```python
import pytest

from sleeper_dynasty.api.platform import LeaguePlatform
from sleeper_dynasty.api.sleeper import SleeperClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeHttp:
    """Records GET paths and replays canned payloads."""

    def __init__(self, routes):
        self.routes = routes
        self.paths = []

    async def get(self, path, **kw):
        self.paths.append(path)
        return _FakeResponse(self.routes.get(path, []))

    async def aclose(self):
        return None


def _client(routes):
    c = SleeperClient()
    c._client = _FakeHttp(routes)
    return c


def test_sleeper_client_satisfies_the_protocol():
    assert isinstance(SleeperClient(), LeaguePlatform)


@pytest.mark.asyncio
async def test_get_raw_matchups_returns_the_weeks_rows():
    rows = [{"matchup_id": 1, "roster_id": 3, "points": 100.5}]
    c = _client({"/league/L1/matchups/4": rows})
    assert await c.get_raw_matchups("L1", 4) == rows


@pytest.mark.asyncio
async def test_get_raw_matchups_normalizes_a_null_body_to_empty():
    """Sleeper returns null for a week that does not exist."""
    c = _client({"/league/L1/matchups/99": None})
    assert await c.get_raw_matchups("L1", 99) == []


@pytest.mark.asyncio
async def test_get_trade_transactions_filters_to_complete_trades():
    txs = [
        {"type": "trade", "status": "complete", "transaction_id": "1"},
        {"type": "trade", "status": "failed", "transaction_id": "2"},
        {"type": "waiver", "status": "complete", "transaction_id": "3",
         "drops": {"4034": 1}},
    ]
    routes = {f"/league/L1/transactions/{w}": (txs if w == 1 else [])
              for w in range(1, 19)}
    c = _client(routes)
    out = await c.get_trade_transactions("L1")
    assert [t["transaction_id"] for t in out] == ["1"]


@pytest.mark.asyncio
async def test_get_drop_transactions_excludes_trades():
    txs = [
        {"type": "trade", "status": "complete", "transaction_id": "1",
         "drops": {"4034": 1}},
        {"type": "waiver", "status": "complete", "transaction_id": "3",
         "drops": {"5000": 2}},
        {"type": "waiver", "status": "complete", "transaction_id": "4"},
    ]
    routes = {f"/league/L1/transactions/{w}": (txs if w == 1 else [])
              for w in range(1, 19)}
    c = _client(routes)
    out = await c.get_drop_transactions("L1")
    assert [t["transaction_id"] for t in out] == ["3"]


@pytest.mark.asyncio
async def test_get_phase_map_derives_from_the_brackets():
    class _Lg:
        league_id = "L1"
        playoff_week_start = 15
        playoff_round_type = 0

    routes = {
        "/league/L1/winners_bracket": [{"r": 1, "t1": 1, "t2": 2}],
        "/league/L1/losers_bracket": [{"r": 1, "t1": 5, "t2": 6}],
    }
    phases = await _client(routes).get_phase_map(_Lg())
    assert phases[(15, 1)] == "playoff"
    assert phases[(15, 6)] == "toilet"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_sleeper_protocol_conformance.py -v`
Expected: FAIL — `AttributeError: 'SleeperClient' object has no attribute 'get_raw_matchups'`

- [ ] **Step 3: Add the protocol methods to `SleeperClient`**

In `src/sleeper_dynasty/api/sleeper.py`, add these methods to the class (place them after `get_transactions`, keeping the Sleeper-native helpers they build on adjacent):

```python
    async def get_raw_matchups(self, league_id: str, week: int) -> list[dict]:
        """Per-roster matchup rows for one league-week, unmodified.

        On the protocol because ``grader_io`` needs the raw rows (starters,
        players_points) rather than the paired ``Matchup`` shape, and used to
        reach through to ``self._client`` to get them.
        """
        resp = await self._client.get(f"/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        return resp.json() or []

    async def _all_week_transactions(self, league_id: str) -> list[dict]:
        """Every transaction across the fantasy season, in week order."""
        out: list[dict] = []
        for week in range(1, 19):
            out.extend(await self.get_transactions(league_id, week) or [])
        return out

    async def get_trade_transactions(self, league_id: str) -> list[dict]:
        """Completed trades only. Already in the shape normalize_trade wants —
        Sleeper is the reference encoding for that shape."""
        return [
            tx for tx in await self._all_week_transactions(league_id)
            if tx.get("type") == "trade" and tx.get("status") == "complete"
        ]

    async def get_drop_transactions(self, league_id: str) -> list[dict]:
        """Completed non-trade transactions that dropped someone. Trade drops
        are excluded — a trade is not a drop, and build_drop_index would
        otherwise record every traded-away player as cut."""
        return [
            tx for tx in await self._all_week_transactions(league_id)
            if tx.get("type") in _DROP_TX_TYPES
            and tx.get("status") == "complete"
            and (tx.get("drops") or {})
        ]

    async def get_draft_results(self, league_id: str) -> list[dict]:
        """One row per pick made across every completed draft this season."""
        out: list[dict] = []
        for d in await self.get_drafts(league_id):
            if d.get("status") != "complete":
                continue
            season = int(d.get("season") or 0)
            for pick in await self.get_draft_picks(d["draft_id"]):
                out.append({**pick, "season": season})
        return out

    async def get_phase_map(self, league) -> dict:
        """(week, roster_id) -> "playoff" | "toilet", from the two brackets.

        Sleeper publishes brackets and the engine interprets them; Yahoo marks
        matchups directly. The protocol asks for the map both can produce.
        """
        from sleeper_dynasty.engine.playoff_phase import classify_playoff_phases
        winners = await self.get_winners_bracket(league.league_id)
        losers = await self.get_losers_bracket(league.league_id)
        return classify_playoff_phases(
            winners, losers,
            league.playoff_week_start,
            getattr(league, "playoff_round_type", 0),
        )
```

Add the drop-type constant at module level, beside `_TYPE_TO_FORMAT`:

```python
# Sleeper transaction types that can drop a player outside a trade.
_DROP_TX_TYPES = ("drop", "waiver", "free_agent")
```

- [ ] **Step 4: Remove the reach-through in `grader_io`**

In `api/app/services/grader_io.py`, replace lines 160-163:

```python
    raw_per_week: dict[int, list[dict]] = {}
    for week in range(1, 19):
        resp = await client._client.get(f"/league/{lg.league_id}/matchups/{week}")
        resp.raise_for_status()
        raw_per_week[week] = resp.json() or []
```

with:

```python
    raw_per_week: dict[int, list[dict]] = {}
    for week in range(1, 19):
        raw_per_week[week] = await client.get_raw_matchups(lg.league_id, week)
```

Leave the `get_winners_bracket` / `get_losers_bracket` calls on lines 166-167 as they are — the bundle persists raw brackets for sealed leagues and Task 7 handles what a Yahoo bundle stores there.

- [ ] **Step 5: Route trade-history fetching through the protocol**

In `src/sleeper_dynasty/engine/trade_history.py`, replace the transaction-fetching block inside `_fetch_league_season_data` (the `async def _one_week` definition through the end of the `for week_txs in tx_chunks:` loop, lines 378-395) with:

```python
    raw_trades: list[dict] = []
    for tx in await client.get_trade_transactions(league.league_id):
        tx_id = str(tx.get("transaction_id", ""))
        if tx_id in BLACKLISTED_TRANSACTION_IDS:
            log.info("Skipping blacklisted transaction %s", tx_id)
            continue
        raw_trades.append(tx)
    raw_drops = await client.get_drop_transactions(league.league_id)
```

Delete the now-unused `_MAX_WEEK` constant and the `asyncio` import **only if** `grep -n "asyncio\|_MAX_WEEK" src/sleeper_dynasty/engine/trade_history.py` shows no other use.

Replace the draft-fetching block immediately below it:

```python
    drafts = await client.get_drafts(league.league_id)
    draft_picks_by_draft_id: dict[str, list[dict]] = {}
    for d in drafts:
        if d.get("status") == "complete":
            picks = await client.get_draft_picks(d["draft_id"])
            draft_picks_by_draft_id[d["draft_id"]] = picks
```

Leave this block **unchanged**. It is Sleeper-shaped (`draft_id`-keyed) and Task 8 handles the Yahoo mapping onto it; changing it now would mean rewriting `_resolve_one_asset`'s pick-resolution logic in a refactor that is supposed to change nothing.

- [ ] **Step 6: Un-xfail the conformance test**

In `tests/test_platform_protocol.py`, delete the `@pytest.mark.xfail(...)` line added in Task 2 Step 4.

- [ ] **Step 7: Run the tests**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_sleeper_protocol_conformance.py tests/test_platform_protocol.py -v`
Expected: PASS — 13 passed, 0 xfailed

- [ ] **Step 8: Run the full backend suites — this is the regression gate**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/ -q && pytest api/tests/ -q`
Expected: PASS — engine ≥534, api ≥484. **Any failure here is a real behavior change, not a test that needs updating.** This task's entire contract is that nothing changed. If a test fails, revert the specific edit that caused it and re-derive it rather than adjusting the test.

- [ ] **Step 9: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/api/sleeper.py api/app/services/grader_io.py src/sleeper_dynasty/engine/trade_history.py tests/test_sleeper_protocol_conformance.py tests/test_platform_protocol.py
git commit -m "refactor: SleeperClient implements LeaguePlatform; drop the _client reach-through"
```

---

### Task 4: Yahoo → Sleeper player id mapping

**Files:**
- Create: `src/sleeper_dynasty/api/yahoo_ids.py`
- Test: `tests/test_yahoo_ids.py`

**Interfaces:**
- Consumes: `engine/injury_data.py`'s `_IDS_URL` and `_fetch_csv_rows` (the DynastyProcess `db_playerids.csv` this app already downloads).
- Produces: `build_yahoo_to_sleeper(rows) -> dict[str, str]` (pure) and `async fetch_yahoo_to_sleeper(cache=None) -> dict[str, str]` (cached fetch).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_yahoo_ids.py`:

```python
from sleeper_dynasty.api.yahoo_ids import build_yahoo_to_sleeper


def test_maps_yahoo_id_to_sleeper_id():
    rows = [{"yahoo_id": "31002", "sleeper_id": "4034", "name": "Alvin Kamara"}]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_rows_missing_either_id_are_skipped():
    rows = [
        {"yahoo_id": "31002", "sleeper_id": "4034"},
        {"yahoo_id": "", "sleeper_id": "5000"},
        {"yahoo_id": "31003", "sleeper_id": ""},
        {"yahoo_id": "31004"},
        {"sleeper_id": "6000"},
    ]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_ids_are_normalized_to_strings_without_float_suffixes():
    """The CSV round-trips numeric columns through pandas, so an id can
    arrive as "31002.0". Left alone it would never match a Yahoo key."""
    rows = [{"yahoo_id": "31002.0", "sleeper_id": "4034.0"}]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_whitespace_is_stripped():
    rows = [{"yahoo_id": " 31002 ", "sleeper_id": " 4034 "}]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_first_row_wins_on_a_duplicate_yahoo_id():
    """Deterministic rather than last-write-wins, so two runs over the same
    CSV can never disagree."""
    rows = [
        {"yahoo_id": "31002", "sleeper_id": "4034"},
        {"yahoo_id": "31002", "sleeper_id": "9999"},
    ]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_empty_input_is_an_empty_map_not_an_error():
    assert build_yahoo_to_sleeper([]) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_ids.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.api.yahoo_ids'`

- [ ] **Step 3: Write the implementation**

Create `src/sleeper_dynasty/api/yahoo_ids.py`:

```python
"""Yahoo player id -> Sleeper player id.

Sleeper's player_id is this app's canonical key: KTC, FantasyCalc, nflverse,
the chain cache and lineage are all keyed on it. Rather than teach any of them
a second identity scheme, the Yahoo adapter translates at its own boundary and
nothing inward ever sees a Yahoo id.

The map comes from DynastyProcess's ``db_playerids.csv``, which this app
already downloads for injury signals (``engine/injury_data.py``) and which
carries ``yahoo_id`` and ``sleeper_id`` columns side by side.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Same source engine/injury_data.py uses. Kept as its own constant so a change
# to one consumer's URL cannot silently repoint the other.
IDS_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv"

_CACHE_KEY = "yahoo_to_sleeper_ids.json"
_CACHE_TTL = 7 * 24 * 3600  # ids change only when players enter the league


def _clean_id(raw) -> str:
    """Normalize a CSV id cell to a bare string.

    The upstream CSV round-trips numeric columns through pandas, so an id can
    arrive as "31002.0". Left alone that never matches a Yahoo player key.
    """
    s = str(raw or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def build_yahoo_to_sleeper(rows: list[dict]) -> dict[str, str]:
    """Pure: CSV rows -> {yahoo_id: sleeper_id}.

    Rows missing either id are skipped — a partial mapping is worse than no
    mapping, because it silently drops players from a trade. First row wins on
    a duplicate so two runs over the same CSV can never disagree.
    """
    out: dict[str, str] = {}
    for row in rows:
        yid = _clean_id(row.get("yahoo_id"))
        sid = _clean_id(row.get("sleeper_id"))
        if not yid or not sid:
            continue
        out.setdefault(yid, sid)
    return out


async def fetch_yahoo_to_sleeper(cache=None) -> dict[str, str]:
    """Fetch (or read cached) the yahoo_id -> sleeper_id map.

    Returns {} on any failure. An empty map is not silently acceptable to
    callers — the adapter treats it as fatal — but raising here would take
    down an otherwise healthy refresh at the fetch layer instead of at the
    layer that knows what a missing map means.
    """
    if cache is not None:
        cached = cache.read(_CACHE_KEY, max_age_seconds=_CACHE_TTL)
        if cached:
            return cached
    try:
        from sleeper_dynasty.engine.injury_data import _fetch_csv_rows
        rows = _fetch_csv_rows(IDS_URL)
    except Exception:
        log.warning("player id map fetch failed", exc_info=True)
        return {}
    mapping = build_yahoo_to_sleeper(rows)
    log.info("player id map: %d yahoo ids resolved to sleeper ids", len(mapping))
    if cache is not None and mapping:
        cache.write(_CACHE_KEY, mapping)
    return mapping
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_ids.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Confirm `_fetch_csv_rows` is importable and returns dict rows**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && python -c "
from sleeper_dynasty.engine.injury_data import _fetch_csv_rows
rows = _fetch_csv_rows('https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv')
print(type(rows), len(rows))
print(sorted(k for k in rows[0] if 'id' in k.lower()))
"`
Expected: a list of several thousand dicts, and the printed key list contains both `yahoo_id` and `sleeper_id`. **If either column is absent, stop** — the whole identity strategy rests on it, and the fallback (name matching via `util/name_match.py`) is a different design that needs its own decision.

- [ ] **Step 6: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/api/yahoo_ids.py tests/test_yahoo_ids.py
git commit -m "feat: yahoo_id to sleeper_id mapping from the DynastyProcess id table"
```

---

### Task 5: Yahoo transport and JSON unwrapping

Yahoo's `format=json` output is XML transliterated into JSON: nested single-key envelopes, collections encoded as `{"0": {...}, "1": {...}, "count": 2}`, and resources split across lists of partial dicts that must be merged. Every later task depends on flattening it, so it gets its own tested module.

**Files:**
- Create: `src/sleeper_dynasty/api/yahoo_json.py`
- Create: `tests/fixtures/yahoo/` (recorded payloads)
- Create: `scripts/record_yahoo_fixtures.py`
- Test: `tests/test_yahoo_json.py`

**Interfaces:**
- Produces: `collection(node) -> list[dict]`, `merge_fragments(node) -> dict`, `unwrap(payload, *path) -> object`.
- Consumed by: Tasks 6, 7, 8.

**Record fixtures before writing the parser.** Do not write tests against invented Yahoo payloads — the exact nesting varies by resource and any guess will be confidently wrong. Step 1 captures real responses; Steps 3+ are written against what came back.

- [ ] **Step 1: Record real fixtures**

Create `scripts/record_yahoo_fixtures.py`:

```python
"""Save real Yahoo Fantasy API responses as test fixtures.

Usage:
    export YAHOO_DEV_ACCESS_TOKEN=...        # from Yahoo's OAuth playground
    export YAHOO_DEV_LEAGUE_KEY=461.l.123456
    python scripts/record_yahoo_fixtures.py

Writes tests/fixtures/yahoo/<name>.json. Run once; commit the results. These
are read-only league payloads, but scrub anything you would not put in a
public repo before committing.
"""

import asyncio
import json
import os
import pathlib

import httpx

BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "yahoo"

RESOURCES = {
    "league_meta": "/league/{lk}",
    "league_settings": "/league/{lk}/settings",
    "teams": "/league/{lk}/teams",
    "standings": "/league/{lk}/standings",
    "scoreboard_wk1": "/league/{lk}/scoreboard;week=1",
    "transactions_trades": "/league/{lk}/transactions;types=trade",
    "transactions_all": "/league/{lk}/transactions",
    "draftresults": "/league/{lk}/draftresults",
    "user_leagues": "/users;use_login=1/games;game_keys=nfl/leagues",
}


async def main():
    token = os.environ["YAHOO_DEV_ACCESS_TOKEN"]
    lk = os.environ["YAHOO_DEV_LEAGUE_KEY"]
    OUT.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30.0) as c:
        for name, path in RESOURCES.items():
            url = path.format(lk=lk)
            resp = await c.get(url, params={"format": "json"})
            print(f"{resp.status_code}  {name}  {url}")
            if resp.status_code != 200:
                print(f"   body: {resp.text[:300]}")
                continue
            (OUT / f"{name}.json").write_text(json.dumps(resp.json(), indent=2))


asyncio.run(main())
```

Get a token from Yahoo's OAuth playground or a one-off authorization-code exchange, register an app at the Yahoo developer portal with **read** permission for Fantasy Sports, then run:

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
export YAHOO_DEV_ACCESS_TOKEN=...
export YAHOO_DEV_LEAGUE_KEY=...
python scripts/record_yahoo_fixtures.py
```

**Read the recorded files before writing any parser.** Note for each resource: where the real payload sits under `fantasy_content`, whether collections use the `{"0":…, "count":N}` encoding, and which resources split across a list of partial dicts.

- [ ] **Step 2: Write the failing tests against the recorded fixtures**

Create `tests/test_yahoo_json.py`. The synthetic cases below encode the two encodings Yahoo uses; **add at least one assertion per recorded fixture** confirming the helpers extract a known-real value from it (e.g. the league name out of `league_meta.json`, the team count out of `teams.json`).

```python
import json
import pathlib

import pytest

from sleeper_dynasty.api.yahoo_json import collection, merge_fragments, unwrap

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "yahoo"


def _fixture(name):
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {name}.json not recorded")
    return json.loads(path.read_text())


def test_collection_reads_the_numeric_key_encoding():
    node = {"0": {"a": 1}, "1": {"a": 2}, "count": 2}
    assert collection(node) == [{"a": 1}, {"a": 2}]


def test_collection_orders_numerically_not_lexically():
    """"10" sorts before "2" as a string — that would silently reorder a
    12-team league's rosters."""
    node = {str(i): {"i": i} for i in range(12)}
    node["count"] = 12
    assert [d["i"] for d in collection(node)] == list(range(12))


def test_collection_ignores_the_count_key():
    assert collection({"0": {"a": 1}, "count": 1}) == [{"a": 1}]


def test_collection_of_a_plain_list_is_that_list():
    assert collection([{"a": 1}]) == [{"a": 1}]


def test_collection_of_none_or_empty_is_empty():
    assert collection(None) == []
    assert collection({}) == []
    assert collection({"count": 0}) == []


def test_merge_fragments_flattens_a_list_of_partial_dicts():
    """Yahoo splits one resource across several dicts in a list."""
    assert merge_fragments([
        {"team_key": "461.l.1.t.3"}, {"name": "Team Rocket"}, [],
    ]) == {"team_key": "461.l.1.t.3", "name": "Team Rocket"}


def test_merge_fragments_recurses_into_nested_lists():
    assert merge_fragments([[{"a": 1}], [{"b": 2}]]) == {"a": 1, "b": 2}


def test_merge_fragments_keeps_the_first_value_on_a_key_collision():
    assert merge_fragments([{"a": 1}, {"a": 2}]) == {"a": 1}


def test_merge_fragments_passes_a_dict_through():
    assert merge_fragments({"a": 1}) == {"a": 1}


def test_unwrap_walks_a_key_path():
    payload = {"fantasy_content": {"league": [{"name": "X"}]}}
    assert unwrap(payload, "fantasy_content", "league") == [{"name": "X"}]


def test_unwrap_returns_none_for_a_missing_path():
    assert unwrap({"fantasy_content": {}}, "fantasy_content", "league") is None


def test_unwrap_returns_none_rather_than_raising_on_a_non_dict():
    assert unwrap({"fantasy_content": 3}, "fantasy_content", "league") is None


def test_real_league_payload_yields_a_league_name():
    payload = _fixture("league_meta")
    league = merge_fragments(unwrap(payload, "fantasy_content", "league"))
    assert isinstance(league.get("name"), str) and league["name"]
    assert league.get("league_key")


def test_real_teams_payload_yields_every_team():
    payload = _fixture("teams")
    node = unwrap(payload, "fantasy_content", "league")
    teams = collection(merge_fragments(node).get("teams"))
    assert len(teams) >= 2
    assert all(merge_fragments(t.get("team")).get("team_key") for t in teams)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_json.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.api.yahoo_json'`

- [ ] **Step 4: Write the unwrapper**

Create `src/sleeper_dynasty/api/yahoo_json.py`:

```python
"""Yahoo's XML-shaped JSON -> plain dicts and lists.

Yahoo's ``format=json`` output is its XML transliterated, which produces two
encodings nothing else in this codebase has to deal with:

1. **Numeric-key collections.** A list of N things is an object with keys
   "0".."N-1" plus a "count". Ordering must be numeric — "10" sorts before "2"
   as a string, which would silently reorder a 12-team league.
2. **Fragmented resources.** One logical resource arrives as a *list* of
   partial dicts (and sometimes nested lists) that have to be merged to see
   the whole thing.

Isolated here and unit-tested against recorded fixtures so the adapter's own
modules read as ordinary mapping code.
"""

from __future__ import annotations


def collection(node) -> list:
    """A Yahoo collection -> a plain list, in numeric key order.

    Accepts the ``{"0": …, "1": …, "count": N}`` encoding, a plain list, or
    None/empty (-> []).
    """
    if node is None:
        return []
    if isinstance(node, list):
        return node
    if not isinstance(node, dict):
        return []
    keys = [k for k in node if str(k).isdigit()]
    return [node[k] for k in sorted(keys, key=int)]


def merge_fragments(node) -> dict:
    """A fragmented Yahoo resource -> one flat dict.

    A resource can arrive as a list of partial dicts, with nested lists mixed
    in. Merges depth-first, keeping the FIRST value on a key collision:
    Yahoo's leading fragments carry the identifying fields, and letting a
    later fragment overwrite ``team_key`` would corrupt identity.
    """
    if isinstance(node, dict):
        return dict(node)
    if not isinstance(node, list):
        return {}
    out: dict = {}
    for part in node:
        if isinstance(part, dict):
            fragment = part
        elif isinstance(part, list):
            fragment = merge_fragments(part)
        else:
            continue
        for k, v in fragment.items():
            out.setdefault(k, v)
    return out


def unwrap(payload, *path):
    """Walk a key path through nested dicts, returning None if it breaks.

    None rather than raising: a missing sub-resource is normal (a league with
    no trades has no transactions node), and the caller decides whether that
    is empty-and-fine or a real failure.
    """
    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_json.py -v`
Expected: PASS — 14 passed (the two `_fixture` tests skip if fixtures were not recorded; they must **pass**, not skip, before Task 6 begins).

- [ ] **Step 6: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/api/yahoo_json.py scripts/record_yahoo_fixtures.py tests/test_yahoo_json.py tests/fixtures/yahoo/
git commit -m "feat: Yahoo JSON unwrapping with recorded API fixtures"
```

---

### Task 6: `YahooAdapter` — league, chain, rosters, users

**Files:**
- Create: `src/sleeper_dynasty/api/yahoo.py`
- Test: `tests/test_yahoo_adapter_league.py`

**Interfaces:**
- Consumes: `yahoo_json` (Task 5), `yahoo_ids` (Task 4), `LeaguePlatform`/`PhaseMap` (Task 2), `League`/`Roster` (Task 1).
- Produces: `YahooAdapter(access_token, *, id_map=None)` with `walk_league_history`, `get_league`, `get_rosters`, `get_users`, `close`, plus the internal `_get(path, **params)`. Later tasks add the remaining protocol methods to this same class.

**Roster identity:** a Yahoo team key is `{league_key}.t.{n}`. The trailing `n` is a small int, so `Roster.roster_id: int` survives unchanged — parse it off the key. Owner identity is the Yahoo GUID from the team's `managers` block; where a manager GUID is absent (a co-managed or orphaned team), fall back to the team key so identity stays stable rather than collapsing several teams onto `""`.

**Chain walking:** Yahoo's league `settings` carries `renew` (the prior season's `{game_key}_{league_id}`) and `renewed` (the next season's). Walk `renew` backward, mirroring `previous_league_id`. Note the separator differs from a league key — `renew` uses `_`, league keys use `.l.` — so it must be reformatted.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_yahoo_adapter_league.py`:

```python
import pytest

from sleeper_dynasty.api.yahoo import YahooAdapter, renew_to_league_key, roster_id_for


def test_roster_id_parses_the_team_key_suffix():
    assert roster_id_for("461.l.123456.t.7") == 7


def test_roster_id_of_a_malformed_key_is_zero_not_a_crash():
    """A team we cannot identify must not take down the whole refresh."""
    assert roster_id_for("garbage") == 0
    assert roster_id_for("") == 0
    assert roster_id_for(None) == 0


def test_renew_is_reformatted_into_a_league_key():
    """Yahoo writes the prior season as "449_123456" but addresses leagues as
    "449.l.123456"."""
    assert renew_to_league_key("449_123456") == "449.l.123456"


def test_renew_none_or_empty_terminates_the_chain():
    assert renew_to_league_key(None) is None
    assert renew_to_league_key("") is None
    assert renew_to_league_key("garbage") is None


class _FakeAdapter(YahooAdapter):
    """Replays canned payloads instead of calling Yahoo."""

    def __init__(self, routes):
        super().__init__(access_token="test", id_map={})
        self.routes = routes
        self.requested = []

    async def _get(self, path, **params):
        self.requested.append(path)
        return self.routes[path]


def _league_payload(*, league_key, name, season, renew=None, num_teams=12,
                    playoff_start=15, keeper=0):
    settings = {"playoff_start_week": str(playoff_start),
                "num_playoff_teams": "6",
                "uses_playoff_reseeding": "0"}
    if renew is not None:
        settings["renew"] = renew
    meta = {
        "league_key": league_key, "name": name, "season": str(season),
        "num_teams": num_teams, "current_week": "5",
        "is_finished": 0,
    }
    if keeper:
        settings["is_keeper_league"] = "1"
    return {"fantasy_content": {"league": [meta, {"settings": [settings]}]}}


@pytest.mark.asyncio
async def test_get_league_maps_metadata_onto_the_neutral_model():
    a = _FakeAdapter({
        "/league/461.l.1/settings": _league_payload(
            league_key="461.l.1", name="Test League", season=2025),
    })
    lg, prev = await a.get_league("461.l.1")
    assert lg.league_id == "461.l.1"
    assert lg.name == "Test League"
    assert lg.season == 2025
    assert lg.total_rosters == 12
    assert lg.playoff_week_start == 15
    assert prev is None


@pytest.mark.asyncio
async def test_a_yahoo_league_without_keepers_is_redraft():
    a = _FakeAdapter({
        "/league/461.l.1/settings": _league_payload(
            league_key="461.l.1", name="T", season=2025),
    })
    lg, _ = await a.get_league("461.l.1")
    assert lg.format == "redraft"


@pytest.mark.asyncio
async def test_a_yahoo_keeper_league_is_keeper():
    a = _FakeAdapter({
        "/league/461.l.1/settings": _league_payload(
            league_key="461.l.1", name="T", season=2025, keeper=1),
    })
    lg, _ = await a.get_league("461.l.1")
    assert lg.format == "keeper"


@pytest.mark.asyncio
async def test_a_yahoo_league_is_never_dynasty():
    """Yahoo cannot trade future picks. Grading one as dynasty would route it
    to results_led and score it on an Outlook pillar built from draft capital
    that structurally cannot exist."""
    for keeper in (0, 1):
        a = _FakeAdapter({
            "/league/461.l.1/settings": _league_payload(
                league_key="461.l.1", name="T", season=2025, keeper=keeper),
        })
        lg, _ = await a.get_league("461.l.1")
        assert lg.format != "dynasty"


@pytest.mark.asyncio
async def test_walk_league_history_follows_renew_backward():
    a = _FakeAdapter({
        "/league/461.l.1/settings": _league_payload(
            league_key="461.l.1", name="T25", season=2025, renew="449_9"),
        "/league/449.l.9/settings": _league_payload(
            league_key="449.l.9", name="T24", season=2024),
    })
    chain = await a.walk_league_history("461.l.1")
    assert [lg.season for lg in chain] == [2025, 2024]


@pytest.mark.asyncio
async def test_walk_league_history_stops_on_a_cycle():
    """A self-referential renew would otherwise loop until the process dies."""
    a = _FakeAdapter({
        "/league/461.l.1/settings": _league_payload(
            league_key="461.l.1", name="T", season=2025, renew="461_1"),
    })
    chain = await a.walk_league_history("461.l.1")
    assert [lg.league_id for lg in chain] == ["461.l.1"]


@pytest.mark.asyncio
async def test_get_rosters_maps_teams_onto_roster_records():
    a = _FakeAdapter({
        "/league/461.l.1/teams": {"fantasy_content": {"league": [
            {"league_key": "461.l.1"},
            {"teams": {"count": 1, "0": {"team": [
                [{"team_key": "461.l.1.t.3"}, {"name": "Team Rocket"},
                 {"managers": [{"manager": {"guid": "ABC123",
                                            "nickname": "tom"}}]}],
            ]}}},
        ]}},
        "/league/461.l.1/standings": {"fantasy_content": {"league": [
            {"league_key": "461.l.1"},
            {"standings": [{"teams": {"count": 1, "0": {"team": [
                [{"team_key": "461.l.1.t.3"}],
                {"team_standings": {
                    "outcome_totals": {"wins": "8", "losses": "5", "ties": "0"},
                    "points_for": "1450.25", "points_against": "1300.10"}},
            ]}}}]},
        ]}},
    })
    rosters = await a.get_rosters("461.l.1")
    assert len(rosters) == 1
    r = rosters[0]
    assert r.roster_id == 3
    assert r.owner_id == "ABC123"
    assert r.owner_name == "Team Rocket"
    assert (r.wins, r.losses, r.ties) == (8, 5, 0)
    assert r.points_for == pytest.approx(1450.25)
    assert r.points_against == pytest.approx(1300.10)


@pytest.mark.asyncio
async def test_a_team_without_a_manager_guid_falls_back_to_its_team_key():
    a = _FakeAdapter({
        "/league/461.l.1/teams": {"fantasy_content": {"league": [
            {"league_key": "461.l.1"},
            {"teams": {"count": 1, "0": {"team": [
                [{"team_key": "461.l.1.t.4"}, {"name": "Orphan"}],
            ]}}},
        ]}},
        "/league/461.l.1/standings": {"fantasy_content": {"league": [
            {"league_key": "461.l.1"}, {"standings": [{"teams": {"count": 0}}]},
        ]}},
    })
    rosters = await a.get_rosters("461.l.1")
    assert rosters[0].owner_id == "461.l.1.t.4"


@pytest.mark.asyncio
async def test_get_users_keys_by_owner_id():
    a = _FakeAdapter({
        "/league/461.l.1/teams": {"fantasy_content": {"league": [
            {"league_key": "461.l.1"},
            {"teams": {"count": 1, "0": {"team": [
                [{"team_key": "461.l.1.t.3"}, {"name": "Team Rocket"},
                 {"managers": [{"manager": {"guid": "ABC123",
                                            "nickname": "tom"}}]}],
            ]}}},
        ]}},
        "/league/461.l.1/standings": {"fantasy_content": {"league": [
            {"league_key": "461.l.1"}, {"standings": [{"teams": {"count": 0}}]},
        ]}},
    })
    users = await a.get_users("461.l.1")
    assert users["ABC123"]["display_name"] == "tom"
    assert users["ABC123"]["team_name"] == "Team Rocket"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_adapter_league.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.api.yahoo'`

- [ ] **Step 3: Write the adapter's league half**

Create `src/sleeper_dynasty/api/yahoo.py`:

```python
"""Yahoo Fantasy Sports -> the LeaguePlatform protocol.

Reads a Yahoo redraft or keeper league into the same normalized records the
Sleeper client produces, so the engine never learns which platform a league
came from. Yahoo player ids are translated to Sleeper ids at this boundary
(see api/yahoo_ids.py); nothing inward sees a Yahoo id.

Auth: this class takes an access token and does not know how to get one. Token
acquisition, storage, and refresh are deliberately somebody else's problem —
see the auth plan. That keeps the ingestion surface testable without any
credential machinery.
"""

from __future__ import annotations

import logging

import httpx

from sleeper_dynasty.models.league import League, Roster

log = logging.getLogger(__name__)

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"

# Yahoo has no dynasty concept and cannot trade future picks, so a Yahoo
# league is exactly one of these two.
FORMAT_KEEPER = "keeper"
FORMAT_REDRAFT = "redraft"


def roster_id_for(team_key) -> int:
    """The small int at the end of a team key ``{league_key}.t.{n}``.

    Keeps ``Roster.roster_id: int`` intact across platforms. Returns 0 on a
    malformed key rather than raising — one unidentifiable team must not take
    down a whole league's refresh.
    """
    tail = str(team_key or "").rsplit(".t.", 1)
    if len(tail) != 2 or not tail[1].isdigit():
        return 0
    return int(tail[1])


def renew_to_league_key(renew) -> str | None:
    """Yahoo's ``renew`` ("449_123456") -> a league key ("449.l.123456").

    ``renew`` points at the prior season's league — Yahoo's equivalent of
    Sleeper's ``previous_league_id`` — but uses a different separator from the
    key format used to address a league. Returns None for anything that is not
    that shape, which terminates the chain walk.
    """
    parts = str(renew or "").split("_")
    if len(parts) != 2 or not all(parts):
        return None
    return f"{parts[0]}.l.{parts[1]}"


class YahooAdapter:
    """One Yahoo league chain, read through a caller-supplied access token."""

    def __init__(self, access_token: str, *, id_map: dict[str, str] | None = None):
        self._token = access_token
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        # yahoo_id -> sleeper_id. Injected so tests need no network and so a
        # refresh fetches it once for the whole chain.
        self._id_map = id_map if id_map is not None else {}

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params) -> dict:
        """One authenticated GET, JSON-decoded.

        A 401 here means the access token expired mid-refresh. It is raised
        unchanged: the caller that minted the token is the only layer that can
        do anything about it.
        """
        resp = await self._client.get(path, params={"format": "json", **params})
        resp.raise_for_status()
        return resp.json()

    def to_sleeper_id(self, yahoo_player_id) -> str | None:
        """Translate one Yahoo player id. None when unmapped."""
        return self._id_map.get(str(yahoo_player_id or "").strip())

    # ---- league metadata and chain -------------------------------------

    async def get_league(self, league_id: str) -> tuple[League, str | None]:
        """(League, previous-season-league-key-or-None)."""
        from sleeper_dynasty.api.yahoo_json import merge_fragments, unwrap

        payload = await self._get(f"/league/{league_id}/settings")
        node = unwrap(payload, "fantasy_content", "league")
        meta = merge_fragments(node)
        settings = merge_fragments(meta.get("settings"))

        keeper = str(settings.get("is_keeper_league", "0")) in ("1", "true", "True")
        league = League(
            league_id=meta.get("league_key") or league_id,
            name=meta.get("name") or league_id,
            season=int(meta.get("season") or 0),
            total_rosters=int(meta.get("num_teams") or 0),
            roster_positions=_roster_positions(settings),
            scoring_settings={},
            playoff_week_start=int(settings.get("playoff_start_week") or 15),
            num_playoff_teams=int(settings.get("num_playoff_teams") or 6),
            status="complete" if str(meta.get("is_finished") or "0") in ("1", "true")
                   else "in_season",
            # Never "dynasty": Yahoo cannot trade future picks, so grading one
            # as dynasty would route it to results_led and score an Outlook
            # pillar built from draft capital that structurally cannot exist.
            format=FORMAT_KEEPER if keeper else FORMAT_REDRAFT,
        )
        return league, renew_to_league_key(settings.get("renew"))

    async def walk_league_history(self, league_id: str) -> list[League]:
        """Walk ``renew`` back to the chain origin, newest season first.

        Guards against a cycle: a self-referential or looping ``renew`` would
        otherwise spin until the process dies. Sleeper's walk needs no such
        guard because its chain is a strict parent link; Yahoo's is a pair of
        cross-references that a league admin can point anywhere.
        """
        chain: list[League] = []
        seen: set[str] = set()
        current: str | None = league_id
        while current is not None and current not in seen:
            seen.add(current)
            league, prev = await self.get_league(current)
            chain.append(league)
            current = prev
        return chain

    # ---- teams, rosters, users -----------------------------------------

    async def _teams(self, league_id: str) -> list[dict]:
        """Flattened team resources for one league-season."""
        from sleeper_dynasty.api.yahoo_json import collection, merge_fragments, unwrap

        payload = await self._get(f"/league/{league_id}/teams")
        node = merge_fragments(unwrap(payload, "fantasy_content", "league"))
        return [merge_fragments(t.get("team")) for t in collection(node.get("teams"))]

    async def _standings_by_team_key(self, league_id: str) -> dict[str, dict]:
        """team_key -> its ``team_standings`` block."""
        from sleeper_dynasty.api.yahoo_json import collection, merge_fragments, unwrap

        payload = await self._get(f"/league/{league_id}/standings")
        node = merge_fragments(unwrap(payload, "fantasy_content", "league"))
        standings = merge_fragments(collection(node.get("standings")))
        out: dict[str, dict] = {}
        for entry in collection(standings.get("teams")):
            team = merge_fragments(entry.get("team"))
            key = team.get("team_key")
            if key:
                out[key] = merge_fragments(team.get("team_standings"))
        return out

    async def get_rosters(self, league_id: str) -> list[Roster]:
        teams = await self._teams(league_id)
        standings = await self._standings_by_team_key(league_id)
        rosters: list[Roster] = []
        for team in teams:
            key = team.get("team_key") or ""
            st = standings.get(key) or {}
            totals = st.get("outcome_totals") or {}
            rosters.append(Roster(
                roster_id=roster_id_for(key),
                owner_id=_owner_id(team),
                owner_name=team.get("name") or "Unknown",
                # Yahoo's roster is a separate per-week resource; the grader
                # reads current holdings from get_raw_matchups instead, so
                # this stays empty rather than costing 12 extra requests.
                players=[],
                wins=int(totals.get("wins") or 0),
                losses=int(totals.get("losses") or 0),
                ties=int(totals.get("ties") or 0),
                points_for=float(st.get("points_for") or 0.0),
                points_against=float(st.get("points_against") or 0.0),
            ))
        return rosters

    async def get_users(self, league_id: str) -> dict[str, dict[str, str | None]]:
        out: dict[str, dict[str, str | None]] = {}
        for team in await self._teams(league_id):
            out[_owner_id(team)] = {
                "display_name": _manager_field(team, "nickname")
                                or team.get("name") or "Unknown",
                "team_name": team.get("name"),
                "avatar_url": team.get("team_logos") and _logo_url(team) or None,
            }
        return out


def _roster_positions(settings: dict) -> list[str]:
    """Flatten Yahoo's roster_positions into the repeated-slot list the engine
    expects (``["QB", "RB", "RB", …]``)."""
    from sleeper_dynasty.api.yahoo_json import collection, merge_fragments

    out: list[str] = []
    for entry in collection(settings.get("roster_positions")):
        rp = merge_fragments(entry.get("roster_position") or entry)
        pos = rp.get("position")
        if not pos:
            continue
        out.extend([str(pos)] * int(rp.get("count") or 1))
    return out


def _manager_field(team: dict, field: str) -> str | None:
    from sleeper_dynasty.api.yahoo_json import collection, merge_fragments

    for entry in collection(team.get("managers")):
        mgr = merge_fragments(entry.get("manager") or entry)
        val = mgr.get(field)
        if val:
            return str(val)
    return None


def _owner_id(team: dict) -> str:
    """Stable owner identity: the manager GUID, else the team key.

    A co-managed or orphaned team can have no GUID. Falling back to the team
    key keeps each such team distinct; defaulting to "" would collapse every
    one of them onto a single phantom owner.
    """
    return _manager_field(team, "guid") or str(team.get("team_key") or "")


def _logo_url(team: dict) -> str | None:
    from sleeper_dynasty.api.yahoo_json import collection, merge_fragments

    for entry in collection(team.get("team_logos")):
        logo = merge_fragments(entry.get("team_logo") or entry)
        if logo.get("url"):
            return str(logo["url"])
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_adapter_league.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: Check the synthetic payloads against the recorded fixtures**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && python -c "
import asyncio, json, pathlib
from sleeper_dynasty.api.yahoo import YahooAdapter
F = pathlib.Path('tests/fixtures/yahoo')

class Replay(YahooAdapter):
    def __init__(self):
        super().__init__(access_token='x', id_map={})
    async def _get(self, path, **kw):
        name = 'league_settings' if path.endswith('/settings') else (
               'teams' if path.endswith('/teams') else 'standings')
        return json.loads((F / f'{name}.json').read_text())

async def main():
    a = Replay()
    lg, prev = await a.get_league('x')
    print('league:', lg.name, lg.season, lg.format, lg.total_rosters,
          'playoff_wk', lg.playoff_week_start, 'prev', prev)
    print('positions:', lg.roster_positions)
    for r in await a.get_rosters('x'):
        print(' roster', r.roster_id, r.owner_id[:8], r.owner_name,
              r.wins, r.losses, r.points_for)
    await a.close()

asyncio.run(main())
"`
Expected: real values from your league — correct name, season, format, team count, and one line per team with plausible records. **If a field comes out empty or zero, the synthetic fixtures in Step 1 guessed the nesting wrong.** Fix the adapter against the real payload and add a fixture-backed test for the field that was wrong.

- [ ] **Step 6: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/api/yahoo.py tests/test_yahoo_adapter_league.py
git commit -m "feat: YahooAdapter reads league metadata, chain, rosters, and users"
```

---

### Task 7: `YahooAdapter` — matchups and the playoff phase map

**Files:**
- Modify: `src/sleeper_dynasty/api/yahoo.py`
- Test: `tests/test_yahoo_adapter_matchups.py`

**Interfaces:**
- Consumes: Task 6's `YahooAdapter`, `to_sleeper_id`.
- Produces: `YahooAdapter.get_raw_matchups(league_id, week)`, `.get_phase_map(league)`, `.get_nfl_state()`, `.get_stats(season, week)`, `.get_players()`, `.get_traded_picks(league_id)`.

**The phase seam.** Sleeper publishes brackets that `classify_playoff_phases` interprets. Yahoo publishes no bracket resource — its scoreboard marks each matchup with `is_playoffs` and `is_consolation`. That is strictly *more* direct: the flags say what the bracket walk was reconstructing. So `get_phase_map` reads them and never calls `classify_playoff_phases`.

**`get_stats` and `get_players` delegate to Sleeper.** They are NFL-wide, not league-scoped: Sleeper's `/stats/nfl` and `/players/nfl` are public, unauthenticated, and already keyed by the canonical Sleeper player id. Re-deriving them from Yahoo would produce the same numbers through a worse path, and would need a second scoring-settings translation to boot.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_yahoo_adapter_matchups.py`:

```python
import pytest

from sleeper_dynasty.api.yahoo import YahooAdapter


class _FakeAdapter(YahooAdapter):
    def __init__(self, routes, id_map=None):
        super().__init__(access_token="test", id_map=id_map or {})
        self.routes = routes

    async def _get(self, path, **params):
        return self.routes[path]


def _matchup(week, t1, p1, t2, p2, *, playoffs=0, consolation=0):
    def team(key, pts):
        return [
            [{"team_key": f"461.l.1.t.{key}"}],
            {"team_points": {"week": str(week), "total": str(pts)}},
        ]
    return {"matchup": {
        "week": str(week),
        "is_playoffs": str(playoffs),
        "is_consolation": str(consolation),
        "0": {"teams": {"count": 2, "0": {"team": team(t1, p1)},
                        "1": {"team": team(t2, p2)}}},
    }}


def _scoreboard(week, matchups):
    return {"fantasy_content": {"league": [
        {"league_key": "461.l.1"},
        {"scoreboard": {"week": str(week), "0": {"matchups": {
            "count": len(matchups),
            **{str(i): m for i, m in enumerate(matchups)},
        }}}},
    ]}}


@pytest.mark.asyncio
async def test_get_raw_matchups_pairs_rosters_with_a_shared_matchup_id():
    a = _FakeAdapter({
        "/league/461.l.1/scoreboard;week=3": _scoreboard(
            3, [_matchup(3, 1, 110.5, 2, 98.25)]),
    })
    rows = await a.get_raw_matchups("461.l.1", 3)
    assert len(rows) == 2
    assert {r["roster_id"] for r in rows} == {1, 2}
    assert rows[0]["matchup_id"] == rows[1]["matchup_id"]
    assert rows[0]["points"] == pytest.approx(110.5)
    assert rows[1]["points"] == pytest.approx(98.25)


@pytest.mark.asyncio
async def test_matchup_ids_are_unique_across_the_week():
    a = _FakeAdapter({
        "/league/461.l.1/scoreboard;week=3": _scoreboard(
            3, [_matchup(3, 1, 100, 2, 90), _matchup(3, 3, 80, 4, 70)]),
    })
    rows = await a.get_raw_matchups("461.l.1", 3)
    assert len({r["matchup_id"] for r in rows}) == 2


@pytest.mark.asyncio
async def test_an_empty_week_is_an_empty_list_not_an_error():
    a = _FakeAdapter({"/league/461.l.1/scoreboard;week=17": _scoreboard(17, [])})
    assert await a.get_raw_matchups("461.l.1", 17) == []


@pytest.mark.asyncio
async def test_phase_map_marks_playoff_matchups():
    class _Lg:
        league_id = "461.l.1"
        playoff_week_start = 15
        season = 2025

    a = _FakeAdapter({
        f"/league/461.l.1/scoreboard;week={w}": _scoreboard(w, [])
        for w in range(15, 19)
    } | {
        "/league/461.l.1/scoreboard;week=15": _scoreboard(
            15, [_matchup(15, 1, 100, 2, 90, playoffs=1)]),
    })
    phases = await a.get_phase_map(_Lg())
    assert phases[(15, 1)] == "playoff"
    assert phases[(15, 2)] == "playoff"


@pytest.mark.asyncio
async def test_consolation_matchups_are_toilet_not_playoff():
    """A consolation game is a losers-bracket game. Counting it as playoff
    would credit Playoff Points for a game with no title path."""
    class _Lg:
        league_id = "461.l.1"
        playoff_week_start = 15
        season = 2025

    a = _FakeAdapter({
        f"/league/461.l.1/scoreboard;week={w}": _scoreboard(w, [])
        for w in range(15, 19)
    } | {
        "/league/461.l.1/scoreboard;week=15": _scoreboard(
            15, [_matchup(15, 5, 70, 6, 60, playoffs=1, consolation=1)]),
    })
    phases = await a.get_phase_map(_Lg())
    assert phases[(15, 5)] == "toilet"
    assert phases[(15, 6)] == "toilet"


@pytest.mark.asyncio
async def test_regular_season_weeks_are_absent_from_the_phase_map():
    """Weeks before playoff_start are classified by the caller, not here."""
    class _Lg:
        league_id = "461.l.1"
        playoff_week_start = 15
        season = 2025

    a = _FakeAdapter({
        f"/league/461.l.1/scoreboard;week={w}": _scoreboard(
            w, [_matchup(w, 1, 100, 2, 90)]) for w in range(15, 19)
    })
    phases = await a.get_phase_map(_Lg())
    assert (3, 1) not in phases


@pytest.mark.asyncio
async def test_player_ids_in_a_matchup_are_translated_to_sleeper_ids():
    """The identity contract: no Yahoo id may cross this boundary."""
    a = _FakeAdapter({}, id_map={"31002": "4034"})
    assert a.to_sleeper_id("31002") == "4034"
    assert a.to_sleeper_id("99999") is None


@pytest.mark.asyncio
async def test_yahoo_reports_no_traded_picks():
    """Yahoo has no future-pick trading. Empty, and the evidence-based
    future_picks capability then reads False on its own."""
    assert await _FakeAdapter({}).get_traded_picks("461.l.1") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_adapter_matchups.py -v`
Expected: FAIL — `AttributeError: 'YahooAdapter' object has no attribute 'get_raw_matchups'`

- [ ] **Step 3: Add the matchup half to the adapter**

Append these methods to `YahooAdapter` in `src/sleeper_dynasty/api/yahoo.py`:

```python
    # ---- matchups and phases -------------------------------------------

    async def _scoreboard(self, league_id: str, week: int) -> list[dict]:
        """Flattened matchup resources for one league-week."""
        from sleeper_dynasty.api.yahoo_json import collection, merge_fragments, unwrap

        payload = await self._get(f"/league/{league_id}/scoreboard;week={week}")
        node = merge_fragments(unwrap(payload, "fantasy_content", "league"))
        board = merge_fragments(node.get("scoreboard"))
        return [
            merge_fragments(m.get("matchup"))
            for m in collection(merge_fragments(board).get("matchups"))
        ]

    @staticmethod
    def _matchup_teams(matchup: dict) -> list[tuple[int, float]]:
        """[(roster_id, points)] for the (usually two) sides of a matchup."""
        from sleeper_dynasty.api.yahoo_json import collection, merge_fragments

        out: list[tuple[int, float]] = []
        for entry in collection(merge_fragments(matchup).get("teams")):
            team = merge_fragments(entry.get("team"))
            pts = merge_fragments(team.get("team_points"))
            out.append((
                roster_id_for(team.get("team_key")),
                float(pts.get("total") or 0.0),
            ))
        return out

    async def get_raw_matchups(self, league_id: str, week: int) -> list[dict]:
        """Per-roster rows for one week, in the shape grader_io consumes.

        ``starters``/``players``/``players_points`` are left empty: Yahoo
        serves per-player scoring from a separate per-team roster resource
        (one request per team per week — 12x18 for a season), and the engine
        already derives per-player points from Sleeper's public NFL stats
        keyed by the canonical player id. Lineup efficiency (lineup_skill) is
        the one signal that needs real starters; it degrades to neutral
        without them, which is the honest reading rather than a fabricated
        one. Filling this in is the first follow-on if Yahoo lineup grading
        turns out to matter.
        """
        rows: list[dict] = []
        for idx, matchup in enumerate(await self._scoreboard(league_id, week), start=1):
            teams = self._matchup_teams(matchup)
            if len(teams) != 2:
                continue
            for roster_id, points in teams:
                rows.append({
                    "matchup_id": idx,
                    "roster_id": roster_id,
                    "points": points,
                    "starters": [],
                    "players": [],
                    "players_points": {},
                })
        return rows

    async def get_phase_map(self, league) -> dict:
        """(week, roster_id) -> "playoff" | "toilet".

        Yahoo publishes no bracket resource — the scoreboard marks each
        matchup ``is_playoffs`` and ``is_consolation`` directly, which is what
        Sleeper's bracket walk was reconstructing. A consolation game is a
        losers-bracket game: counting it as playoff would credit Playoff
        Points for a game with no title path.
        """
        out: dict[tuple[int, int], str] = {}
        start = int(getattr(league, "playoff_week_start", 15) or 15)
        for week in range(start, 19):
            for matchup in await self._scoreboard(league.league_id, week):
                if str(matchup.get("is_playoffs") or "0") not in ("1", "true"):
                    continue
                consolation = str(
                    matchup.get("is_consolation") or "0") in ("1", "true")
                phase = "toilet" if consolation else "playoff"
                for roster_id, _pts in self._matchup_teams(matchup):
                    out[(week, roster_id)] = phase
        return out

    async def get_traded_picks(self, league_id: str) -> list:
        """Always []. Yahoo has no future-pick trading.

        Returning [] rather than raising is what lets the evidence-based
        capability model do its job: no pick ever appears in a trade, so
        ``future_picks`` reads False without any Yahoo-specific branch.
        """
        return []

    # ---- NFL-wide data, delegated to Sleeper's public API ---------------

    async def get_players(self) -> dict:
        """The player universe, keyed by Sleeper player_id.

        Delegated: Sleeper's /players/nfl is public, unauthenticated, and
        already keyed by this app's canonical id. Re-deriving it from Yahoo
        would produce the same players behind an auth wall under a second
        identity scheme.
        """
        return await self._sleeper().get_players()

    async def get_stats(self, season: int, week: int) -> dict:
        """Raw NFL stats for one week, keyed by Sleeper player_id. Delegated
        for the same reason as get_players — and because deriving them from
        Yahoo would need a second scoring-settings translation."""
        return await self._sleeper().get_stats(season, week)

    async def get_nfl_state(self) -> dict:
        """Current NFL season/week. Delegated; it is league-independent."""
        return await self._sleeper().get_nfl_state()

    def _sleeper(self):
        """Lazily-built Sleeper client for the NFL-wide public endpoints."""
        if getattr(self, "_sleeper_client", None) is None:
            from sleeper_dynasty.api.sleeper import SleeperClient
            self._sleeper_client = SleeperClient()
        return self._sleeper_client
```

Extend `close` so the delegated client is released too — replace the existing `close`:

```python
    async def close(self) -> None:
        await self._client.aclose()
        if getattr(self, "_sleeper_client", None) is not None:
            await self._sleeper_client.close()
            self._sleeper_client = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_adapter_matchups.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Check against the recorded scoreboard fixture**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && python -c "
import asyncio, json, pathlib
from sleeper_dynasty.api.yahoo import YahooAdapter
F = pathlib.Path('tests/fixtures/yahoo')

class Replay(YahooAdapter):
    def __init__(self):
        super().__init__(access_token='x', id_map={})
    async def _get(self, path, **kw):
        return json.loads((F / 'scoreboard_wk1.json').read_text())

async def main():
    rows = await Replay().get_raw_matchups('x', 1)
    print(len(rows), 'rows')
    for r in rows:
        print(' ', r['matchup_id'], r['roster_id'], r['points'])

asyncio.run(main())
"`
Expected: one row per team (12 for a 12-team league), paired matchup ids, and real week-1 scores. **Zero rows means the scoreboard nesting differs from the synthetic fixture** — fix `_scoreboard`/`_matchup_teams` against the real payload and add a fixture-backed test.

- [ ] **Step 6: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/api/yahoo.py tests/test_yahoo_adapter_matchups.py
git commit -m "feat: YahooAdapter matchups and phase map from scoreboard flags"
```

---

### Task 8: `YahooAdapter` — trades, drops, and draft results

**Files:**
- Modify: `src/sleeper_dynasty/api/yahoo.py`
- Test: `tests/test_yahoo_adapter_transactions.py`

**Interfaces:**
- Consumes: Task 6/7's `YahooAdapter`.
- Produces: `YahooAdapter.get_trade_transactions`, `.get_drop_transactions`, `.get_draft_results`. After this task `isinstance(YahooAdapter(...), LeaguePlatform)` is True.

**`services/refresh_delta.py` needs no change.** The spec lists it as a seam ("Sleeper `transaction_id`" → "Yahoo `transaction_key`"), but `new_transaction_ids` keys on `trade.transaction_id` off the *resolved* trade, and this task emits the Yahoo `transaction_key` into exactly that field. Yahoo transaction keys are stable and unique, so incremental refresh's delta detection works untouched. The `test_a_trade_becomes_the_sleeper_transaction_shape` assertion on `transaction_id` is what pins that.

**The shape to hit.** `engine/trade_history.normalize_trade` consumes the Sleeper transaction encoding: `transaction_id`, `roster_ids`, `adds` (`{player_id: dest_roster_id}`), `drops` (`{player_id: src_roster_id}`), `draft_picks`, `waiver_budget`, `created` (epoch **ms**), `leg` (week). Yahoo's `transaction` carries `transaction_key`, `type`, `status`, `timestamp` (epoch **seconds**), and a `players` collection where each player has a `transaction_data` block naming `source_team_key` and `destination_team_key`. Emit the Sleeper shape so `normalize_trade` needs no change.

**Yahoo gives no week on a transaction.** Only a timestamp. `week` (`leg`) is derived by comparing that timestamp to the season's week boundaries — and the honest simple version is to use the league's current week for in-season trades and 0 otherwise, then let `traded_at` carry the real precision. Every downstream consumer that matters (production tenure, timeline, story dating) reads `traded_at`, not `week`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_yahoo_adapter_transactions.py`:

```python
import pytest

from sleeper_dynasty.api.yahoo import YahooAdapter


class _FakeAdapter(YahooAdapter):
    def __init__(self, routes, id_map=None):
        super().__init__(access_token="test", id_map=id_map or {})
        self.routes = routes

    async def _get(self, path, **params):
        return self.routes[path]


def _player(yahoo_id, src, dest):
    return {"player": [
        [{"player_key": f"461.p.{yahoo_id}"}, {"player_id": str(yahoo_id)}],
        {"transaction_data": [{
            "type": "trade",
            "source_team_key": f"461.l.1.t.{src}",
            "destination_team_key": f"461.l.1.t.{dest}",
        }]},
    ]}


def _tx(key, type_, status, ts, players, *, traders=None):
    body = {
        "transaction_key": key, "transaction_id": key.rsplit(".", 1)[-1],
        "type": type_, "status": status, "timestamp": str(ts),
    }
    if traders:
        body["trader_team_key"] = f"461.l.1.t.{traders[0]}"
        body["tradee_team_key"] = f"461.l.1.t.{traders[1]}"
    return {"transaction": [
        body,
        {"players": {"count": len(players),
                     **{str(i): p for i, p in enumerate(players)}}},
    ]}


def _txs(items):
    return {"fantasy_content": {"league": [
        {"league_key": "461.l.1"},
        {"transactions": {"count": len(items),
                          **{str(i): t for i, t in enumerate(items)}}},
    ]}}


@pytest.mark.asyncio
async def test_a_trade_becomes_the_sleeper_transaction_shape():
    a = _FakeAdapter(
        {"/league/461.l.1/transactions;types=trade": _txs([
            _tx("461.l.1.tr.9", "trade", "successful", 1730000000,
                [_player(31002, 1, 2), _player(31003, 2, 1)], traders=(1, 2)),
        ])},
        id_map={"31002": "4034", "31003": "5000"},
    )
    out = await a.get_trade_transactions("461.l.1")
    assert len(out) == 1
    tx = out[0]
    assert tx["transaction_id"] == "461.l.1.tr.9"
    assert sorted(tx["roster_ids"]) == [1, 2]
    assert tx["adds"] == {"4034": 2, "5000": 1}
    assert tx["drops"] == {"4034": 1, "5000": 2}
    assert tx["draft_picks"] == []
    assert tx["waiver_budget"] == []


@pytest.mark.asyncio
async def test_timestamp_seconds_become_epoch_milliseconds():
    """normalize_trade divides `created` by 1000. Seconds passed through
    unchanged would date every Yahoo trade to January 1970."""
    a = _FakeAdapter(
        {"/league/461.l.1/transactions;types=trade": _txs([
            _tx("461.l.1.tr.9", "trade", "successful", 1730000000,
                [_player(31002, 1, 2)], traders=(1, 2)),
        ])},
        id_map={"31002": "4034"},
    )
    out = await a.get_trade_transactions("461.l.1")
    assert out[0]["created"] == 1730000000 * 1000

    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(out[0]["created"] / 1000.0, tz=timezone.utc)
    assert dt.year == 2024


@pytest.mark.asyncio
async def test_unmapped_players_are_dropped_and_do_not_poison_the_trade():
    """A Yahoo id with no Sleeper counterpart must never reach the engine —
    it would be priced at zero and silently distort the grade."""
    a = _FakeAdapter(
        {"/league/461.l.1/transactions;types=trade": _txs([
            _tx("461.l.1.tr.9", "trade", "successful", 1730000000,
                [_player(31002, 1, 2), _player(99999, 2, 1)], traders=(1, 2)),
        ])},
        id_map={"31002": "4034"},
    )
    out = await a.get_trade_transactions("461.l.1")
    assert out[0]["adds"] == {"4034": 2}
    assert "99999" not in out[0]["adds"]


@pytest.mark.asyncio
async def test_non_successful_trades_are_excluded():
    a = _FakeAdapter(
        {"/league/461.l.1/transactions;types=trade": _txs([
            _tx("461.l.1.tr.9", "trade", "pending", 1730000000,
                [_player(31002, 1, 2)], traders=(1, 2)),
        ])},
        id_map={"31002": "4034"},
    )
    assert await a.get_trade_transactions("461.l.1") == []


@pytest.mark.asyncio
async def test_no_transactions_is_an_empty_list():
    a = _FakeAdapter({"/league/461.l.1/transactions;types=trade": _txs([])})
    assert await a.get_trade_transactions("461.l.1") == []


@pytest.mark.asyncio
async def test_drops_come_from_the_non_trade_feed():
    a = _FakeAdapter(
        {"/league/461.l.1/transactions;types=add,drop": _txs([
            _tx("461.l.1.tr.20", "drop", "successful", 1730000000,
                [_player(31002, 3, 0)]),
        ])},
        id_map={"31002": "4034"},
    )
    out = await a.get_drop_transactions("461.l.1")
    assert len(out) == 1
    assert out[0]["drops"] == {"4034": 3}
    assert out[0]["type"] == "drop"


@pytest.mark.asyncio
async def test_an_add_without_a_drop_contributes_no_drop_row():
    a = _FakeAdapter(
        {"/league/461.l.1/transactions;types=add,drop": _txs([
            _tx("461.l.1.tr.21", "add", "successful", 1730000000,
                [_player(31002, 0, 3)]),
        ])},
        id_map={"31002": "4034"},
    )
    assert await a.get_drop_transactions("461.l.1") == []


@pytest.mark.asyncio
async def test_draft_results_map_onto_the_sleeper_pick_shape():
    a = _FakeAdapter(
        {"/league/461.l.1/draftresults": {"fantasy_content": {"league": [
            {"league_key": "461.l.1", "season": "2025"},
            {"draft_results": {"count": 2,
                "0": {"draft_result": {"pick": "1", "round": "1",
                                       "team_key": "461.l.1.t.4",
                                       "player_key": "461.p.31002"}},
                "1": {"draft_result": {"pick": "2", "round": "1",
                                       "team_key": "461.l.1.t.7",
                                       "player_key": "461.p.31003"}}}},
        ]}}},
        id_map={"31002": "4034", "31003": "5000"},
    )
    out = await a.get_draft_results("461.l.1")
    assert len(out) == 2
    first = out[0]
    assert first["round"] == 1
    assert first["pick_no"] == 1
    assert first["draft_slot"] == 1
    assert first["roster_id"] == 4
    assert first["player_id"] == "4034"
    assert first["season"] == 2025


@pytest.mark.asyncio
async def test_draft_slot_is_the_position_within_the_round():
    """draft_slot drives engine/draft_signals tiering. Using the overall pick
    number would put every round-2 pick in a nonexistent tier."""
    picks = {str(i): {"draft_result": {
        "pick": str(i + 1), "round": "1" if i < 12 else "2",
        "team_key": f"461.l.1.t.{(i % 12) + 1}",
        "player_key": f"461.p.{31000 + i}"}} for i in range(24)}
    a = _FakeAdapter(
        {"/league/461.l.1/draftresults": {"fantasy_content": {"league": [
            {"league_key": "461.l.1", "season": "2025"},
            {"draft_results": {"count": 24, **picks}},
        ]}}},
        id_map={str(31000 + i): str(4000 + i) for i in range(24)},
    )
    out = await a.get_draft_results("461.l.1")
    round_two = [p for p in out if p["round"] == 2]
    assert [p["draft_slot"] for p in round_two] == list(range(1, 13))


@pytest.mark.asyncio
async def test_undrafted_or_unmapped_picks_are_skipped():
    a = _FakeAdapter(
        {"/league/461.l.1/draftresults": {"fantasy_content": {"league": [
            {"league_key": "461.l.1", "season": "2025"},
            {"draft_results": {"count": 2,
                "0": {"draft_result": {"pick": "1", "round": "1",
                                       "team_key": "461.l.1.t.4",
                                       "player_key": "461.p.99999"}},
                "1": {"draft_result": {"pick": "2", "round": "1",
                                       "team_key": "461.l.1.t.7"}}}},
        ]}}},
        id_map={},
    )
    assert await a.get_draft_results("461.l.1") == []


def test_yahoo_adapter_satisfies_the_protocol():
    from sleeper_dynasty.api.platform import LeaguePlatform
    assert isinstance(YahooAdapter(access_token="x"), LeaguePlatform)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_adapter_transactions.py -v`
Expected: FAIL — `AttributeError: 'YahooAdapter' object has no attribute 'get_trade_transactions'`

- [ ] **Step 3: Add the transaction half to the adapter**

Append to `YahooAdapter` in `src/sleeper_dynasty/api/yahoo.py`:

```python
    # ---- transactions and drafts ---------------------------------------

    async def _transactions(self, league_id: str, types: str) -> list[dict]:
        """Flattened transaction resources of the given ``types`` filter."""
        from sleeper_dynasty.api.yahoo_json import collection, merge_fragments, unwrap

        payload = await self._get(f"/league/{league_id}/transactions;types={types}")
        node = merge_fragments(unwrap(payload, "fantasy_content", "league"))
        return [
            merge_fragments(t.get("transaction"))
            for t in collection(node.get("transactions"))
        ]

    def _movements(self, tx: dict) -> list[tuple[str, int, int]]:
        """[(sleeper_player_id, source_roster_id, dest_roster_id)] for one tx.

        Players with no Sleeper counterpart are dropped: an unmapped id would
        reach the engine, price at zero, and silently distort the grade. A
        missing player is visible in the coverage warning; a zero-priced
        phantom is not.
        """
        from sleeper_dynasty.api.yahoo_json import collection, merge_fragments

        out: list[tuple[str, int, int]] = []
        for entry in collection(merge_fragments(tx).get("players")):
            player = merge_fragments(entry.get("player"))
            sleeper_id = self.to_sleeper_id(player.get("player_id"))
            if not sleeper_id:
                log.debug("unmapped yahoo player %s", player.get("player_key"))
                continue
            data = merge_fragments(player.get("transaction_data"))
            out.append((
                sleeper_id,
                roster_id_for(data.get("source_team_key")),
                roster_id_for(data.get("destination_team_key")),
            ))
        return out

    async def get_trade_transactions(self, league_id: str) -> list[dict]:
        """Completed trades in the Sleeper transaction shape.

        Emitting Sleeper's encoding rather than a third neutral one means
        ``engine/trade_history.normalize_trade`` needs no change: Sleeper is
        the reference shape and this adapter translates into it.
        """
        out: list[dict] = []
        for tx in await self._transactions(league_id, "trade"):
            if str(tx.get("status") or "") != "successful":
                continue
            adds: dict[str, int] = {}
            drops: dict[str, int] = {}
            rosters: set[int] = set()
            for sleeper_id, src, dest in self._movements(tx):
                if dest:
                    adds[sleeper_id] = dest
                    rosters.add(dest)
                if src:
                    drops[sleeper_id] = src
                    rosters.add(src)
            if not adds and not drops:
                continue
            for key in ("trader_team_key", "tradee_team_key"):
                rid = roster_id_for(tx.get(key))
                if rid:
                    rosters.add(rid)
            out.append({
                "transaction_id": str(tx.get("transaction_key") or ""),
                "type": "trade",
                "status": "complete",
                "roster_ids": sorted(rosters),
                "adds": adds,
                "drops": drops,
                # Yahoo has no future-pick trading and no FAAB-in-trade.
                "draft_picks": [],
                "waiver_budget": [],
                # Yahoo timestamps are epoch SECONDS; normalize_trade divides
                # `created` by 1000. Passing seconds through would date every
                # Yahoo trade to January 1970.
                "created": int(tx.get("timestamp") or 0) * 1000,
                # Yahoo does not stamp a week on a transaction. Everything
                # that matters downstream (tenure, timeline, story dating)
                # reads traded_at, which carries the real precision.
                "leg": 0,
            })
        return out

    async def get_drop_transactions(self, league_id: str) -> list[dict]:
        """Non-trade transactions that dropped a player."""
        out: list[dict] = []
        for tx in await self._transactions(league_id, "add,drop"):
            if str(tx.get("status") or "") != "successful":
                continue
            drops = {
                sleeper_id: src
                for sleeper_id, src, _dest in self._movements(tx)
                if src
            }
            if not drops:
                continue
            out.append({
                "transaction_id": str(tx.get("transaction_key") or ""),
                "type": "drop",
                "status": "complete",
                "drops": drops,
                "adds": {},
                "created": int(tx.get("timestamp") or 0) * 1000,
                "leg": 0,
            })
        return out

    async def get_draft_results(self, league_id: str) -> list[dict]:
        """One row per pick, in the shape engine/draft_signals consumes.

        ``draft_slot`` is the position WITHIN the round, not the overall pick
        number — the engine tiers picks by slot, and an overall number would
        put every round-2 pick in a tier that does not exist.
        """
        from sleeper_dynasty.api.yahoo_json import collection, merge_fragments, unwrap

        payload = await self._get(f"/league/{league_id}/draftresults")
        node = merge_fragments(unwrap(payload, "fantasy_content", "league"))
        season = int(node.get("season") or 0)

        rows: list[dict] = []
        seen_in_round: dict[int, int] = {}
        for entry in collection(node.get("draft_results")):
            pick = merge_fragments(entry.get("draft_result") or entry)
            player_key = str(pick.get("player_key") or "")
            yahoo_pid = player_key.rsplit(".p.", 1)[-1] if ".p." in player_key else ""
            sleeper_id = self.to_sleeper_id(yahoo_pid)
            if not sleeper_id:
                continue
            rnd = int(pick.get("round") or 0)
            seen_in_round[rnd] = seen_in_round.get(rnd, 0) + 1
            rows.append({
                "round": rnd,
                "pick_no": int(pick.get("pick") or 0),
                "draft_slot": seen_in_round[rnd],
                "roster_id": roster_id_for(pick.get("team_key")),
                "player_id": sleeper_id,
                "season": season,
            })
        return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_yahoo_adapter_transactions.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Check against the recorded transaction and draft fixtures**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && python -c "
import asyncio, json, pathlib
from sleeper_dynasty.api.yahoo import YahooAdapter
from sleeper_dynasty.api.yahoo_ids import build_yahoo_to_sleeper
from sleeper_dynasty.engine.injury_data import _fetch_csv_rows, _IDS_URL
F = pathlib.Path('tests/fixtures/yahoo')
ids = build_yahoo_to_sleeper(_fetch_csv_rows(_IDS_URL))

class Replay(YahooAdapter):
    def __init__(self):
        super().__init__(access_token='x', id_map=ids)
    async def _get(self, path, **kw):
        name = 'transactions_trades' if 'types=trade' in path else (
               'draftresults' if 'draftresults' in path else 'transactions_all')
        return json.loads((F / f'{name}.json').read_text())

async def main():
    a = Replay()
    trades = await a.get_trade_transactions('x')
    print(len(trades), 'trades')
    for t in trades[:5]:
        print(' ', t['transaction_id'], t['roster_ids'], 'adds', t['adds'])
    picks = await a.get_draft_results('x')
    print(len(picks), 'picks; first:', picks[:2])

asyncio.run(main())
"`
Expected: the real trade count for your league with plausible roster ids and Sleeper player ids, and a full draft (typically 150-180 picks for a 12-team league). **A pick count well below the real draft size means the id map is missing players** — check how many unmapped ids were skipped before assuming the parser is wrong.

- [ ] **Step 6: Run the full backend suites**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/ -q && pytest api/tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/api/yahoo.py tests/test_yahoo_adapter_transactions.py
git commit -m "feat: YahooAdapter trades, drops, and draft results"
```

---

### Task 9: Route the grader by platform and read a real Yahoo league

**Files:**
- Create: `api/app/services/platform_client.py`
- Modify: `api/app/services/grader_io.py` (the bundle's bracket fields)
- Modify: `api/app/routes/refresh.py:31`
- Test: `api/tests/test_platform_client.py`

**Interfaces:**
- Consumes: `platform_for_league_id` (Task 2), `YahooAdapter` (Tasks 6-8), `SleeperClient` (Task 3).
- Produces: `client_for_league(league_id, *, access_token=None) -> LeaguePlatform` and `YahooCredentialsMissing`.

**Dev-token only.** `client_for_league` takes an explicit `access_token` and, when none is passed, reads `YAHOO_DEV_ACCESS_TOKEN` from the environment. Plan 2 replaces that fallback with the connection store. The env fallback is **refused when the app is not in debug mode** so a dev token can never become production's auth story by accident.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_platform_client.py`:

```python
import pytest

from app.services.platform_client import YahooCredentialsMissing, client_for_league
from sleeper_dynasty.api.sleeper import SleeperClient
from sleeper_dynasty.api.yahoo import YahooAdapter


def test_a_sleeper_id_gets_the_sleeper_client():
    assert isinstance(client_for_league("1048178156025733120"), SleeperClient)


def test_a_yahoo_key_with_an_explicit_token_gets_the_yahoo_adapter():
    c = client_for_league("461.l.123456", access_token="tok")
    assert isinstance(c, YahooAdapter)


def test_a_yahoo_key_without_a_token_raises_a_named_error():
    """Not a generic KeyError deep in a request — the caller needs to tell the
    user to reconnect."""
    with pytest.raises(YahooCredentialsMissing, match="461.l.123456"):
        client_for_league("461.l.123456")


def test_the_dev_token_env_fallback_is_refused_outside_debug(monkeypatch):
    """A dev token must never become production's auth story by accident."""
    monkeypatch.setenv("YAHOO_DEV_ACCESS_TOKEN", "devtok")
    monkeypatch.setattr(
        "app.services.platform_client._debug_enabled", lambda: False)
    with pytest.raises(YahooCredentialsMissing):
        client_for_league("461.l.123456")


def test_the_dev_token_env_fallback_works_in_debug(monkeypatch):
    monkeypatch.setenv("YAHOO_DEV_ACCESS_TOKEN", "devtok")
    monkeypatch.setattr(
        "app.services.platform_client._debug_enabled", lambda: True)
    assert isinstance(client_for_league("461.l.123456"), YahooAdapter)


def test_an_unrecognized_id_raises_value_error():
    with pytest.raises(ValueError, match="unrecognized league id"):
        client_for_league("not-a-league")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_platform_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.platform_client'`

- [ ] **Step 3: Write the factory**

Create `api/app/services/platform_client.py`:

```python
"""Pick the right ingestion client for a league id.

One place decides which platform a league belongs to, so the grader, the
refresh route, and the scheduler all agree. The platform is derived from the
id's shape (see api/platform.py) — no stored column, no migration.

Credentials: Sleeper needs none. Yahoo needs an access token, supplied by the
caller. Until the connection store exists, a developer token can be supplied
through YAHOO_DEV_ACCESS_TOKEN — but only in debug mode, so a dev token cannot
quietly become production's auth story.
"""

from __future__ import annotations

import logging
import os

from sleeper_dynasty.api.platform import (
    PLATFORM_YAHOO, platform_for_league_id,
)

log = logging.getLogger(__name__)

DEV_TOKEN_ENV = "YAHOO_DEV_ACCESS_TOKEN"


class YahooCredentialsMissing(RuntimeError):
    """No usable Yahoo access token for this league.

    Distinct from a generic error so the caller can surface *reconnect
    required* rather than a stack trace. The auth plan turns this into a real
    user-facing state.
    """


def _debug_enabled() -> bool:
    try:
        from app.config import get_settings
        return bool(getattr(get_settings(), "debug", False))
    except Exception:
        return False


def client_for_league(league_id: str, *, access_token: str | None = None):
    """A LeaguePlatform for ``league_id``. Raises on an unusable id or creds."""
    platform = platform_for_league_id(league_id)
    if platform != PLATFORM_YAHOO:
        from sleeper_dynasty.api.sleeper import SleeperClient
        return SleeperClient()

    token = access_token
    if not token and _debug_enabled():
        token = os.environ.get(DEV_TOKEN_ENV)
        if token:
            log.warning(
                "using %s for league %s — debug only, never production",
                DEV_TOKEN_ENV, league_id,
            )
    if not token:
        raise YahooCredentialsMissing(
            f"no Yahoo access token for league {league_id}; "
            "the account must reconnect Yahoo"
        )

    from sleeper_dynasty.api.yahoo import YahooAdapter
    return YahooAdapter(access_token=token)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_platform_client.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Use the phase map in the matchup bundle**

`api/app/services/grader_io.py:166-167` stores raw brackets on the bundle, and downstream code calls `classify_playoff_phases` on them. Yahoo has no brackets. Replace lines 166-167:

```python
    winners = await client.get_winners_bracket(lg.league_id)
    losers = await client.get_losers_bracket(lg.league_id)
```

with:

```python
    # Both platforms produce a phase map; only Sleeper produces brackets.
    # Store the map (the thing every consumer actually reads) and keep the
    # raw brackets only when the client has them, for the sealed-league cache
    # and for debugging a misclassified week.
    phase_map = await client.get_phase_map(lg)
    winners = (await client.get_winners_bracket(lg.league_id)
               if hasattr(client, "get_winners_bracket") else [])
    losers = (await client.get_losers_bracket(lg.league_id)
              if hasattr(client, "get_losers_bracket") else [])
```

Add `"phase_map": {f"{w}:{r}": p for (w, r), p in phase_map.items()},` to the `bundle` dict beside `"winners_bracket"` (JSON keys must be strings, so the tuple key is flattened).

Then find every consumer of the bundle's brackets:

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && grep -rn "winners_bracket\|classify_playoff_phases" api/app/ src/sleeper_dynasty/ | grep -v "api/sleeper.py"`

For each consumer that calls `classify_playoff_phases(bundle["winners_bracket"], …)`, prefer the stored map when present:

```python
    stored = bundle.get("phase_map") or {}
    if stored:
        phases = {
            (int(k.split(":")[0]), int(k.split(":")[1])): v
            for k, v in stored.items()
        }
    else:
        phases = classify_playoff_phases(
            bundle["winners_bracket"], bundle["losers_bracket"],
            bundle["playoff_week_start"], bundle.get("playoff_round_type", 0),
        )
```

The `else` branch keeps every already-cached sealed-league bundle working — they have no `phase_map` until their next rebuild.

- [ ] **Step 6: Route the refresh endpoint**

In `api/app/routes/refresh.py:31`, replace:

```python
        client = SleeperClient()
```

with:

```python
        from app.services.platform_client import (
            YahooCredentialsMissing, client_for_league,
        )
        try:
            client = client_for_league(league_id)
        except YahooCredentialsMissing as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
```

Confirm `HTTPException` is imported in that module; add it to the `fastapi` import if not.

- [ ] **Step 7: Run the full backend suites**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/ -q && pytest api/tests/ -q`
Expected: PASS. A failure in a bracket/phase test means Step 5's consumer rewrite missed a call site — re-run the grep.

- [ ] **Step 8: Read a real Yahoo league end to end**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
export YAHOO_DEV_ACCESS_TOKEN=...          # fresh; it lasts one hour
export TRADE_GRADER_DEBUG=1
make dev-api
```

In a second terminal, trigger a refresh for the Yahoo league key and watch the SSE stream:

```bash
curl -N "http://localhost:8000/api/league/461.l.123456/refresh"
```

Confirm, in order:
- the chain walk finds every season (`renew` followed back to origin)
- the grade completes without error and writes `chain_461.l.123456.json`
- `capabilities.format` is `redraft` or `keeper` — **never `dynasty`**
- `capabilities.future_picks` is `false` (no pick ever appeared in a trade)
- the trade count matches what the league actually has
- Franchise ratings are produced under `redraft_led` or `keeper_led`

Check the written entry directly:

```bash
python -c "
import json, pathlib, os
p = pathlib.Path(os.path.expanduser('~/.sleeper-dynasty/cache/chain_461.l.123456.json'))
e = json.loads(p.read_text())
print('capabilities:', e.get('capabilities'))
print('trades:', len(e.get('resolved_trades') or []))
print('owners:', len(e.get('grades') or {}))
"
```

**Expected failure mode to watch for:** if the redraft path itself misbehaves (a wrong-looking grade, an empty pillar), suspect it before the adapter. Per the redraft plan's "Post-merge outstanding", **no redraft league has ever been run through this app end to end** — this is likely the first time that path executes against a real league of any platform.

- [ ] **Step 9: Update the project docs**

Add a bullet to `CLAUDE.md`'s "Key conventions" list, in the same voice as its neighbours:

```markdown
- **Platform ingestion protocol:** `api/platform.py::LeaguePlatform` is the contract every platform implements — `SleeperClient` and `YahooAdapter` are two implementations of one interface, and anything not on the protocol is unavailable to the engine. Platform routing is derived from the league id's **shape** (`platform_for_league_id`: all-digits → Sleeper, `.l.` → Yahoo), so no cache filename, membership row, or URL carries a discriminator. Three normalizations matter: the protocol asks for a **phase map** rather than brackets (Sleeper derives one from winners/losers brackets; Yahoo's scoreboard marks `is_playoffs`/`is_consolation` directly, and a consolation game is `toilet`, never `playoff`); trades and drops are **separate** calls (Sleeper filters one mixed feed, Yahoo has typed collections); and **every `player_id` crossing the boundary is a Sleeper id** — `api/yahoo_ids.py` maps `yahoo_id`→`sleeper_id` off DynastyProcess's `db_playerids.csv`, and an unmapped player is **dropped, never zero-priced**. `League.format` (`dynasty`|`keeper`|`redraft`) replaced the Sleeper-specific `league_type` int; each adapter maps its own encoding onto it, which is what lets `derive_capabilities` stay platform-free. A Yahoo league is **never dynasty** — Yahoo cannot trade future picks. Yahoo's NFL-wide reads (`get_players`/`get_stats`/`get_nfl_state`) delegate to Sleeper's public endpoints, which are already keyed by the canonical id. **Yahoo ingestion is dev-token only until the auth plan lands** (`services/platform_client.py`, `YAHOO_DEV_ACCESS_TOKEN`, debug-mode-gated).
```

Update `README.md` where it describes supported leagues: Sleeper dynasty/keeper/redraft, plus Yahoo redraft/keeper behind a developer token.

- [ ] **Step 10: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add api/app/services/platform_client.py api/app/services/grader_io.py api/app/routes/refresh.py api/tests/test_platform_client.py CLAUDE.md README.md
git commit -m "feat: route ingestion by platform; read Yahoo leagues with a dev token"
```

---

## Known gaps this plan deliberately leaves open

Recorded so a reviewer does not read them as oversights.

- **No per-player lineup data for Yahoo.** `get_raw_matchups` returns empty `starters`/`players`/`players_points` because Yahoo serves them from a per-team-per-week resource (12 x 18 requests per season). The consequence is that **lineup_skill degrades to neutral for Yahoo leagues** — one of four Skill signals. That is the honest reading rather than a fabricated one, but it is a real difference from a Sleeper league and it should be disclosed in the coverage warning when Yahoo ships to users. Filling it in is the first ingestion follow-on.
- **Trade `week` is always 0.** Yahoo stamps no week on a transaction. `traded_at` carries full timestamp precision and every consumer that matters reads it; verify during Step 8 that the timeline and story dating look right, and derive a real week from season boundaries only if something visibly needs it.
- **No Yahoo league discovery.** `routes/me.py` still only discovers Sleeper leagues. Adding Yahoo discovery needs an OAuth'd user, so it belongs to the auth plan.
- **The scheduler cannot refresh a Yahoo league.** `refresh_all_members` builds a bare `SleeperClient` and has no token. It will raise `YahooCredentialsMissing` per-league and log it, isolated by the existing try/except — so a Yahoo league in the cache degrades to manual-refresh-only rather than breaking the loop for everyone. Making it actually work is the auth plan's core deliverable.
- **Redraft grading is still unverified against a real league.** Inherited from the redraft project, not introduced here.

## Verification

Before calling this plan done, run all of it and confirm output:

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
pytest tests/ -q
pytest api/tests/ -q
cd web && npx tsc --noEmit && npx vitest --config tests/vitest.config.ts run
```

Expected: engine ≥ 527 + ~55 new, api ≥ 484 + 6 new, frontend 329 unchanged (this plan touches no frontend code), tsc clean.

Plus the manual end-to-end pass in Task 9 Step 8 — a real Yahoo league walked, graded, and inspected. Unit tests against recorded fixtures cannot catch a wrong-but-plausible grade; only looking at one can.
