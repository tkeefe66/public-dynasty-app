# Trade Story Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn each trade's detail page into a bold, funny, system-inferred *story* (verdict + spicy paragraph, receipts behind a disclosure), grounded in engine-verified facts.

**Architecture:** Mirror the existing recap pattern — pure engine fact-builders compute a grounded `TradeStoryFacts` packet (winner, lopsidedness, per-player post-trade arcs, owner-strategy signals, offseason flag); a `TradeStoryWriter` feeds that packet to Claude with a facts-only persona; stories are generated eagerly+incrementally during the existing SSE refresh, cached in `ChainCacheEntry`, and served on `TradeDetailResp`. The frontend renders Format A.

**Tech Stack:** Python 3 / pytest (engine + `api/`), `anthropic` SDK (`claude-opus-4-8`), FastAPI, Next.js 14 / React / Tailwind / vitest (`web/`).

**Reference spec:** `docs/superpowers/specs/2026-06-07-trade-story-design.md`

**Conventions:** Engine + API tests live in repo-root `tests/`, run with `pytest`. Web tests run with `npx vitest run --config tests/vitest.config.ts` from `web/`. House style: no em dashes in prose/persona. Run all commands from the worktree root unless noted.

---

## File Structure

**Create (engine):**
- `src/sleeper_dynasty/models/trade_story.py` — facts-packet dataclasses + `facts_hash`.
- `src/sleeper_dynasty/engine/trade_story.py` — pure fact-builders (`is_offseason`, `build_owner_strategy`, `build_player_arc`, `build_trade_story_facts`).
- `src/sleeper_dynasty/llm/trade_story_writer.py` — `TradeStoryWriter` + `parse_story`.
- `src/sleeper_dynasty/llm/prompts/trade_story_persona.md` — persona.

**Create (api):**
- `api/app/services/story_gen.py` — eager+incremental+concurrent generation orchestrator.

**Create (web):**
- `web/components/TradeStory.tsx` — verdict + body + "Show the receipts".
- `web/lib/season-week.ts` — `seasonWeekLabel` (offseason fix, single source).

**Create (tests):**
- `tests/test_trade_story_models.py`, `tests/test_trade_story_engine.py`,
  `tests/test_trade_story_writer.py`, `tests/test_story_gen.py`,
  `tests/test_trade_view_story.py`
- `web/tests/season-week.test.ts`, `web/tests/TradeStory.test.tsx`

**Modify:**
- `api/app/services/chain_cache.py` — add `trade_stories`, `owner_dossiers` fields.
- `api/app/services/grader.py` — call `story_gen` in `GraderService.run`.
- `api/app/models/trade.py` — add `TradeStory` model + `story` on `TradeDetailResp`.
- `api/app/services/trade_view.py` — wire `story` from the cache entry.
- `web/lib/types.ts` — `TradeStory` type + `story` on `TradeDetailResp`.
- `web/app/league/[id]/trade/[tid]/page.tsx` — render `TradeStory`, fix header label.
- `web/components/TradeCard.tsx` — use `seasonWeekLabel`.

---

## Phase 1 — Engine facts

### Task 1: Trade-story facts-packet models

**Files:**
- Create: `src/sleeper_dynasty/models/trade_story.py`
- Test: `tests/test_trade_story_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_story_models.py
from sleeper_dynasty.models.trade_story import (
    PlayerArc, PickOutcome, OwnerStrategyFacts, TradeStoryFacts, facts_hash,
)


def _facts() -> TradeStoryFacts:
    return TradeStoryFacts(
        trade_id="t1", season=2024, is_offseason=True,
        winner_user_id="u_mike", lopsidedness=0.82,
        margins={"ktc": 1840.0, "production": 41.2, "impact": 6.0},
        sides=[
            {"user_id": "u_mike", "owner_name": "Mike",
             "player_arcs": [PlayerArc(
                 player="Bijan Robinson", position="RB", received_by="u_mike",
                 starter_weeks=14, points_total=210.0,
                 season_high_points=34.0, season_high_week=14,
                 season_high_is_playoff=True,
                 playoff_vs_regular_pct=12.0, decisive_starts=3,
                 benched_weeks=0).to_dict()],
             "pick_outcomes": []},
            {"user_id": "u_tom", "owner_name": "Tom",
             "player_arcs": [],
             "pick_outcomes": [PickOutcome(
                 season=2025, round=1, became_player="Rookie X",
                 points_per_game=9.1).to_dict()]},
        ],
        owners={
            "u_mike": OwnerStrategyFacts(
                user_id="u_mike", owner_name="Mike", trades_count=12,
                net_picks=-4, players_for_picks_count=7,
                picks_for_players_count=2, first_round_picks_sent=1,
                tilt="win-now", net_ktc=3200.0,
                tendencies=["buys win-now help with picks"]).to_dict(),
            "u_tom": OwnerStrategyFacts(
                user_id="u_tom", owner_name="Tom", trades_count=9,
                net_picks=5, players_for_picks_count=1,
                picks_for_players_count=4, first_round_picks_sent=3,
                tilt="rebuild", net_ktc=-1800.0,
                tendencies=["sold a 1st in 3 of last 4 deals"]).to_dict(),
        },
    )


def test_to_dict_is_json_serializable_and_round_trips():
    import json
    d = _facts().to_dict()
    s = json.dumps(d)  # must not raise
    assert json.loads(s)["winner_user_id"] == "u_mike"
    assert d["sides"][0]["player_arcs"][0]["season_high_week"] == 14
    assert d["owners"]["u_tom"]["tilt"] == "rebuild"


def test_facts_hash_is_stable_and_order_independent():
    a = facts_hash(_facts())
    b = facts_hash(_facts())
    assert a == b and len(a) == 16
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_story_models.py -v`
Expected: FAIL with `ModuleNotFoundError: sleeper_dynasty.models.trade_story`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/models/trade_story.py
"""Structured 'facts packet' models for trade stories.

Contract between the trade-story FactsBuilder (engine/trade_story.py) and the
TradeStoryWriter (llm/trade_story_writer.py). The writer serializes these to
JSON and is instructed to reference ONLY facts present here, so every number
the story cites is engine-verified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlayerArc:
    """One traded player's post-trade trajectory for the side that got them."""
    player: str
    position: str | None
    received_by: str  # user_id
    starter_weeks: int
    points_total: float
    season_high_points: float | None
    season_high_week: int | None
    season_high_is_playoff: bool
    playoff_vs_regular_pct: float | None  # +/- %; None if not enough data
    decisive_starts: int
    benched_weeks: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "player": self.player, "position": self.position,
            "received_by": self.received_by, "starter_weeks": self.starter_weeks,
            "points_total": round(self.points_total, 1),
            "season_high_points": self.season_high_points,
            "season_high_week": self.season_high_week,
            "season_high_is_playoff": self.season_high_is_playoff,
            "playoff_vs_regular_pct": self.playoff_vs_regular_pct,
            "decisive_starts": self.decisive_starts,
            "benched_weeks": self.benched_weeks,
        }


@dataclass
class PickOutcome:
    """What a traded pick became, when resolvable."""
    season: int
    round: int
    became_player: str | None
    points_per_game: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season, "round": self.round,
            "became_player": self.became_player,
            "points_per_game": (round(self.points_per_game, 1)
                                if self.points_per_game is not None else None),
        }


@dataclass
class OwnerStrategyFacts:
    """Verified signals describing one owner's trading strategy."""
    user_id: str
    owner_name: str
    trades_count: int
    net_picks: int
    players_for_picks_count: int   # received player(s), sent pick(s) = win-now
    picks_for_players_count: int   # received pick(s), sent player(s) = rebuild
    first_round_picks_sent: int
    tilt: str  # "win-now" | "rebuild" | "balanced"
    net_ktc: float
    tendencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id, "owner_name": self.owner_name,
            "trades_count": self.trades_count, "net_picks": self.net_picks,
            "players_for_picks_count": self.players_for_picks_count,
            "picks_for_players_count": self.picks_for_players_count,
            "first_round_picks_sent": self.first_round_picks_sent,
            "tilt": self.tilt, "net_ktc": round(self.net_ktc, 0),
            "tendencies": list(self.tendencies),
        }


