> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Provenance-Aware Pick Grading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a traded draft pick resolve to its drafted player in exactly one trade — the one that delivered it to the team that actually drafted with it — and value every other appearance of that pick as a pick, so display, production, and impact stop misattributing a flipped pick's drafted player.

**Architecture:** A new pure provenance pass over normalized trades computes, per pick identity `(original_owner_user_id, season, round)`, which trade is the "resolution trade" (the chronologically last trade that received it). `resolve_assets` upgrades a `PickAsset` to a `PlayerAsset` only in that trade; everywhere else it stays a `PickAsset` annotated with the drafted player for snapshot valuation only. Snapshot valuation gains a pick-value table (parsed from KTC's `PICK` entries, round-level) for picks whose draft hasn't happened. Production/impact logic is unchanged and becomes correct for free because non-resolution picks are no longer `PlayerAsset`s.

**Tech Stack:** Python 3, dataclasses, pytest. Engine code in `src/sleeper_dynasty/`, API wiring in `api/app/services/`. Spec: `docs/superpowers/specs/2026-05-30-provenance-aware-pick-grading-design.md`.

---

## File Structure

- `src/sleeper_dynasty/models/trade.py` — add two optional fields to `PickAsset`.
- `src/sleeper_dynasty/api/ktc.py` — add `build_pick_value_table()` (parse `PICK` entries → `(season, round) -> KTCValue`).
- `src/sleeper_dynasty/engine/trade_history.py` — add `compute_pick_resolution_map()`; thread a resolution map through `resolve_assets` / `_resolve_one_asset`; call both from `build_trade_history`.
- `src/sleeper_dynasty/engine/trade_grader.py` — `_ktc_value`, `grade_snapshot_value`, `grade_trade` accept a `pick_values` table and value `PickAsset`s.
- `api/app/services/grader_io.py` — build the pick-value table in `pull_supporting_data`, return it.
- `api/app/services/grader.py` — pass `pick_values` into `grade_trade`.
- Tests: `tests/test_trade_models.py`, `tests/test_ktc_parser.py`, `tests/test_trade_grader.py`, `tests/test_trade_history.py`.

All `pytest` commands run from the repo root: `/Users/tomkeefe/Code Apps/sleeper-dynasty`.

---

## Task 1: Add drafted-player fields to `PickAsset`

**Files:**
- Modify: `src/sleeper_dynasty/models/trade.py:12-23`
- Test: `tests/test_trade_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_models.py`:

```python
def test_pick_asset_carries_optional_drafted_player():
    from sleeper_dynasty.models.trade import PickAsset

    # Defaults: a bare pick knows nothing about a drafted player.
    bare = PickAsset(season=2025, round=1, original_owner_user_id="u_alice")
    assert bare.drafted_player_id is None
    assert bare.drafted_player_name is None

    # Annotated: a non-resolution pick records what it became, for valuation.
    annotated = PickAsset(
        season=2024,
        round=1,
        original_owner_user_id="u_alice",
        drafted_player_id="p_jayden",
        drafted_player_name="Jayden Daniels",
    )
    assert annotated.drafted_player_id == "p_jayden"
    assert annotated.drafted_player_name == "Jayden Daniels"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_models.py::test_pick_asset_carries_optional_drafted_player -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'drafted_player_id'`

- [ ] **Step 3: Add the fields**

In `src/sleeper_dynasty/models/trade.py`, replace the `PickAsset` body:

```python
@dataclass
class PickAsset:
    """A future or unused draft pick.

    ``original_owner_user_id`` is the stable user_id of whoever originally
    held this pick (i.e., before any trade). This is what determines the
    draft slot once the draft happens.

    ``drafted_player_id`` / ``drafted_player_name`` are populated when the
    pick's draft is complete but this pick is NOT being upgraded to a
    PlayerAsset in this trade (i.e., the team in this trade flipped the
    pick rather than drafting with it). They exist purely so the snapshot
    lens can value the pick at the drafted player's current market value.
    They are intentionally invisible to production/impact, which gate on
    PlayerAsset.
    """

    season: int
    round: int
    original_owner_user_id: str
    drafted_player_id: str | None = None
    drafted_player_name: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_models.py -v`
Expected: PASS (new test plus existing model tests)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/trade.py tests/test_trade_models.py
git commit -m "feat: PickAsset carries optional drafted-player annotation"
```

---

## Task 2: Build the KTC pick-value table

**Files:**
- Modify: `src/sleeper_dynasty/api/ktc.py` (add function + helpers near the bottom)
- Test: `tests/test_ktc_parser.py`

KTC's `playersArray` includes draft-pick entries with `position == "PICK"` and
names like `"2025 Early 1st"`, `"2025 Mid 2nd"`, `"2025 1st"`. These survive
parsing into `KTCValue`s but are discarded later because they match no Sleeper
`player_id`. We parse them into a `(season, round) -> KTCValue` table, averaging
Early/Mid/Late within a round (slot is unknown until standings).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ktc_parser.py`:

```python
def test_build_pick_value_table_groups_and_averages_by_round():
    from sleeper_dynasty.api.ktc import build_pick_value_table
    from sleeper_dynasty.models.player import KTCValue

    def pick(name, sf, one):
        return KTCValue(
            name=name, normalized_name=name.lower(), position="PICK",
            superflex_value=sf, one_qb_value=one,
        )

    values = {
        "a": pick("2025 Early 1st", 6000, 5800),
        "b": pick("2025 Mid 1st", 5000, 4800),
        "c": pick("2025 Late 1st", 4000, 3800),
        "d": pick("2025 Early 2nd", 2400, 2200),
        # A real player must be ignored.
        "e": KTCValue(name="Bijan", normalized_name="bijan", position="RB",
                      superflex_value=7500, one_qb_value=7400),
    }

    table = build_pick_value_table(values)

    # 2025 round 1 = average of early/mid/late = (6000+5000+4000)/3 = 5000.
    assert table[(2025, 1)].superflex_value == 5000
    assert table[(2025, 1)].one_qb_value == 4800  # (5800+4800+3800)/3
    # 2025 round 2 = single entry passes through.
    assert table[(2025, 2)].superflex_value == 2400
    # No player leaked in.
    assert (0, 0) not in table
    assert len(table) == 2


def test_build_pick_value_table_ignores_unparseable_names():
    from sleeper_dynasty.api.ktc import build_pick_value_table
    from sleeper_dynasty.models.player import KTCValue

    values = {
        "x": KTCValue(name="2025 1st", normalized_name="2025 1st", position="PICK",
                      superflex_value=5500, one_qb_value=5300),
        "y": KTCValue(name="Mystery Pick", normalized_name="mystery pick",
                      position="PICK", superflex_value=999, one_qb_value=999),
    }
    table = build_pick_value_table(values)
    # "2025 1st" (no Early/Mid/Late) parses to (2025, 1); "Mystery Pick" is dropped.
    assert table[(2025, 1)].superflex_value == 5500
    assert len(table) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ktc_parser.py::test_build_pick_value_table_groups_and_averages_by_round -v`
Expected: FAIL with `ImportError: cannot import name 'build_pick_value_table'`

- [ ] **Step 3: Implement `build_pick_value_table`**

Add to `src/sleeper_dynasty/api/ktc.py` (imports at top: ensure `import re` and `from sleeper_dynasty.models.player import KTCValue` are present — `KTCValue` is already imported):

```python
import re

# Maps the ordinal word in a KTC pick name ("1st", "2nd", …) to a round number.
_PICK_ORDINALS = {
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
    "5th": 5, "6th": 6, "7th": 7, "8th": 8,
}
# "2025 Early 1st", "2025 Mid 2nd", "2025 Late 3rd", or "2025 1st".
_PICK_NAME_RE = re.compile(
    r"^(?P<year>\d{4})\s+(?:(?:early|mid|late)\s+)?(?P<ord>\d(?:st|nd|rd|th))$",
    re.IGNORECASE,
)


def _parse_pick_name(name: str) -> tuple[int, int] | None:
    """Parse a KTC pick name into (season, round); None if it isn't a pick."""
    m = _PICK_NAME_RE.match(name.strip())
    if not m:
        return None
    rnd = _PICK_ORDINALS.get(m.group("ord").lower())
    if rnd is None:
        return None
    return int(m.group("year")), rnd


def _avg(vals: list[int]) -> int | None:
    present = [v for v in vals if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present))


def build_pick_value_table(
    ktc_values: dict[str, KTCValue],
) -> dict[tuple[int, int], KTCValue]:
    """Group KTC draft-pick entries into a round-level value table.

    Recognizes picks by name pattern (year + ordinal), independent of the
    ``position`` string, then averages Early/Mid/Late entries within a round
    because the precise slot isn't known until end-of-season standings.

    Returns ``(season, round) -> KTCValue`` with averaged superflex/1QB values.
    """
    buckets: dict[tuple[int, int], list[KTCValue]] = {}
    for val in ktc_values.values():
        key = _parse_pick_name(val.name)
        if key is None:
            continue
        buckets.setdefault(key, []).append(val)

    table: dict[tuple[int, int], KTCValue] = {}
    for (season, rnd), entries in buckets.items():
        sf = _avg([e.superflex_value for e in entries])
        one = _avg([e.one_qb_value for e in entries])
        table[(season, rnd)] = KTCValue(
            name=f"{season} Round {rnd}",
            normalized_name=f"{season} round {rnd}",
            position="PICK",
            superflex_value=sf,
            one_qb_value=one,
        )
    return table
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ktc_parser.py -v`
Expected: PASS (both new tests plus existing parser tests)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/api/ktc.py tests/test_ktc_parser.py
git commit -m "feat: parse KTC pick entries into a round-level value table"
```

---

## Task 3: Value picks in the snapshot lens

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py:29-57` (`_ktc_value`, `grade_snapshot_value`) and `:229-258` (`grade_trade`)
- Test: `tests/test_trade_grader.py`

`grade_snapshot_value` and `grade_trade` gain an optional `pick_values` table.
`_ktc_value` learns to value a `PickAsset`: by the drafted player's current KTC
when annotated, else by the round-level pick table.

- [ ] **Step 1: Write the failing tests**

In `tests/test_trade_grader.py`, **replace** `test_snapshot_value_unresolved_pick_is_zero_in_v1` with the three tests below (the v1 zero-behavior is superseded):

```python
def test_snapshot_value_future_pick_uses_pick_table():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
            "u2": [],
        },
        given_by_uid={
            "u1": [],
            "u2": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
        },
    )
    pick_values = {
        (2030, 1): KTCValue(
            name="2030 Round 1", normalized_name="2030 round 1", position="PICK",
            superflex_value=5000, one_qb_value=4800,
        )
    }
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex",
                                  pick_values=pick_values)
    assert swings["u1"] == pytest.approx(5000)
    assert swings["u2"] == pytest.approx(-5000)


def test_snapshot_value_future_pick_zero_without_table():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
            "u2": [],
        },
        given_by_uid={
            "u1": [],
            "u2": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
        },
    )
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex")
    assert swings["u1"] == 0.0
    assert swings["u2"] == 0.0


def test_snapshot_value_drafted_but_flipped_pick_uses_player_value():
    # A pick annotated with its drafted player (non-resolution trade) is valued
    # at that player's CURRENT KTC, so it telescopes against the resolution trade.
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2024, round=1, original_owner_user_id="u_a",
                             drafted_player_id="p_jayden",
                             drafted_player_name="Jayden Daniels")],
            "u2": [],
        },
        given_by_uid={
            "u1": [],
            "u2": [PickAsset(season=2024, round=1, original_owner_user_id="u_a",
                             drafted_player_id="p_jayden",
                             drafted_player_name="Jayden Daniels")],
        },
    )
    ktc = {
        "p_jayden": KTCValue(
            name="Jayden Daniels", normalized_name="jayden daniels", position="QB",
            superflex_value=8000, one_qb_value=7900,
        )
    }
    swings = grade_snapshot_value(rt, ktc_values=ktc, fmt="superflex")
    assert swings["u1"] == pytest.approx(8000)
    assert swings["u2"] == pytest.approx(-8000)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trade_grader.py::test_snapshot_value_future_pick_uses_pick_table -v`
Expected: FAIL with `TypeError: grade_snapshot_value() got an unexpected keyword argument 'pick_values'`

- [ ] **Step 3: Implement pick valuation**

In `src/sleeper_dynasty/engine/trade_grader.py`, replace `_ktc_value` and
`grade_snapshot_value`:

```python
def _ktc_value(
    asset: TradeAsset,
    ktc: dict[str, KTCValue],
    fmt: str,
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
) -> float:
    """KTC value of an asset for snapshot grading.

    PlayerAsset: today's KTC value (Superflex or 1QB per fmt).
    PickAsset annotated with a drafted player: today's KTC of that player
        (so a flipped pick telescopes against its resolution trade).
    PickAsset without a drafted player (future/undrafted): round-level pick
        value from ``pick_values`` if available, else 0.
    FaabAsset: 0.
    """
    def _from_ktc(v: KTCValue | None) -> float:
        if v is None:
            return 0.0
        raw = v.superflex_value if fmt == "superflex" else v.one_qb_value
        return float(raw) if raw is not None else 0.0

    if isinstance(asset, PlayerAsset):
        v = ktc.get(asset.player_id)
        if v is None:
            log.warning("No KTC value for player %s (%s)", asset.player_id, asset.name)
        return _from_ktc(v)
    if isinstance(asset, PickAsset):
        if asset.drafted_player_id is not None:
            return _from_ktc(ktc.get(asset.drafted_player_id))
        table = pick_values or {}
        return _from_ktc(table.get((asset.season, asset.round)))
    return 0.0


def grade_snapshot_value(
    rt: ResolvedTrade,
    ktc_values: dict[str, KTCValue],
    fmt: str = "superflex",
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
) -> dict[str, float]:
    """Compute snapshot KTC value swing per side."""
    swings: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = sum(_ktc_value(a, ktc_values, fmt, pick_values) for a in side.received)
        given = sum(_ktc_value(a, ktc_values, fmt, pick_values) for a in side.given)
        swings[uid] = received - given
    return swings
```

Add `PickAsset` to the model import at the top of the file (it currently imports
`PlayerAsset`, `TradeAsset`, etc. from `sleeper_dynasty.models.trade`):

```python
from sleeper_dynasty.models.trade import (
    OwnerTradeRecord,
    PickAsset,
    PlayerAsset,
    RealizedImpact,
    ResolvedTrade,
    TradeAsset,
    TradeGrade,
)
```

Then thread `pick_values` through `grade_trade`. Replace its signature and the
`grade_snapshot_value` call:

```python
def grade_trade(
    rt: ResolvedTrade,
    ktc_values: dict[str, KTCValue],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int] | None = None,
    fmt: str = "superflex",
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
) -> TradeGrade:
    """Compute all three lenses for a single trade."""
    league_season_by_id = league_season_by_id or {}
    snapshot = grade_snapshot_value(rt, ktc_values, fmt=fmt, pick_values=pick_values)
    hindsight = grade_hindsight_production(
        rt, matchups, roster_to_user_by_league,
        league_season_by_id=league_season_by_id,
    )
    received, given = grade_realized_impact(
        rt,
        matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        playoff_weeks_by_league=playoff_weeks_by_league,
        league_season_by_id=league_season_by_id,
    )
    return TradeGrade(
        trade_id=rt.trade.transaction_id,
        snapshot_value_swing=snapshot,
        hindsight_production_swing=hindsight,
        realized_impact_received=received,
        realized_impact_given=given,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trade_grader.py -v`
Expected: PASS (the three new snapshot tests plus all existing grader tests)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader.py
git commit -m "feat: snapshot lens values picks (drafted-player or round table)"
```

---

## Task 4: Provenance pass — resolve a pick in exactly one trade

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_history.py` (`:128-224` resolve helpers, `:318-404` `build_trade_history`; add `compute_pick_resolution_map`)
- Test: `tests/test_trade_history.py`

### 4a. The resolution map (pure function)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_history.py`:

```python
def _pick_trade(tx_id, traded_at, giver, receiver, season, rnd, original_owner):
    from sleeper_dynasty.models.trade import PickAsset, Trade, TradeSide

    pick = PickAsset(season=season, round=rnd, original_owner_user_id=original_owner)
    sides = {
        giver: TradeSide(user_id=giver, received=[], given=[pick]),
        receiver: TradeSide(user_id=receiver, received=[pick], given=[]),
    }
    return Trade(
        transaction_id=tx_id, league_id="L", season=2024, week=1,
        traded_at=traded_at, sides=sides,
    )


def test_resolution_map_picks_last_receiver():
    from datetime import datetime, timezone
    from sleeper_dynasty.engine.trade_history import compute_pick_resolution_map

    # A->B (Sept), then B->C (Oct). Identity = (u_a, 2025, 1).
    ab = _pick_trade("ab", datetime(2024, 9, 1, tzinfo=timezone.utc),
                     giver="u_a", receiver="u_b", season=2025, rnd=1, original_owner="u_a")
    bc = _pick_trade("bc", datetime(2024, 10, 1, tzinfo=timezone.utc),
                     giver="u_b", receiver="u_c", season=2025, rnd=1, original_owner="u_a")

    resolution = compute_pick_resolution_map([ab, bc])
    # The pick belongs to whoever received it last: the B->C trade.
    assert resolution[("u_a", 2025, 1)] == "bc"


def test_resolution_map_handles_reacquisition():
    from datetime import datetime, timezone
    from sleeper_dynasty.engine.trade_history import compute_pick_resolution_map

    out = _pick_trade("out", datetime(2024, 9, 1, tzinfo=timezone.utc),
                      giver="u_a", receiver="u_b", season=2025, rnd=1, original_owner="u_a")
    back = _pick_trade("back", datetime(2024, 11, 1, tzinfo=timezone.utc),
                       giver="u_b", receiver="u_a", season=2025, rnd=1, original_owner="u_a")
    resolution = compute_pick_resolution_map([out, back])
    assert resolution[("u_a", 2025, 1)] == "back"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_history.py::test_resolution_map_picks_last_receiver -v`
Expected: FAIL with `ImportError: cannot import name 'compute_pick_resolution_map'`

- [ ] **Step 3: Implement `compute_pick_resolution_map`**

Add to `src/sleeper_dynasty/engine/trade_history.py` (after the imports / before
`normalize_trade`):

```python
def compute_pick_resolution_map(
    trades: list[Trade],
) -> dict[tuple[str, int, int], str]:
    """Map each pick identity to the transaction_id of its resolution trade.

    A pick's identity is ``(original_owner_user_id, season, round)``. The
    resolution trade is the chronologically last trade in which that pick was
    *received* — i.e., the one that delivered it to whoever ultimately held it
    (and therefore drafted with it). Ties on ``traded_at`` break by
    transaction_id for determinism.
    """
    # identity -> (sort_key, transaction_id) of the current best (latest) candidate.
    best: dict[tuple[str, int, int], tuple[tuple, str]] = {}
    for trade in trades:
        for side in trade.sides.values():
            for asset in side.received:
                if not isinstance(asset, PickAsset):
                    continue
                identity = (
                    asset.original_owner_user_id, asset.season, asset.round,
                )
                sort_key = (trade.traded_at, trade.transaction_id)
                current = best.get(identity)
                if current is None or sort_key > current[0]:
                    best[identity] = (sort_key, trade.transaction_id)
    return {identity: tx_id for identity, (_k, tx_id) in best.items()}
```

(`PickAsset` is already imported at the top of this module.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_history.py::test_resolution_map_picks_last_receiver tests/test_trade_history.py::test_resolution_map_handles_reacquisition -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_history.py tests/test_trade_history.py
git commit -m "feat: compute_pick_resolution_map identifies each pick's resolution trade"
```

### 4b. Resolve only in the resolution trade; annotate elsewhere

- [ ] **Step 6: Write the failing test**

Append to `tests/test_trade_history.py`:

```python
def test_resolve_assets_resolves_only_in_resolution_trade():
    from datetime import datetime, timezone
    from sleeper_dynasty.engine.trade_history import (
        compute_pick_resolution_map,
        resolve_assets,
    )
    from sleeper_dynasty.models.trade import PickAsset, PlayerAsset

    # Pick (u_a, 2024 R1) flipped A->B then B->C; C drafts player "p_drafted".
    ab = _pick_trade("ab", datetime(2024, 5, 1, tzinfo=timezone.utc),
                     giver="u_a", receiver="u_b", season=2024, rnd=1, original_owner="u_a")
    bc = _pick_trade("bc", datetime(2024, 6, 1, tzinfo=timezone.utc),
                     giver="u_b", receiver="u_c", season=2024, rnd=1, original_owner="u_a")

    drafts_by_season = {2024: {"draft_id": "d1", "status": "complete"}}
    draft_picks_by_draft_id = {
        "d1": [{"round": 1, "draft_slot": 3, "player_id": "p_drafted"}],
    }
    user_to_slot_by_season = {2024: {"u_a": 3}}  # original owner u_a holds slot 3
    player_names = {"p_drafted": "Drafted Rookie"}

    resolution = compute_pick_resolution_map([ab, bc])
    resolved = resolve_assets(
        [ab, bc],
        drafts_by_season=drafts_by_season,
        draft_picks_by_draft_id=draft_picks_by_draft_id,
        user_to_slot_by_season=user_to_slot_by_season,
        player_names=player_names,
        resolution_by_identity=resolution,
    )
    by_id = {rt.trade.transaction_id: rt for rt in resolved}

    # B->C is the resolution trade: C's received pick became the PlayerAsset.
    c_received = by_id["bc"].sides["u_c"].received
    assert any(isinstance(a, PlayerAsset) and a.player_id == "p_drafted"
               for a in c_received)

    # A->B is NOT the resolution trade: B's received asset stays a PickAsset,
    # annotated with the drafted player for valuation only.
    b_received = by_id["ab"].sides["u_b"].received
    assert len(b_received) == 1
    pick = b_received[0]
    assert isinstance(pick, PickAsset)
    assert pick.drafted_player_id == "p_drafted"
    assert pick.drafted_player_name == "Drafted Rookie"
    # No PlayerAsset leaked into the non-resolution trade.
    assert not any(isinstance(a, PlayerAsset) for a in b_received)
```

- [ ] **Step 7: Run test to verify it fails**

Run: `pytest tests/test_trade_history.py::test_resolve_assets_resolves_only_in_resolution_trade -v`
Expected: FAIL with `TypeError: resolve_assets() got an unexpected keyword argument 'resolution_by_identity'`

- [ ] **Step 8: Thread the resolution map through resolution**

In `src/sleeper_dynasty/engine/trade_history.py`, replace `_resolve_one_asset`,
`_resolve_side`, and `resolve_assets` with versions that take
`resolution_by_identity` and the current `trade_id`:

```python
def _resolve_one_asset(
    asset,
    trade_id: str,
    resolution_by_identity: dict[tuple[str, int, int], str],
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
):
    """Resolve a single asset.

    A PickAsset whose draft is complete and whose drafted player is known is
    EITHER upgraded to a PlayerAsset (only in its resolution trade) OR returned
    as a PickAsset annotated with the drafted player (every other trade). A
    pick whose draft hasn't happened (or whose slot/player can't be found) is
    returned unchanged.
    """
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
            asset.original_owner_user_id, asset.season,
        )
        return asset
    rows = draft_picks_by_draft_id.get(draft["draft_id"], [])
    player_id = None
    for row in rows:
        if row.get("round") == asset.round and row.get("draft_slot") == slot:
            player_id = row.get("player_id")
            break
    if not player_id:
        log.warning(
            "Draft %s has no drafted player for round=%d slot=%d (user=%s); "
            "pick stays unresolved",
            draft["draft_id"], asset.round, slot, asset.original_owner_user_id,
        )
        return asset

    player_name = player_names.get(player_id, player_id)
    identity = (asset.original_owner_user_id, asset.season, asset.round)
    is_resolution_trade = resolution_by_identity.get(identity) == trade_id
    if is_resolution_trade:
        return PlayerAsset(player_id=player_id, name=player_name, via_pick=asset)
    # Non-resolution trade: keep the pick, annotate it for snapshot valuation.
    return PickAsset(
        season=asset.season,
        round=asset.round,
        original_owner_user_id=asset.original_owner_user_id,
        drafted_player_id=player_id,
        drafted_player_name=player_name,
    )


def _resolve_side(
    side: TradeSide,
    trade_id: str,
    resolution_by_identity: dict[tuple[str, int, int], str],
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
) -> TradeSide:
    def _resolve(a):
        return _resolve_one_asset(
            a, trade_id, resolution_by_identity, drafts_by_season,
            draft_picks_by_draft_id, user_to_slot_by_season, player_names,
        )

    return TradeSide(
        user_id=side.user_id,
        received=[_resolve(a) for a in side.received],
        given=[_resolve(a) for a in side.given],
    )


def resolve_assets(
    trades: list[Trade],
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
    resolution_by_identity: dict[tuple[str, int, int], str] | None = None,
) -> list[ResolvedTrade]:
    """Resolve traded picks.

    ``resolution_by_identity`` (from ``compute_pick_resolution_map``) decides
    which single trade may upgrade each pick to a PlayerAsset. When omitted,
    no pick is upgraded — every drafted pick is annotated instead. Callers that
    want resolution MUST pass the map.
    """
    resolution_by_identity = resolution_by_identity or {}
    resolved: list[ResolvedTrade] = []
    for trade in trades:
        new_sides = {
            uid: _resolve_side(
                side,
                trade.transaction_id,
                resolution_by_identity,
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

Note: `TradeSide` is already imported at the top of the module.

- [ ] **Step 9: Run test to verify it passes**

Run: `pytest tests/test_trade_history.py::test_resolve_assets_resolves_only_in_resolution_trade -v`
Expected: PASS

- [ ] **Step 10: Check for and fix existing `resolve_assets` callers in tests**

Run: `pytest tests/test_trade_history.py -v`
Expected: Any pre-existing test that calls `resolve_assets` and asserts a pick
RESOLVED to a PlayerAsset will now fail, because those calls don't pass
`resolution_by_identity`. For each such failing test, add
`resolution_by_identity=compute_pick_resolution_map(<the trades list>)` to the
`resolve_assets(...)` call (import `compute_pick_resolution_map` in that test).
Tests that only assert annotation/future-pick behavior need no change. Re-run
until green.

- [ ] **Step 11: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_history.py tests/test_trade_history.py
git commit -m "feat: resolve a traded pick only in its resolution trade"
```

### 4c. Wire the resolution map into `build_trade_history`

- [ ] **Step 12: Update `build_trade_history` to compute and pass the map**

In `src/sleeper_dynasty/engine/trade_history.py`, inside `build_trade_history`,
the section currently reads (around the "Resolve picks." comment):

```python
    # Resolve picks.
    resolved = resolve_assets(
        trades,
        drafts_by_season=drafts_by_season,
        draft_picks_by_draft_id=draft_picks_by_draft_id,
        user_to_slot_by_season=user_to_slot_by_season,
        player_names=player_names,
    )
```

Replace it with:

```python
    # Resolve picks. The resolution map ensures each traded pick upgrades to a
    # PlayerAsset in exactly one trade (the one that delivered it to its final
    # holder); elsewhere it stays an annotated pick.
    resolution_by_identity = compute_pick_resolution_map(trades)
    resolved = resolve_assets(
        trades,
        drafts_by_season=drafts_by_season,
        draft_picks_by_draft_id=draft_picks_by_draft_id,
        user_to_slot_by_season=user_to_slot_by_season,
        player_names=player_names,
        resolution_by_identity=resolution_by_identity,
    )
```

- [ ] **Step 13: Run the full trade-history suite**

Run: `pytest tests/test_trade_history.py -v`
Expected: PASS

- [ ] **Step 14: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_history.py
git commit -m "feat: build_trade_history threads the pick resolution map"
```

---

## Task 5: End-to-end flip test (telescoping + production)

**Files:**
- Test: `tests/test_trade_grader.py`

Proves the spec's worked example: across the two trades, the flipped pick nets
to zero in snapshot for the middle team, and production credits only actual
roster ownership.

- [ ] **Step 1: Write the test**

Append to `tests/test_trade_grader.py`:

```python
def test_flipped_pick_telescopes_and_credits_only_real_ownership():
    # B receives a pick in A<->B and flips it in B<->C. The pick's drafted
    # player ("p_x") is rostered only by C. Grade both trades and confirm:
    #  - snapshot: B's pick nets to ~0 across the two trades
    #  - production: B earns 0 from the pick (never rostered p_x)
    ktc = {
        "p_x": KTCValue(name="X", normalized_name="x", position="WR",
                        superflex_value=6000, one_qb_value=5900),
    }

    # A<->B: B receives an annotated (flipped) pick worth p_x's KTC.
    ab = _stub_resolved_trade(
        received_by_uid={
            "u_b": [PickAsset(season=2024, round=1, original_owner_user_id="u_a",
                              drafted_player_id="p_x", drafted_player_name="X")],
            "u_a": [],
        },
        given_by_uid={
            "u_b": [],
            "u_a": [PickAsset(season=2024, round=1, original_owner_user_id="u_a",
                              drafted_player_id="p_x", drafted_player_name="X")],
        },
    )
    # B<->C: the resolution trade. B gives the resolved player; C receives it.
    bc = _stub_resolved_trade(
        received_by_uid={
            "u_c": [PlayerAsset("p_x", "X")],
            "u_b": [],
        },
        given_by_uid={
            "u_c": [],
            "u_b": [PlayerAsset("p_x", "X")],
        },
    )

    ab_swings = grade_snapshot_value(ab, ktc, fmt="superflex")
    bc_swings = grade_snapshot_value(bc, ktc, fmt="superflex")

    # B: +6000 (received pick in A<->B) then -6000 (gave p_x in B<->C) = 0 net.
    assert ab_swings["u_b"] + bc_swings["u_b"] == pytest.approx(0.0)
    # A gave the pick: -6000. C received p_x: +6000.
    assert ab_swings["u_a"] == pytest.approx(-6000)
    assert bc_swings["u_c"] == pytest.approx(6000)

    # Production: p_x scores 20 pts in week 5, rostered by C (roster 3).
    matchups = {
        ("L", 5, 3): {
            "players": ["p_x"], "players_points": {"p_x": 20.0},
            "starters": ["p_x"], "team_points": 100.0, "opponent_points": 90.0,
        },
    }
    roster_to_user = {"L": {3: "u_c"}}
    # In A<->B, B received the pick (a PickAsset) -> no production for B.
    ab_prod = grade_hindsight_production(ab, matchups, roster_to_user)
    assert ab_prod["u_b"] == pytest.approx(0.0)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_trade_grader.py::test_flipped_pick_telescopes_and_credits_only_real_ownership -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_trade_grader.py
git commit -m "test: flipped pick telescopes in snapshot, 0 production for flipper"
```

---

## Task 6: Wire the pick-value table through the API service

**Files:**
- Modify: `api/app/services/grader_io.py:54-143`
- Modify: `api/app/services/grader.py:91-104`

The engine now accepts a pick-value table; the backend must build it (from the
raw, name-keyed KTC values, BEFORE they're filtered to player_id) and pass it in.

- [ ] **Step 1: Build the table in `pull_supporting_data`**

In `api/app/services/grader_io.py`, add the import near the existing
`from sleeper_dynasty.api.ktc import fetch_ktc_values`:

```python
from sleeper_dynasty.api.ktc import build_pick_value_table, fetch_ktc_values
```

Then, immediately after the `ktc_values` is fetched (after the
`try/except` that sets `ktc_values`, before the `raw_players` loop), add:

```python
    # Draft-pick values live in the raw, name-keyed KTC blob and would be
    # dropped by the player_id matching below. Capture them first.
    pick_value_table = build_pick_value_table(ktc_values)
```

Finally, add it to the returned dict (the `return {` near the end of the
function):

```python
        "pick_value_table": pick_value_table,
```

- [ ] **Step 2: Pass it into `grade_trade`**

In `api/app/services/grader.py`, update the `grade_trade(...)` call inside the
grading loop:

```python
            g = grade_trade(
                rt,
                ktc_values=supporting["ktc_by_player_id"],
                matchups=supporting["matchups"],
                roster_to_user_by_league=supporting["roster_to_user_by_league"],
                playoff_weeks_by_league=supporting["playoff_weeks_by_league"],
                league_season_by_id=supporting["league_season_by_id"],
                fmt="superflex",
                pick_values=supporting["pick_value_table"],
            )
```

- [ ] **Step 3: Run the backend tests**

Run: `make test` (or `pytest -v` for the engine suite plus the api suite if run
separately). If `pull_supporting_data` has a unit test with a hand-built
`supporting` dict consumed by `GraderService`, ensure that fixture includes a
`pick_value_table` key (add `"pick_value_table": {}` if a test constructs the
dict manually).
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add api/app/services/grader_io.py api/app/services/grader.py
git commit -m "feat: backend builds and passes the pick-value table to the grader"
```

---

## Task 7: Full verification

- [ ] **Step 1: Run the entire engine + CLI suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 2: Run the backend + frontend unit tests**

Run: `make test`
Expected: all PASS.

- [ ] **Step 3: Final commit if anything was touched during verification**

```bash
git status
# commit any stragglers with an appropriate message
```

---

## Notes / known limitations (per spec, intentionally out of scope)

- **Identity drift when an owner left the league.** If a pick's
  `original_owner_user_id` resolves to the `"Owner #<roster_id>"` fallback in
  one season but a real user_id in another, the identity won't match across
  trades and provenance degrades toward per-trade resolution for that pick. Log
  output already flags the missing mapping. Not addressed here.
- **Round-level future-pick values.** Early/Mid/Late are averaged; no
  standings-projected slot precision.
- **Today's values only.** No historical point-in-time KTC for picks or players.
- **Phase 2 (incremental caching)** is a separate spec/plan and is not started here.
```