@dataclass
class TradeStoryFacts:
    trade_id: str
    season: int
    is_offseason: bool
    winner_user_id: str | None  # None => "even"
    lopsidedness: float          # 0..1
    margins: dict[str, float]    # ktc / production / impact
    sides: list[dict[str, Any]]  # each: user_id, owner_name, player_arcs, pick_outcomes
    owners: dict[str, dict[str, Any]]  # user_id -> OwnerStrategyFacts.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id, "season": self.season,
            "is_offseason": self.is_offseason,
            "winner_user_id": self.winner_user_id,
            "lopsidedness": round(self.lopsidedness, 3),
            "margins": {k: round(v, 1) for k, v in self.margins.items()},
            "sides": self.sides,
            "owners": self.owners,
        }


def facts_hash(facts: TradeStoryFacts) -> str:
    """Stable 16-char hash of a facts packet (used for incremental skip)."""
    blob = json.dumps(facts.to_dict(), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_story_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/trade_story.py tests/test_trade_story_models.py
git commit -m "feat(engine): trade-story facts-packet models"
```

---

### Task 2: Offseason detection + owner-strategy builder

**Files:**
- Create: `src/sleeper_dynasty/engine/trade_story.py`
- Test: `tests/test_trade_story_engine.py`

> **Offseason rule (heuristic, documented):** dynasty in-season trading happens
> only in Sept–Nov (the deadline is ~Week 11). So a trade is offseason when its
> `traded_at` month is **not** in `{9, 10, 11}`. This uses data we already have
> (`Trade.traded_at`) and fixes the "Week 1" mislabel. The constant
> `IN_SEASON_MONTHS` is centralized so it can be refined later.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_story_engine.py
from datetime import datetime

from sleeper_dynasty.engine.trade_story import is_offseason, build_owner_strategy
from sleeper_dynasty.models.trade import (
    PlayerAsset, PickAsset, Trade, TradeSide, ResolvedTrade,
)


def test_is_offseason_true_in_summer_false_midseason():
    assert is_offseason(datetime(2024, 6, 14)) is True
    assert is_offseason(datetime(2024, 10, 6)) is False
    assert is_offseason(datetime(2024, 2, 1)) is True


def _rt(tx, month, mike_gets_player, season=2024):
    """Mike sends a 1st-round pick, gets a player (win-now). Tom the reverse."""
    pick = PickAsset(season=2025, round=1, original_owner_user_id="u_mike")
    player = PlayerAsset(player_id="p1", name="Bijan Robinson")
    mike = TradeSide(user_id="u_mike",
                     received=[player] if mike_gets_player else [pick],
                     given=[pick] if mike_gets_player else [player])
    tom = TradeSide(user_id="u_tom",
                    received=[pick] if mike_gets_player else [player],
                    given=[player] if mike_gets_player else [pick])
    t = Trade(transaction_id=tx, league_id="L", season=season, week=1,
              traded_at=datetime(season, month, 1),
              sides={"u_mike": mike, "u_tom": tom})
    return ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})


def test_owner_strategy_classifies_tilt_and_counts_first_round_sales():
    resolved = [_rt("t1", 6, True), _rt("t2", 7, True)]
    grades = {
        "t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}},
        "t2": {"snapshot_value_swing": {"u_mike": 940.0, "u_tom": -940.0}},
    }
    owners = {"u_mike": "Mike", "u_tom": "Tom"}
    strat = build_owner_strategy(resolved, grades, owners)
    assert strat["u_mike"].tilt == "win-now"
    assert strat["u_mike"].players_for_picks_count == 2
    assert strat["u_mike"].first_round_picks_sent == 2  # Mike SENT the firsts
    assert strat["u_mike"].net_ktc == 1840.0
    assert any("win-now" in t for t in strat["u_mike"].tendencies)
    assert strat["u_tom"].tilt == "rebuild"
    assert strat["u_tom"].first_round_picks_sent == 0
    assert strat["u_tom"].net_ktc == -1840.0


def test_first_round_sale_tendency_fires_after_three_deals():
    # Three win-now deals where Mike ships a 1st each time -> tendency fires.
    resolved = [_rt("t1", 6, True), _rt("t2", 7, True), _rt("t3", 8, True)]
    strat = build_owner_strategy(
        resolved, {}, {"u_mike": "Mike", "u_tom": "Tom"})
    assert any("sold a 1st" in t for t in strat["u_mike"].tendencies)
```

> Note: `first_round_picks_sent` counts first-round picks an owner **gave
> away** (`side.given`). The "sold a 1st in N of last 4 deals" tendency fires at
> N >= 3.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_story_engine.py -v`
Expected: FAIL with `ImportError: cannot import name 'is_offseason'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/engine/trade_story.py
"""FactsBuilder for trade stories.

Every number a story can cite is computed here so the LLM writer never has to
(and can never invent one). Pure functions, unit-testable against fixture data.
"""

from __future__ import annotations

from datetime import datetime

from sleeper_dynasty.models.trade import (
    PickAsset, PlayerAsset, ResolvedTrade,
)
from sleeper_dynasty.models.trade_story import OwnerStrategyFacts

# Dynasty in-season trading window (deadline ~Week 11). Everything else is
# offseason. Centralized so it can be refined against real data later.
IN_SEASON_MONTHS = {9, 10, 11}

RECENT_DEALS = 4  # window for the "sold a 1st in N of last 4 deals" tendency


def is_offseason(traded_at: datetime) -> bool:
    return traded_at.month not in IN_SEASON_MONTHS


def _counts(side_received, side_given):
    players_recv = sum(isinstance(a, PlayerAsset) for a in side_received)
    picks_recv = sum(isinstance(a, PickAsset) for a in side_received)
    players_given = sum(isinstance(a, PlayerAsset) for a in side_given)
    picks_given = sum(isinstance(a, PickAsset) for a in side_given)
    return players_recv, picks_recv, players_given, picks_given


def build_owner_strategy(
    resolved: list[ResolvedTrade],
    grades: dict[str, dict],
    owners_display: dict[str, str],
) -> dict[str, OwnerStrategyFacts]:
    """Aggregate each owner's trading tendencies across the whole chain."""
    acc: dict[str, dict] = {}
    # Newest-first per owner, for the "last N deals" tendency.
    by_owner_deals: dict[str, list[tuple[datetime, int]]] = {}

    for rt in resolved:
        for uid, side in rt.sides.items():
            p_recv, k_recv, p_given, k_given = _counts(side.received, side.given)
            a = acc.setdefault(uid, {
                "trades_count": 0, "net_picks": 0,
                "players_for_picks_count": 0, "picks_for_players_count": 0,
                "first_round_picks_sent": 0, "net_ktc": 0.0,
            })
            a["trades_count"] += 1
            a["net_picks"] += k_recv - k_given
            if p_recv >= 1 and k_given >= 1:
                a["players_for_picks_count"] += 1
            if k_recv >= 1 and p_given >= 1:
                a["picks_for_players_count"] += 1
            firsts_sent = sum(
                isinstance(x, PickAsset) and x.round == 1 for x in side.given
            )
            a["first_round_picks_sent"] += firsts_sent
            g = grades.get(rt.trade.transaction_id) or {}
            a["net_ktc"] += float(
                (g.get("snapshot_value_swing") or {}).get(uid, 0.0) or 0.0
            )
            by_owner_deals.setdefault(uid, []).append(
                (rt.trade.traded_at, firsts_sent)
            )

    out: dict[str, OwnerStrategyFacts] = {}
    for uid, a in acc.items():
        if a["players_for_picks_count"] > a["picks_for_players_count"]:
            tilt = "win-now"
        elif a["picks_for_players_count"] > a["players_for_picks_count"]:
            tilt = "rebuild"
        else:
            tilt = "balanced"

        tendencies: list[str] = []
        if tilt == "win-now":
            tendencies.append("buys win-now help with picks")
        elif tilt == "rebuild":
            tendencies.append("trades present help for future picks")
        recent = sorted(by_owner_deals.get(uid, []), reverse=True)[:RECENT_DEALS]
        firsts_recent = sum(1 for _, f in recent if f > 0)
        if firsts_recent >= 3:
            tendencies.append(
                f"sold a 1st in {firsts_recent} of last {len(recent)} deals"
            )

        out[uid] = OwnerStrategyFacts(
            user_id=uid, owner_name=owners_display.get(uid, uid),
            trades_count=a["trades_count"], net_picks=a["net_picks"],
            players_for_picks_count=a["players_for_picks_count"],
            picks_for_players_count=a["picks_for_players_count"],
            first_round_picks_sent=a["first_round_picks_sent"],
            tilt=tilt, net_ktc=a["net_ktc"], tendencies=tendencies,
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_story_engine.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_story.py tests/test_trade_story_engine.py
git commit -m "feat(engine): offseason detection + owner-strategy builder"
```

---

### Task 3: Per-player post-trade arc builder

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_story.py`
- Test: `tests/test_trade_story_engine.py` (add)

> Reuses `_is_post_trade` from the grader so post-trade semantics stay identical
> to Lens 3. `matchups` is keyed `(league_id, week, roster_id) -> entry` with
> `entry` keys `players`, `starters`, `players_points`, `team_points`,
> `opponent_points` (see `grade_realized_impact`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_story_engine.py  (append)
from sleeper_dynasty.engine.trade_story import build_player_arc


def test_player_arc_season_high_playoff_split_and_decisive():
    # Mike (roster 1, league L season 2024) owns p_bijan after a week-1 trade.
    rt = _rt("t1", 9, True)  # in-season Sept trade, week 1
    matchups = {
        # week 5 regular: 10 pts, team wins by 4 -> decisive (10 > 4)
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 96.0},
        # week 9 regular: 20 pts, loss
        ("L", 9, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 20.0},
                      "team_points": 90.0, "opponent_points": 110.0},
        # week 15 playoff: 34 pts season high
        ("L", 15, 1): {"players": ["p1"], "starters": ["p1"],
                       "players_points": {"p1": 34.0},
                       "team_points": 130.0, "opponent_points": 120.0},
        # week 16 benched (rostered, not started)
        ("L", 16, 1): {"players": ["p1"], "starters": [],
                       "players_points": {"p1": 5.0},
                       "team_points": 100.0, "opponent_points": 99.0},
    }
    arc = build_player_arc(
        pid="p1", player_name="Bijan Robinson", position="RB",
        owner_uid="u_mike", rt=rt, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
    )
    assert arc.starter_weeks == 3
    assert arc.season_high_points == 34.0 and arc.season_high_week == 15
    assert arc.season_high_is_playoff is True
    assert arc.decisive_starts == 2  # week 5 and week 15 are both decisive wins
    assert arc.benched_weeks == 1
    # regular avg = (10+20)/2 = 15; playoff avg = 34; pct = +126.7
    assert round(arc.playoff_vs_regular_pct, 1) == 126.7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_story_engine.py::test_player_arc_season_high_playoff_split_and_decisive -v`
Expected: FAIL with `ImportError: cannot import name 'build_player_arc'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/engine/trade_story.py  (add imports + function)
from sleeper_dynasty.engine.trade_grader import _is_post_trade
from sleeper_dynasty.models.trade_story import PlayerArc


def build_player_arc(
    pid: str,
    player_name: str,
    position: str | None,
    owner_uid: str,
    rt: ResolvedTrade,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int] | None = None,
) -> PlayerArc:
    league_season_by_id = league_season_by_id or {}
    starter_weeks = benched_weeks = decisive_starts = 0
    points_total = 0.0
    season_high_points: float | None = None
    season_high_week: int | None = None
    season_high_is_playoff = False
    reg_pts: list[float] = []
    pf_pts: list[float] = []

    for (lg, wk, rid), entry in matchups.items():
        if not _is_post_trade(lg, wk, rt, league_season_by_id):
            continue
        if roster_to_user_by_league.get(lg, {}).get(rid) != owner_uid:
            continue
        if pid not in (entry.get("players") or []):
            continue
        is_starter = pid in (entry.get("starters") or [])
        pts = float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        if not is_starter:
            benched_weeks += 1
            continue
        starter_weeks += 1
        points_total += pts
        is_playoff = wk >= playoff_weeks_by_league.get(lg, 15)
        (pf_pts if is_playoff else reg_pts).append(pts)
        team_pts = float(entry.get("team_points") or 0.0)
        opp_pts = float(entry.get("opponent_points") or 0.0)
        if team_pts > opp_pts and pts > (team_pts - opp_pts):
            decisive_starts += 1
        if season_high_points is None or pts > season_high_points:
            season_high_points, season_high_week = pts, wk
            season_high_is_playoff = is_playoff

    pct: float | None = None
    if reg_pts and pf_pts:
        reg_avg = sum(reg_pts) / len(reg_pts)
        if reg_avg > 0:
            pct = (sum(pf_pts) / len(pf_pts) / reg_avg - 1.0) * 100.0

    return PlayerArc(
        player=player_name, position=position, received_by=owner_uid,
        starter_weeks=starter_weeks, points_total=points_total,
        season_high_points=season_high_points, season_high_week=season_high_week,
        season_high_is_playoff=season_high_is_playoff,
        playoff_vs_regular_pct=pct, decisive_starts=decisive_starts,
        benched_weeks=benched_weeks,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_story_engine.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_story.py tests/test_trade_story_engine.py
git commit -m "feat(engine): per-player post-trade arc builder"
```

---

### Task 4: Assemble the full `TradeStoryFacts`

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_story.py`
- Test: `tests/test_trade_story_engine.py` (add)

> Winner = the side with the largest positive `snapshot_value_swing` (KTC is the
> primary lens). `lopsidedness = min(1, |winner_margin| / 2500)` (2500 KTC ≈ a
> blowout). `margins` reports the winner's swing in each lens. `player_arcs` are
> built for each `PlayerAsset` a side received; `pick_outcomes` come from
> resolved `PlayerAsset.via_pick` / unresolved `PickAsset`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_story_engine.py  (append)
from sleeper_dynasty.engine.trade_story import build_trade_story_facts
from sleeper_dynasty.models.trade_story import OwnerStrategyFacts


def test_build_trade_story_facts_picks_winner_and_offseason():
    rt = _rt("t1", 6, True)  # June (offseason), Mike receives the player
    grade = {
        "snapshot_value_swing": {"u_mike": 1840.0, "u_tom": -1840.0},
        "hindsight_production_swing": {"u_mike": 41.2, "u_tom": -41.2},
        "hindsight_started_swing": {"u_mike": 30.0, "u_tom": -30.0},
    }
    owner_strategy = {
        "u_mike": OwnerStrategyFacts("u_mike", "Mike", 12, -4, 7, 2, 1,
                                     "win-now", 3200.0, []),
        "u_tom": OwnerStrategyFacts("u_tom", "Tom", 9, 5, 1, 4, 3,
                                    "rebuild", -1800.0, []),
    }
    facts = build_trade_story_facts(
        rt=rt, grade=grade, owner_strategy=owner_strategy,
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024},
        positions={"p1": "RB"},
    )
    assert facts.is_offseason is True
    assert facts.winner_user_id == "u_mike"
    assert facts.margins["ktc"] == 1840.0
    assert 0.73 < facts.lopsidedness <= 0.74  # 1840/2500
    assert facts.owners["u_tom"]["tilt"] == "rebuild"
    mike_side = next(s for s in facts.sides if s["user_id"] == "u_mike")
    assert mike_side["player_arcs"][0]["player"] == "Bijan Robinson"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_story_engine.py::test_build_trade_story_facts_picks_winner_and_offseason -v`
Expected: FAIL with `ImportError: cannot import name 'build_trade_story_facts'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/engine/trade_story.py  (add)
from sleeper_dynasty.models.trade_story import PickOutcome, TradeStoryFacts

BLOWOUT_KTC = 2500.0


def _pick_outcome(asset) -> PickOutcome | None:
    if isinstance(asset, PlayerAsset) and asset.via_pick is not None:
        return PickOutcome(season=asset.via_pick.season,
                           round=asset.via_pick.round,
                           became_player=asset.name, points_per_game=None)
    if isinstance(asset, PickAsset):
        return PickOutcome(season=asset.season, round=asset.round,
                           became_player=asset.drafted_player_name,
                           points_per_game=None)
    return None


def build_trade_story_facts(
    rt: ResolvedTrade,
    grade: dict,
    owner_strategy: dict[str, OwnerStrategyFacts],
    owners_display: dict[str, str],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int] | None = None,
    positions: dict[str, str] | None = None,
) -> TradeStoryFacts:
    positions = positions or {}
    swings = grade.get("snapshot_value_swing") or {}
    winner = max(swings, key=lambda u: swings.get(u, 0.0)) if swings else None
    win_margin = abs(swings.get(winner, 0.0)) if winner else 0.0
    if win_margin < 1e-6:
        winner = None
    lopsidedness = min(1.0, win_margin / BLOWOUT_KTC)

    margins = {
        "ktc": float((swings or {}).get(winner, 0.0) or 0.0) if winner else 0.0,
        "production": float(
            (grade.get("hindsight_production_swing") or {}).get(winner, 0.0)
            if winner else 0.0
        ),
        "impact": float(
            (grade.get("hindsight_started_swing") or {}).get(winner, 0.0)
            if winner else 0.0
        ),
    }

    sides: list[dict] = []
    for uid, side in rt.sides.items():
        arcs = [
            build_player_arc(
                pid=a.player_id, player_name=a.name,
                position=positions.get(a.player_id), owner_uid=uid, rt=rt,
                matchups=matchups,
                roster_to_user_by_league=roster_to_user_by_league,
                playoff_weeks_by_league=playoff_weeks_by_league,
                league_season_by_id=league_season_by_id,
            ).to_dict()
            for a in side.received if isinstance(a, PlayerAsset)
        ]
        outs = [o.to_dict() for o in (_pick_outcome(a) for a in side.received)
                if o is not None]
        sides.append({
            "user_id": uid, "owner_name": owners_display.get(uid, uid),
            "player_arcs": arcs, "pick_outcomes": outs,
        })

    return TradeStoryFacts(
        trade_id=rt.trade.transaction_id, season=rt.trade.season,
        is_offseason=is_offseason(rt.trade.traded_at),
        winner_user_id=winner, lopsidedness=lopsidedness, margins=margins,
        sides=sides,
        owners={uid: f.to_dict() for uid, f in owner_strategy.items()},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_story_engine.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_story.py tests/test_trade_story_engine.py
git commit -m "feat(engine): assemble full TradeStoryFacts packet"
```

---

## Phase 2 — LLM writer

### Task 5: Persona prompt + `TradeStoryWriter` + `parse_story`

**Files:**
- Create: `src/sleeper_dynasty/llm/prompts/trade_story_persona.md`
- Create: `src/sleeper_dynasty/llm/trade_story_writer.py`
- Test: `tests/test_trade_story_writer.py`

- [ ] **Step 1: Write the persona prompt**

```markdown
<!-- src/sleeper_dynasty/llm/prompts/trade_story_persona.md -->
# The Beat Writer

You are the league's trade columnist: sharp, candid, competitive, and funny.
You write for ~10 friends in one private dynasty league who already know each
other and love trash talk. You settle arguments with receipts.

## Hard rules
- Use ONLY facts present in the FACTS PACKET. Never invent a number, a game, a
  player, or an event. If a fact is not in the packet, do not mention it.
- Output exactly: one VERDICT line, then a blank line, then 1-2 short
  paragraphs of body. No headings, no lists, no preamble.
- The VERDICT line is a single bold sentence naming the winner (or "Too close
  to call" when `winner_user_id` is null). Reference `owner_name` from the
  packet, never the user_id.
- No em dashes. No "--". Use commas, periods, colons, or parentheses.

## Voice, dialed by `lopsidedness` (0..1)
- High (>= 0.6): brutal and gloating. Someone got robbed. Say so.
- Mid (0.3-0.6): confident lean with jokes, acknowledge the loser had a point.
- Low (< 0.3): "too close to call," but still spicy. Tease both sides.

## What to weave in
- The winner and the margin in plain language (market value, points since).
- The single most vivid player beat (a season-high game, a playoff explosion or
  collapse via `playoff_vs_regular_pct`, decisive starts).
- The losing/ winning owner's strategy from `owners` (tilt, tendencies): frame
  the trade as a move that fits or breaks their pattern, and what it means next.
- Plain language only. Never use jargon like "swing", "KTC", or stat acronyms.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_trade_story_writer.py
from unittest.mock import MagicMock, patch

from sleeper_dynasty.llm.trade_story_writer import (
    TradeStoryWriter, load_persona, parse_story,
)
from sleeper_dynasty.models.trade_story import TradeStoryFacts


def _facts():
    return TradeStoryFacts(
        trade_id="t1", season=2024, is_offseason=True, winner_user_id="u_mike",
        lopsidedness=0.82, margins={"ktc": 1840.0, "production": 41.2, "impact": 6.0},
        sides=[{"user_id": "u_mike", "owner_name": "Mike",
                "player_arcs": [], "pick_outcomes": []}],
        owners={"u_mike": {"owner_name": "Mike", "tilt": "win-now"}},
    )


def test_persona_loads_with_hard_rules():
    p = load_persona()
    assert "ONLY" in p and "Beat Writer" in p


def test_parse_story_splits_verdict_and_body():
    raw = "Mike robbed Tom.\n\nThree months later, it is not close.\n\nReceipts."
    story = parse_story(raw)
    assert story["verdict"] == "Mike robbed Tom."
    assert "Three months later" in story["body"]
    assert "Receipts." in story["body"]


def test_build_request_has_cached_persona_and_facts_only():
    w = TradeStoryWriter(api_key="test")
    system, messages = w.build_request(_facts())
    assert system[0]["cache_control"]["type"] == "ephemeral"
    assert "Beat Writer" in str(system)
    assert "1840.0" in str(messages) and "use ONLY" in str(messages).lower()


def test_write_calls_client_and_parses():
    fake = MagicMock()
    fake.content = [MagicMock(text="Mike robbed Tom.\n\nNot close.")]
    client = MagicMock()
    client.messages.create.return_value = fake
    w = TradeStoryWriter(api_key="test")
    with patch.object(w, "_client", client):
        out = w.write(_facts())
    assert out["verdict"] == "Mike robbed Tom."
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-opus-4-8"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_trade_story_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: sleeper_dynasty.llm.trade_story_writer`.

- [ ] **Step 4: Write minimal implementation**

```python
# src/sleeper_dynasty/llm/trade_story_writer.py
"""TradeStoryWriter: turn a TradeStoryFacts packet into verdict+story prose.

Mirrors RecapWriter: a static prompt-cached persona system block plus a user
turn carrying the facts JSON. The model is told to use only packet facts.
"""

from __future__ import annotations

import json
import logging
from importlib import resources

import anthropic

from sleeper_dynasty.models.trade_story import TradeStoryFacts

logger = logging.getLogger(__name__)

_PROMPTS = "sleeper_dynasty.llm.prompts"
DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 1024


def load_persona() -> str:
    return resources.files(_PROMPTS).joinpath("trade_story_persona.md").read_text()


def parse_story(text: str) -> dict[str, str]:
    """Split raw model output into {verdict, body}.

    Verdict = first non-empty line (markdown bold stripped). Body = the rest,
    trimmed. Resilient to a missing blank line.
    """
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    verdict = ""
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.strip():
            verdict = ln.strip().strip("*").strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    return {"verdict": verdict, "body": body}


class TradeStoryWriter:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 persona: str | None = None) -> None:
        self.model = model
        self.persona = persona or load_persona()
        self._client = anthropic.Anthropic(api_key=api_key)

    def build_request(self, facts: TradeStoryFacts) -> tuple[list[dict], list[dict]]:
        system = [{"type": "text", "text": self.persona,
                   "cache_control": {"type": "ephemeral"}}]
        user = (
            "FACTS PACKET (use ONLY these facts):\n\n```json\n"
            + json.dumps(facts.to_dict(), indent=2)
            + "\n```\n\nWrite the verdict line and the story."
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
        return system, messages

    def write(self, facts: TradeStoryFacts) -> dict[str, str]:
        system, messages = self.build_request(facts)
        logger.info("Requesting trade story from %s (trade %s)",
                    self.model, facts.trade_id)
        resp = self._client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS,
            system=system, messages=messages,
        )
        return parse_story(resp.content[0].text)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_trade_story_writer.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/llm/trade_story_writer.py \
  src/sleeper_dynasty/llm/prompts/trade_story_persona.md \
  tests/test_trade_story_writer.py
git commit -m "feat(llm): TradeStoryWriter + bold/funny persona"
```

---

## Phase 3 — Generation + cache

### Task 6: Cache fields for stories + dossiers

**Files:**
- Modify: `api/app/services/chain_cache.py:12-30`
- Test: `tests/test_chain_cache_stories.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chain_cache_stories.py
import json
from pathlib import Path

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _entry(**over):
    base = dict(
        league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="now",
    )
    base.update(over)
    return ChainCacheEntry(**base)


def test_new_fields_default_empty_and_round_trip(tmp_path: Path):
    c = ChainCache(cache_dir=tmp_path)
    e = _entry(trade_stories={"t1": {"verdict": "v", "body": "b",
                                     "facts_hash": "h", "generated_at": "now"}})
    c.write("L", e)
    back = c.read("L")
    assert back.trade_stories["t1"]["verdict"] == "v"
    assert back.owner_dossiers == {}


def test_pre_migration_file_without_story_fields_loads(tmp_path: Path):
    # A cache file written before these fields existed (has 'owners', no stories).
    raw = dict(
        league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="now",
        warnings=[],
    )
    (tmp_path / "chain_L.json").write_text(json.dumps(raw))
    back = ChainCache(cache_dir=tmp_path).read("L")
    assert back is not None and back.trade_stories == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest ../tests/test_chain_cache_stories.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword 'trade_stories'`.
(Run API tests from `api/` so `app` imports resolve; engine tests run from root.)

- [ ] **Step 3: Write minimal implementation**

```python
# api/app/services/chain_cache.py  — add two fields to ChainCacheEntry, after `warnings`
    warnings: list[str] = field(default_factory=list)
    trade_stories: dict[str, dict[str, Any]] = field(default_factory=dict)
    owner_dossiers: dict[str, dict[str, Any]] = field(default_factory=dict)
```

(`read()` already passes `**raw` into the dataclass; missing keys fall back to
the new defaults, so old files load. `write()` uses `asdict`, so new files
include them. No other change needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest ../tests/test_chain_cache_stories.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/chain_cache.py tests/test_chain_cache_stories.py
git commit -m "feat(api): cache fields for trade stories + owner dossiers"
```

---

### Task 7: Generation orchestrator (eager, incremental, concurrent)

**Files:**
- Create: `api/app/services/story_gen.py`
- Test: `tests/test_story_gen.py`

> Skips a trade whose cached `facts_hash` already matches (incremental). Runs the
> blocking SDK calls via `asyncio.to_thread` under a `Semaphore` (concurrent,
> non-blocking). A per-trade failure logs and leaves that story unset. Takes the
> writer as a parameter so tests inject a fake (no live API).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_story_gen.py
import asyncio
from datetime import datetime

from app.services.story_gen import generate_stories
from sleeper_dynasty.models.trade import (
    PlayerAsset, PickAsset, Trade, TradeSide, ResolvedTrade,
)


class FakeWriter:
    def __init__(self):
        self.calls = 0

    def write(self, facts):
        self.calls += 1
        return {"verdict": f"V {facts.trade_id}", "body": "B"}


def _rt(tx):
    pick = PickAsset(season=2025, round=1, original_owner_user_id="u_mike")
    player = PlayerAsset(player_id="p1", name="Bijan Robinson")
    mike = TradeSide("u_mike", received=[player], given=[pick])
    tom = TradeSide("u_tom", received=[pick], given=[player])
    t = Trade(tx, "L", 2024, 1, datetime(2024, 6, 1),
              {"u_mike": mike, "u_tom": tom})
    return ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})


def _supporting():
    return dict(matchups={}, roster_to_user_by_league={},
                playoff_weeks_by_league={}, league_season_by_id={"L": 2024},
                positions={}, owners_display={"u_mike": "Mike", "u_tom": "Tom"})


def test_generates_for_new_trades_and_skips_unchanged():
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    writer = FakeWriter()

    stories, dossiers = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=writer, max_concurrency=4,
    ))
    assert writer.calls == 1
    assert stories["t1"]["verdict"] == "V t1"
    assert "facts_hash" in stories["t1"] and "u_mike" in dossiers

    # Re-run with the prior stories; same facts => skipped.
    writer2 = FakeWriter()
    stories2, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories=stories, writer=writer2, max_concurrency=4,
    ))
    assert writer2.calls == 0
    assert stories2["t1"]["verdict"] == "V t1"


def test_per_trade_failure_is_isolated():
    class Boom(FakeWriter):
        def write(self, facts):
            raise RuntimeError("api down")

    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    stories, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=Boom(), max_concurrency=4,
    ))
    assert stories == {}  # failed trade simply absent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest ../tests/test_story_gen.py -v`
Expected: FAIL with `ModuleNotFoundError: app.services.story_gen`.

- [ ] **Step 3: Write minimal implementation**

```python
# api/app/services/story_gen.py
"""Eager + incremental + concurrent trade-story generation.

Called from GraderService.run after grading. Reuses the engine fact-builders;
the writer is injected so tests can fake it (no live Anthropic calls).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sleeper_dynasty.engine.trade_story import (
    build_owner_strategy, build_trade_story_facts,
)
from sleeper_dynasty.models.trade_story import facts_hash

log = logging.getLogger(__name__)


async def generate_stories(
    *,
    resolved: list,
    grades: dict[str, dict],
    supporting: dict[str, Any],
    prior_stories: dict[str, dict],
    writer,
    max_concurrency: int = 5,
    progress_cb=None,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (trade_stories, owner_dossiers)."""
    owners_display = supporting["owners_display"]
    owner_strategy = build_owner_strategy(resolved, grades, owners_display)
    dossiers = {uid: f.to_dict() for uid, f in owner_strategy.items()}

    # Build facts for every trade, then decide what needs (re)generation.
    pending: list[tuple[str, Any, str]] = []
    stories: dict[str, dict] = {}
    for rt in resolved:
        tx = rt.trade.transaction_id
        facts = build_trade_story_facts(
            rt=rt, grade=grades.get(tx) or {}, owner_strategy=owner_strategy,
            owners_display=owners_display,
            matchups=supporting["matchups"],
            roster_to_user_by_league=supporting["roster_to_user_by_league"],
            playoff_weeks_by_league=supporting["playoff_weeks_by_league"],
            league_season_by_id=supporting["league_season_by_id"],
            positions=supporting.get("positions") or {},
        )
        h = facts_hash(facts)
        prior = prior_stories.get(tx)
        if prior and prior.get("facts_hash") == h:
            stories[tx] = prior  # incremental skip
            continue
        pending.append((tx, facts, h))

    sem = asyncio.Semaphore(max_concurrency)
    done = 0

    async def _one(tx: str, facts, h: str):
        nonlocal done
        async with sem:
            try:
                result = await asyncio.to_thread(writer.write, facts)
            except Exception:
                log.exception("trade story generation failed for %s", tx)
                return
            stories[tx] = {
                **result, "facts_hash": h,
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        done += 1
        if progress_cb is not None:
            await progress_cb("stories",
                              f"Writing trade stories {done}/{len(pending)}")

    await asyncio.gather(*(_one(tx, f, h) for tx, f, h in pending))
    return stories, dossiers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest ../tests/test_story_gen.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/story_gen.py tests/test_story_gen.py
git commit -m "feat(api): incremental concurrent trade-story generation"
```

---

### Task 8: Hook generation into `GraderService.run`

**Files:**
- Modify: `api/app/services/grader.py`
- Modify: `api/app/services/grader_io.py` (ensure `positions` + `owners_display` in `supporting`)
- Test: `tests/test_grader_story_hook.py`

> The hook is best-effort: if `ANTHROPIC_API_KEY` is missing or generation
> raises, refresh still completes graded and records a warning. The prior cache
> entry (if any) supplies `prior_stories` for the incremental skip. Reuses the
> dashboard `owners` map for display names; adds a `positions` map from the raw
> players already fetched.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grader_story_hook.py
import os
import asyncio
from datetime import datetime

from app.services.grader import GraderService
from app.services.chain_cache import ChainCacheEntry


class _FakeClient:
    async def walk_league_history(self, lid):
        from types import SimpleNamespace
        return [SimpleNamespace(league_id="L", season=2024, name="Bros",
                                total_rosters=10, playoff_week_start=15)]
    async def get_players(self):
        return {"p1": {"full_name": "Bijan Robinson", "position": "RB"}}
    async def close(self): ...


async def _supporting(*a, **k):
    return dict(
        ktc_by_player_id={}, matchups={}, roster_to_user_by_league={},
        playoff_weeks_by_league={"L": 15}, league_season_by_id={"L": 2024},
        owners={"u_mike": {"owner_name": "Mike"}, "u_tom": {"owner_name": "Tom"}},
        league_name_by_id={"L": "Bros"}, pick_value_table={}, warnings=[],
    )


async def _history(*a, **k):
    from sleeper_dynasty.models.trade import (
        PlayerAsset, PickAsset, Trade, TradeSide, ResolvedTrade)
    pick = PickAsset(2025, 1, "u_mike")
    pl = PlayerAsset("p1", "Bijan Robinson")
    mike = TradeSide("u_mike", [pl], [pick]); tom = TradeSide("u_tom", [pick], [pl])
    t = Trade("t1", "L", 2024, 1, datetime(2024, 6, 1),
              {"u_mike": mike, "u_tom": tom})
    return [ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})]


def test_run_populates_trade_stories_with_injected_writer(monkeypatch):
    class FakeWriter:
        def write(self, facts):
            return {"verdict": "Mike robbed Tom.", "body": "Not close."}

    events = []
    async def cb(stage, message, **x): events.append(stage)

    async def go():
        svc = GraderService()
        return await svc.run(
            client=_FakeClient(), current_league_id="L", progress_cb=cb,
            cache_dir=None, _build_trade_history=_history,
            _pull_supporting_data=_supporting, _story_writer=FakeWriter(),
        )

    entry: ChainCacheEntry = asyncio.run(go())
    assert entry.trade_stories["t1"]["verdict"] == "Mike robbed Tom."
    assert "u_mike" in entry.owner_dossiers
    assert "stories" in events
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest ../tests/test_grader_story_hook.py -v`
Expected: FAIL — `run()` has no `_story_writer` param / `entry.trade_stories` empty.

- [ ] **Step 3: Write minimal implementation**

In `api/app/services/grader_io.py::pull_supporting_data`, add to the returned
dict (the raw players are already in scope as `players`):

```python
        "owners_display": {uid: (o.get("owner_name") or uid)
                           for uid, o in owners.items()},
        "positions": {pid: raw.get("position")
                      for pid, raw in players.items()
                      if isinstance(raw, dict)},
```

In `api/app/services/grader.py`, extend `run`'s signature and add the hook
before building `entry`:

```python
    # add params to run():
        _story_writer=None,

    # ... after the at_trade block, before `await progress_cb("done", ...)`:
        await progress_cb("stories", "Writing trade stories")
        try:
            from app.services.story_gen import generate_stories
            writer = _story_writer
            if writer is None:
                from sleeper_dynasty.llm.trade_story_writer import TradeStoryWriter
                writer = TradeStoryWriter()  # reads ANTHROPIC_API_KEY
            prior = {}
            if cache_dir is not None:
                from app.services.chain_cache import ChainCache
                prev = ChainCache(cache_dir=cache_dir).read(
                    current_league_id, max_age_seconds=10 ** 9)
                prior = prev.trade_stories if prev else {}
            # supporting needs owners_display; fall back if absent.
            supporting.setdefault(
                "owners_display",
                {uid: (o.get("owner_name") or uid)
                 for uid, o in supporting["owners"].items()})
            trade_stories, owner_dossiers = await generate_stories(
                resolved=resolved, grades=grades, supporting=supporting,
                prior_stories=prior, writer=writer, progress_cb=progress_cb,
            )
        except Exception as e:  # never fail refresh on story errors
            log.exception("trade story stage failed")
            trade_stories, owner_dossiers = {}, {}
            supporting.setdefault("warnings", []).append(
                f"trade stories skipped: {e}")
```

Then add the two new fields to the `ChainCacheEntry(...)` constructor:

```python
            trade_stories=trade_stories,
            owner_dossiers=owner_dossiers,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest ../tests/test_grader_story_hook.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `cd api && python -m pytest ../tests -q`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
git add api/app/services/grader.py api/app/services/grader_io.py \
  tests/test_grader_story_hook.py
git commit -m "feat(api): generate trade stories during refresh"
```

---

## Phase 4 — API surface

### Task 9: `TradeStory` response model + wire into `build_trade_detail`

**Files:**
- Modify: `api/app/models/trade.py`
- Modify: `api/app/services/trade_view.py`
- Test: `tests/test_trade_view_story.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_view_story.py
from app.services.chain_cache import ChainCacheEntry
from app.services.trade_view import build_trade_detail


def _entry():
    rt = {"trade": {"transaction_id": "t1", "traded_at": "2024-06-01T00:00:00",
                    "week": 1, "season": 2024, "league_id": "L"},
          "sides": {"u_mike": {"received": [], "given": []}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[rt], grades={},
        owners={"u_mike": {"owner_name": "Mike"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2024},
        cached_at="now",
        trade_stories={"t1": {"verdict": "Mike robbed Tom.", "body": "Nope.",
                              "facts_hash": "h", "generated_at": "now"}},
    )


def test_detail_includes_story_when_present():
    resp = build_trade_detail(_entry(), "t1")
    assert resp.story is not None
    assert resp.story.verdict == "Mike robbed Tom."


def test_detail_story_none_when_absent():
    e = _entry(); e.trade_stories = {}
    resp = build_trade_detail(e, "t1")
    assert resp.story is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest ../tests/test_trade_view_story.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'story'`.

- [ ] **Step 3: Write minimal implementation**

```python
# api/app/models/trade.py  — add model + field
class TradeStory(BaseModel):
    verdict: str
    body: str
    generated_at: str | None = None


# inside TradeDetailResp, add:
    story: TradeStory | None = None
```

```python
# api/app/services/trade_view.py  — import + build the story, pass to resp
from app.models.trade import TradeDetailResp, TradeSideView, TradeStory

# ... after computing `sides`, before the return:
    raw_story = (entry.trade_stories or {}).get(trade_id)
    story = (
        TradeStory(verdict=raw_story.get("verdict", ""),
                   body=raw_story.get("body", ""),
                   generated_at=raw_story.get("generated_at"))
        if raw_story else None
    )

# add `story=story,` to the TradeDetailResp(...) constructor.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest ../tests/test_trade_view_story.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add api/app/models/trade.py api/app/services/trade_view.py \
  tests/test_trade_view_story.py
git commit -m "feat(api): expose trade story on the detail response"
```

---

## Phase 5 — Frontend (Format A)

### Task 10: Types + offseason label util

**Files:**
- Modify: `web/lib/types.ts`
- Create: `web/lib/season-week.ts`
- Test: `web/tests/season-week.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/season-week.test.ts
import { describe, it, expect } from "vitest";
import { seasonWeekLabel } from "@/lib/season-week";

describe("seasonWeekLabel", () => {
  it("labels summer trades as Offseason", () => {
    expect(seasonWeekLabel("2024-06-14", 1)).toBe("Offseason");
  });
  it("labels in-season trades by week", () => {
    expect(seasonWeekLabel("2024-10-06", 5)).toBe("Week 5");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npx vitest run tests/season-week.test.ts --config tests/vitest.config.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```ts
// web/lib/season-week.ts
// Dynasty in-season trading happens only Sep-Nov (deadline ~week 11).
// Mirror of the engine's IN_SEASON_MONTHS so labels match the story packet.
const IN_SEASON_MONTHS = new Set([9, 10, 11]);

export function seasonWeekLabel(dateIso: string, week: number): string {
  const month = Number(dateIso.slice(5, 7)); // "YYYY-MM-DD"
  return IN_SEASON_MONTHS.has(month) ? `Week ${week}` : "Offseason";
}
```

```ts
// web/lib/types.ts  — add near TradeDetailResp
export interface TradeStory {
  verdict: string;
  body: string;
  generated_at?: string;
}

// add to the TradeDetailResp interface:
//   story?: TradeStory | null;
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `web/`): `npx vitest run tests/season-week.test.ts --config tests/vitest.config.ts`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add web/lib/season-week.ts web/lib/types.ts web/tests/season-week.test.ts
git commit -m "feat(web): season/week label util + TradeStory type"
```

---

### Task 11: `TradeStory` component

**Files:**
- Create: `web/components/TradeStory.tsx`
- Test: `web/tests/TradeStory.test.tsx`

> Format A: bold verdict headline, story body (paragraphs split on blank lines,
> no markdown lib), then a `<details>`-based "Show the receipts" disclosure. The
> caller passes the already-built receipts node as `children` so this component
> stays focused on the story.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/TradeStory.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeStory } from "@/components/TradeStory";

describe("TradeStory", () => {
  const story = { verdict: "Mike robbed Tom.", body: "One.\n\nTwo." };

  it("renders the verdict and each body paragraph", () => {
    render(<TradeStory story={story}>receipts-here</TradeStory>);
    expect(screen.getByText("Mike robbed Tom.")).toBeTruthy();
    expect(screen.getByText("One.")).toBeTruthy();
    expect(screen.getByText("Two.")).toBeTruthy();
  });

  it("hides the receipts behind a disclosure", () => {
    render(<TradeStory story={story}>the-receipts</TradeStory>);
    expect(screen.getByText("Show the receipts")).toBeTruthy();
    expect(screen.getByText("the-receipts")).toBeTruthy(); // in DOM, collapsed
  });

  it("falls back to receipts when there is no story", () => {
    render(<TradeStory story={null}>only-receipts</TradeStory>);
    expect(screen.queryByText("Show the receipts")).toBeNull();
    expect(screen.getByText("only-receipts")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npx vitest run tests/TradeStory.test.tsx --config tests/vitest.config.ts`
Expected: FAIL — component not found.

- [ ] **Step 3: Write minimal implementation**

```tsx
// web/components/TradeStory.tsx
import { ReactNode } from "react";
import { TradeStory as Story } from "@/lib/types";

interface Props {
  story: Story | null | undefined;
  children: ReactNode; // the receipts panel
}

export function TradeStory({ story, children }: Props) {
  if (!story) {
    return <div className="mt-8">{children}</div>;
  }
  const paragraphs = story.body.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  return (
    <section className="mt-6">
      <h1 className="text-3xl font-extrabold tracking-tight text-balance">
        {story.verdict}
      </h1>
      <div className="mt-4 max-w-[68ch] space-y-3 text-[15px] leading-relaxed text-ink">
        {paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
      <details className="mt-8 group">
        <summary className="cursor-pointer select-none font-mono text-[11px] uppercase tracking-widest text-dim hover:text-ink">
          Show the receipts
        </summary>
        <div className="mt-5">{children}</div>
      </details>
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `web/`): `npx vitest run tests/TradeStory.test.tsx --config tests/vitest.config.ts`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add web/components/TradeStory.tsx web/tests/TradeStory.test.tsx
git commit -m "feat(web): TradeStory component (verdict + body + receipts)"
```

---

### Task 12: Wire the detail page + fix the offseason label on the card

**Files:**
- Modify: `web/app/league/[id]/trade/[tid]/page.tsx`
- Modify: `web/components/TradeCard.tsx:18-20`
- Test: manual + existing vitest + `npm run build`

> The existing `TradeSidePanel` becomes the *receipts* content passed as
> `children`. This task wires Format A and fixes the labels; the receipts panel
> is de-nested and put into plain language in Task 13.

- [ ] **Step 1: Update the trade-detail page**

Replace the header + side grid in `page.tsx` so the story leads and the side
panels become the receipts:

```tsx
// web/app/league/[id]/trade/[tid]/page.tsx — imports
import { TradeStory } from "@/components/TradeStory";
import { seasonWeekLabel } from "@/lib/season-week";

// replace the <h1>...</h1> + grid block with:
        <div className="mt-6 font-mono text-[10px] uppercase tracking-widest text-dim">
          Trade · {data.date} · {seasonWeekLabel(data.date, data.week)} · {data.league_name} · {data.season}
        </div>
        <TradeStory story={data.story}>
          <div className={`grid gap-5 ${gridClass}`}>
            {data.sides.map((s) => (
              <TradeSidePanel key={s.user_id} side={s} displayNames={displayNames} />
            ))}
          </div>
        </TradeStory>
```

(When `data.story` is null the page degrades to the receipts grid, unchanged.)

- [ ] **Step 2: Fix the card label**

```tsx
// web/components/TradeCard.tsx — import + replace the date/week line
import { seasonWeekLabel } from "@/lib/season-week";

// was: {trade.date} · Week {trade.week}
      <div className="font-mono text-[10px] text-dim mb-1 tracking-wide">
        {trade.date} · {seasonWeekLabel(trade.date, trade.week)}
      </div>
```

- [ ] **Step 3: Run web unit tests + typecheck/build**

Run (from `web/`): `npx vitest run --config tests/vitest.config.ts`
Expected: PASS (all suites, including the new ones).

Run (from `web/`): `npm run build`
Expected: build succeeds (types valid; `story` optional on `TradeDetailResp`).

- [ ] **Step 4: Commit**

```bash
git add web/app/league/[id]/trade/[tid]/page.tsx web/components/TradeCard.tsx
git commit -m "feat(web): story-led trade detail page + offseason labels"
```

---

### Task 13: De-nest + plain-language receipts panel

**Files:**
- Modify: `web/components/TradeSidePanel.tsx` (full rewrite)
- Test: `web/tests/TradeSidePanel.test.tsx`

> Kills the nested cards (the critique's P1) and the SW/SPC/WSP acronym soup. The
> outer panel is the only card; inside, metrics are borderless rows grouped under
> plain-language headings (Market value / Points / Usage). Values keep their
> `+`/`−` sign so meaning is never carried by color alone. Reuses `OwnerLabel`
> and `AssetRender` exactly as before; only the metric chrome changes.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/TradeSidePanel.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeSidePanel } from "@/components/TradeSidePanel";

const side = {
  user_id: "u1", owner_name: "Mike", team_name: "Team", avatar_url: undefined,
  received: [], given: [],
  snapshot_ktc_swing: 1840, hindsight_production_swing: 41.2,
  hindsight_started_swing: 30, at_trade_ktc_swing: 1500, aged_ktc_swing: 340,
  at_trade_approx: false, at_trade_snapshot_date: null,
  realized: { starter_weeks: 14, starter_points_contributed: 210,
              win_share_points: 120, decisive_starts: 3, playoff_starts: 2 },
} as any;

describe("TradeSidePanel receipts", () => {
  it("uses plain-language labels, not acronyms", () => {
    render(<TradeSidePanel side={side} displayNames={{}} />);
    expect(screen.getByText(/Market value today/i)).toBeTruthy();
    expect(screen.getByText(/Weeks started/i)).toBeTruthy();
    expect(screen.queryByText(/^WSP$/)).toBeNull();
    expect(screen.queryByText(/^SPC$/)).toBeNull();
  });

  it("shows a signed value so meaning is not color-only", () => {
    render(<TradeSidePanel side={side} displayNames={{}} />);
    expect(screen.getByText(/\+1,840/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npx vitest run tests/TradeSidePanel.test.tsx --config tests/vitest.config.ts`
Expected: FAIL — current panel renders "Value today" / acronyms, not these labels.

- [ ] **Step 3: Rewrite the component (de-nested, plain language)**

```tsx
// web/components/TradeSidePanel.tsx
import { TradeSideView } from "@/lib/types";
import { AssetRender } from "./AssetRender";
import { OwnerLabel } from "./OwnerLabel";

interface Props {
  side: TradeSideView;
  displayNames: Record<string, string>;
}

function signed(n: number): string {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(Math.round(n)).toLocaleString()}`;
}
function tone(n: number): string {
  return n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-dim";
}

export function TradeSidePanel({ side, displayNames }: Props) {
  const market: { label: string; v: number | null }[] = [
    { label: "Market value today", v: side.snapshot_ktc_swing },
    { label: "Value when traded", v: side.at_trade_ktc_swing },
    { label: "Change since", v: side.aged_ktc_swing },
  ];
  const points: { label: string; v: number }[] = [
    { label: "Total points since", v: side.hindsight_production_swing },
    { label: "Points in starting lineups", v: side.hindsight_started_swing },
  ];
  const usage: { label: string; v: number }[] = [
    { label: "Weeks started", v: side.realized.starter_weeks },
    { label: "Game-deciding starts", v: side.realized.decisive_starts },
    { label: "Playoff starts", v: side.realized.playoff_starts },
  ];

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div className="mt-5">
      <div className="text-[11px] font-semibold text-dim mb-1.5">{title}</div>
      <div className="divide-y divide-divider/60">{children}</div>
    </div>
  );
  const Asset = ({ title, list }: { title: string; list: TradeSideView["received"] }) => (
    <div className="mt-4">
      <div className="text-[11px] font-semibold text-dim mb-1">{title}</div>
      <ul className="space-y-1">
        {list.length === 0 && <li className="text-dim text-[12px]">—</li>}
        {list.map((a, i) => (
          <li key={i} className="text-[13px]"><AssetRender asset={a} displayNames={displayNames} /></li>
        ))}
      </ul>
    </div>
  );

  return (
    <div className="bg-surface border border-divider rounded-card p-5">
      <OwnerLabel
        owner={{ user_id: side.user_id, owner_name: side.owner_name,
                 team_name: side.team_name, avatar_url: side.avatar_url }}
        variant="full"
      />
      <Asset title="Received" list={side.received} />
      <Asset title="Gave" list={side.given} />

      <Section title="Market value">
        {market.map((m) => (
          <div key={m.label} className="flex items-baseline justify-between py-1.5 text-[13px]">
            <span className="text-dim">{m.label}</span>
            <span className={`tabular font-semibold ${m.v == null ? "text-dim" : tone(m.v)}`}>
              {m.v == null ? "—" : signed(m.v)}
            </span>
          </div>
        ))}
      </Section>
      <Section title="Points">
        {points.map((m) => (
          <div key={m.label} className="flex items-baseline justify-between py-1.5 text-[13px]">
            <span className="text-dim">{m.label}</span>
            <span className={`tabular font-semibold ${tone(m.v)}`}>{m.v > 0 ? "+" : ""}{m.v.toFixed(1)}</span>
          </div>
        ))}
      </Section>
      <Section title="Usage">
        {usage.map((m) => (
          <div key={m.label} className="flex items-baseline justify-between py-1.5 text-[13px]">
            <span className="text-dim">{m.label}</span>
            <span className="tabular font-semibold">{Math.round(m.v)}</span>
          </div>
        ))}
      </Section>
    </div>
  );
}
```

- [ ] **Step 4: Run test + full web suite**

Run (from `web/`): `npx vitest run tests/TradeSidePanel.test.tsx --config tests/vitest.config.ts`
Expected: PASS (2 passed).
Run (from `web/`): `npx vitest run --config tests/vitest.config.ts`
Expected: PASS (all suites).

- [ ] **Step 5: Commit**

```bash
git add web/components/TradeSidePanel.tsx web/tests/TradeSidePanel.test.tsx
git commit -m "feat(web): de-nest receipts panel, plain-language labels"
```

---

### Task 14: Docs + config

**Files:**
- Modify: `.env.example` (root and/or `api/`), `README.md`, `CLAUDE.md`

- [ ] **Step 1: Document the new env var + behavior**

- Add `ANTHROPIC_API_KEY=` to `.env.example` with a comment: required by the
  backend for trade-story generation during refresh; if unset, refresh still
  completes and stories are skipped with a warning.
- Add a short "Trade stories" note to `README.md` (engine fact packet → Claude
  writer → cached in `ChainCacheEntry`, generated during refresh).
- Note in `CLAUDE.md` under conventions: trade stories follow the recap pattern
  (`engine/trade_story.py` + `llm/trade_story_writer.py`); offseason rule lives
  in `engine/trade_story.py::IN_SEASON_MONTHS` and `web/lib/season-week.ts`.

- [ ] **Step 2: Commit**

```bash
git add .env.example README.md CLAUDE.md
git commit -m "docs: document trade-story generation + ANTHROPIC_API_KEY"
```

---

## Final verification

- [ ] Run the full backend suite: `cd api && python -m pytest ../tests -q` → all PASS.
- [ ] Run the web suite: from `web/`, `npx vitest run --config tests/vitest.config.ts` → all PASS.
- [ ] Build the web app: from `web/`, `npm run build` → success.
- [ ] Manual smoke (optional, needs `ANTHROPIC_API_KEY` + a league): `make dev-api` + `make dev-web`, refresh a league, open a trade, confirm the verdict + story render and "Show the receipts" expands; confirm an offseason trade reads "Offseason," not "Week 1."

---

## Self-review notes (author)

- **Spec coverage:** verdict/winner (Tasks 4, 5, 11), owner-strategy inference
  (Task 2), player arcs incl. playoff split (Task 3), offseason fix (Tasks 2,
  10, 12), bold/funny voice dialed by lopsidedness (Task 5 persona), grounded
  facts-only (Tasks 1-5), eager+incremental+concurrent generation (Tasks 7-8),
  cache (Task 6), Format A with receipts disclosure (Tasks 11-12), tests
  throughout, config/docs (Task 13). All spec sections map to a task.
- **Offseason heuristic** is the one spec "open question"; encoded concretely as
  `IN_SEASON_MONTHS` in both engine and web with a refine-later comment.
- **Type consistency:** `facts_hash`, `generate_stories`, `TradeStory`
  (`verdict`/`body`/`generated_at`), `seasonWeekLabel`, and `build_*` signatures
  are referenced identically across tasks.
- **Receipts de-nesting** (critique P1) is now in-scope as Task 13.
- **Out of scope (per spec):** no manual profile editing, no regenerate button,
  no owner-page/dashboard stories.
