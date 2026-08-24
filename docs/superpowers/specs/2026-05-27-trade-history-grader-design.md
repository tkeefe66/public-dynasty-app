# Trade History & Grader — Design Spec

**Date:** 2026-05-27
**Owner:** Tom
**Status:** Implemented (with revisions — see "Post-implementation revisions" at the bottom)

## Goal

Add a new CLI subcommand, `sleeper-dynasty trades <username>`, that pulls the
complete trade history across a dynasty league's full season chain (walking
`previous_league_id` back to the league's origin) and grades every trade —
plus every owner's full trading record — through three independent lenses:

1. **Snapshot KTC** — current market value swing
2. **Hindsight production** — fantasy points actually scored since the trade
3. **Realized impact** — starter usage, win-share points, decisive games,
   playoff appearances

The output is a standalone **Google Sheets** report (originally specified as
Google Docs — see revisions) with three tabs: Definitions (column glossary),
Trade Ledger (one row per trade-side), and Owner Standings (one row per
owner, sorted by Net KTC).

## Non-goals (v1)

- Grading waiver / free-agent transactions. The data model is designed to
  extend to these later, but only multi-party trades are graded in v1.
- Historical KTC snapshots. KTC does not expose historical values, so
  "value at trade time" is **not** a supported lens. All snapshot grading
  uses today's KTC values.
- Valuing FAAB transferred in trades. We record FAAB transfers in the trade
  record but do not assign them dollar-or-KTC value in v1.
- Integration into the existing `analyze` report. The trades report is a
  standalone subcommand. A future flag (`analyze --include-trades`) can
  reuse the same data layer if desired.

## Architecture

Layered pipeline mirroring the existing project structure
(`api → models → engine → output`).

```
src/sleeper_dynasty/
  api/sleeper.py
    + get_transactions(league_id, week) -> list[dict]
    + get_drafts(league_id) -> list[dict]
    + get_draft_picks(draft_id) -> list[dict]
    + get_users(league_id) -> dict[user_id, dict]
    + get_league(league_id) -> tuple[League, str | None]
    + walk_league_history(league_id) -> list[League]   # newest → oldest

  models/trade.py            # NEW
    Trade, TradeSide, TradeAsset (PlayerAsset|PickAsset|FaabAsset),
    ResolvedTrade, TradeGrade, RealizedImpact, OwnerTradeRecord

  engine/
    trade_history.py         # NEW
      BLACKLISTED_TRANSACTION_IDS  # frozenset — junk tx filtered at fetch
      normalize_trade(raw_tx, roster_to_user, league_id, season) -> Trade
      resolve_assets(...) -> list[ResolvedTrade]
      build_trade_history(client, current_league_id, player_names)
        -> list[ResolvedTrade]   # newest-first, picks resolved,
                                  # player names backfilled

    trade_grader.py          # NEW
      grade_snapshot_value(rt, ktc_values, fmt) -> dict[uid, float]
      grade_hindsight_production(rt, matchups, roster_to_user_by_league,
                                 league_season_by_id) -> dict[uid, float]
      grade_realized_impact(rt, matchups, roster_to_user_by_league,
                            playoff_weeks_by_league, league_season_by_id)
        -> tuple[dict[uid, RealizedImpact], dict[uid, RealizedImpact]]
      grade_trade(rt, ktc_values, matchups, roster_to_user_by_league,
                  playoff_weeks_by_league, league_season_by_id, fmt)
        -> TradeGrade
      aggregate_owner_records(grades, display_names)
        -> dict[uid, OwnerTradeRecord]

  output/google_sheets.py     # NEW (replaces the originally-planned
                              # google_docs additions)
    + create_spreadsheet() -> str
    + write_definitions(spreadsheet_id)
    + write_trade_ledger(spreadsheet_id, resolved_trades, grades,
                         display_names, league_name_by_id)
    + write_owner_standings(spreadsheet_id, records)
    + set_sharing(spreadsheet_id, private=False)
    + get_url(spreadsheet_id) -> str

  cli.py
    + `trades` subcommand
```

### Stable owner identity

`roster_id` is league-scoped and can shift across seasons; owners come and
go. All aggregation happens by **Sleeper `user_id`**. For each league in
the chain we fetch `/league/{id}/users` and `/league/{id}/rosters` to build
a per-season `roster_id → user_id` mapping. The display name shown in the
output is the user's most-recent `display_name` or `team_name`. Departed
owners are still graded and listed; their last known name is used.

### Asset model

```python
class TradeAsset(ABC): ...

@dataclass
class PlayerAsset(TradeAsset):
    player_id: str
    name: str

@dataclass
class PickAsset(TradeAsset):
    season: int
    round: int
    original_owner_user_id: str  # stable identity

@dataclass
class FaabAsset(TradeAsset):
    amount: int
```

**Pick resolution rule:** if the draft for `(season, round)` has been
completed, we use Sleeper's `draft_picks` endpoint — which returns
`draft_slot`, `round`, `pick_no`, `roster_id`, and `player_id` per pick —
to find the row matching `(round, draft_slot of original_owner_user_id
for that season)` and replace the `PickAsset` with a `PlayerAsset` for
the drafted player. Otherwise the pick remains as `PickAsset` and is valued
against KTC's rookie-pick table (snapshot lens) or contributes zero to the
other two lenses.

## Data flow

```
1. Resolve user_id from username (existing flow).
2. Resolve current league via _select_league (existing flow).
3. walk_league_history(current_league_id) → ordered list of leagues
   (newest → oldest), terminating when previous_league_id is null.
4. For each league in chain:
   a. get_users(league_id)
   b. get_rosters(league_id)              → roster_id → user_id (this season)
   c. get_transactions(league_id, week)   for week in 1..18
      filter type=="trade", status=="complete"
   d. get_drafts(league_id) + get_draft_picks(draft_id)
   e. get_matchups(league_id, week)       for weeks 1..max_played_week
      (max_played_week = highest week with non-null points in the matchups
       response; for completed seasons this includes playoff weeks)
5. Normalize: build Trade objects with sides keyed by user_id, each side
   carrying received[] and given[] assets.
6. Resolve assets: convert resolved PickAssets to PlayerAssets via draft
   join; leave unresolved picks as-is.
7. Grade each trade (three lenses, below).
8. Aggregate per owner.
9. Emit Google Doc.
```

Historical seasons' data is immutable; cached with effectively-infinite TTL.

## Grading lenses

For every trade, all three are computed independently. Each is reported
per-side.

### Lens 1 — Snapshot KTC value swing

```
side_value[user_id] = Σ KTC value (today) of assets received[user_id]
                    − Σ KTC value (today) of assets given[user_id]
```

- `PlayerAsset` → matched current KTC player value (0 + warning if no match).
- Resolved `PickAsset` (now a `PlayerAsset`) → drafted player's KTC value.
- Unresolved `PickAsset` → KTC rookie-pick value table.
- `FaabAsset` → 0 (v1).

Output: `"Tom: +1450 KTC value swing  ·  Jim: −1450"`.

### Lens 2 — Hindsight production swing

For each `PlayerAsset` received, sum fantasy points scored by that player
**for the receiving team** in every week from the trade date through the
latest played week, across all leagues in the chain.

```
received_production[side] = Σ player_points[week]
                            for each player ∈ received[side],
                            for weeks the player was on receiver's roster,
                            from trade_date through latest_played_week
```

We compute a symmetric "phantom production" for each `PlayerAsset` given
(what the player actually scored anywhere in those weeks, on whatever team
ended up rostering them). The hindsight swing is
`received_production − given_phantom_production`.

For resolved picks: production accrues only from the player's first
post-draft rostered week.
For unresolved picks: contributes zero to this lens.

Output: `"Tom: +387.4 production points  ·  Jim: −387.4"`.

### Lens 3 — Realized impact

A bundle of five sub-metrics per side, **not** collapsed into a single
number:

| Metric | Definition |
|---|---|
| Starter weeks (SW) | Count of weeks the received player was in `starters` post-trade |
| Starter points contributed (SPC) | Σ points scored as a starter post-trade |
| Win-share points (WSP) | Σ starter points in weeks the receiving team won |
| Decisive starts (DS) | Count of weeks the player started, team won, and player points > margin of victory |
| Playoff starts (PS) | Count of starts during playoff weeks |

Output:
```
Tom (Bijan):  18 SW · 286 SPC · 198 WSP · 4 DS · 2 PS
Jim (Adams):   8 SW · 102 SPC ·  60 WSP · 1 DS · 0 PS
```

### Per-owner aggregation

| Column | Source |
|---|---|
| Trades | trade count |
| Net KTC | Σ Lens 1 swing |
| Net Production | Σ Lens 2 swing |
| Starter Wks Gained | Σ Lens 3 SW (received) − Σ Lens 3 SW (given, phantom) |
| Decisive Starts Gained | Σ Lens 3 DS (received) |
| Playoff Starts Gained | Σ Lens 3 PS (received) |
| Best Trade | trade with highest swing in this owner's favor |
| Worst Trade | trade with worst swing against this owner |

No composite "letter grade." Three lenses stay independent; the reader
judges.

## Output

A new Google Sheets spreadsheet with **three** tabs. Sheets was chosen over
the originally-specified Docs (see revisions) because trade data is
inherently tabular — Sheets enables sorting, filtering, and pivoting, and
sidesteps the Docs API's 60-write-per-minute rate limit that caused multi-
minute runs in the Docs prototype.

### Tab 1 — Definitions

A built-in column glossary. Two sections (Trade Ledger and Owner Standings)
each list every column with a one-line definition, followed by a Notes
section covering KTC snapshot semantics, post-trade scope, FAAB handling,
and KTC name-match gaps. Headers and section labels are bold; column B
auto-wraps so long definitions stay readable.

### Tab 2 — Trade Ledger (one row per trade-side)

Each trade contributes N rows (one per participant). Columns:

```
Trade Date | Week | Season | League | Owner | Received | Gave |
Snapshot KTC | Hindsight Pts | Starter Wks | SPC | WSP | DS | PS |
Trade ID
```

This shape makes filtering ("show me all of Tom's trades"), sorting
("biggest KTC wins"), and pivoting trivial. Trade-level data is repeated
on each side row — Sheets handles that fine.

`Received` / `Gave` cells join assets with `; ` separators. Picks are
rendered as `2025 round 2 (from <original drafter display name>)`.
Resolved picks render as the drafted player.

### Tab 3 — Owner Standings

One row per user who has been in the league at any point in the chain.
Default sort: Net KTC descending. Columns:

```
Owner | Trades | Net KTC | Net Production | SW Gained |
DS Gained | PS Gained | Best Trade | Worst Trade
```

### Formatting (both data tabs)

- Header row bold and frozen
- Auto-resized columns where it helps readability

## CLI

```
sleeper-dynasty trades <username>
  [--season SEASON]            # entry-point season; defaults to current
  [--no-cache]                 # invalidate full cache (existing behavior)
  [--refresh-trades]           # invalidate only transaction/draft/matchup caches
  [--private]                  # private Google Doc (existing flag)
```

## Caching

New keys on `FileCache`:

| Key pattern | TTL (completed season) | TTL (current season) |
|---|---|---|
| `transactions_{league_id}_w{week}.json` | 1 year | 1 hour |
| `drafts_{league_id}.json` | 1 year | 1 hour until draft complete |
| `draft_picks_{draft_id}.json` | 1 year | n/a (immutable once drafted) |
| `matchups_{league_id}_w{week}.json` | 1 year | 1 hour |
| `league_meta_{league_id}.json` | 1 year | 1 hour for active league |
| `users_{league_id}.json` | 1 year | 1 day for active league |

`--refresh-trades` invalidates the above without nuking the players or
KTC caches (which are slower and rarely change behaviour for this command).

## Error handling

| Condition | Behavior |
|---|---|
| Missing `previous_league_id` | Terminate chain walk; this is the origin. |
| Missing KTC value for a player | Treat as 0 for snapshot lens; warn in log. |
| KTC service entirely unavailable | Snapshot lens degrades to 0 across the board; lenses 2 and 3 still computed; mention in footnote. |
| Roster_id → user_id mapping miss for a historical trade | Fall back to `Owner #<roster_id>` placeholder; warn in log. |
| Pick still listed in transaction but draft never happened (data anomaly) | Keep as `PickAsset`; warn in log. |
| Pre-KTC-era trade | Same as missing KTC values. |
| 3+ team trade | Supported; each side graded independently against the assets they received vs. gave. |
| FAAB-only trade | Recorded; all three lenses return 0. |
| Failed Sleeper API call (transient) | One retry with exponential backoff (httpx default); on second failure, log and skip that fetch (downstream gracefully handles missing data). |

## Performance

Rough estimate for a 5-season dynasty chain with ~10 trades/season:
~150 first-time API calls (transactions × 18 weeks × 5 seasons +
matchups + drafts + users). Calls are parallelizable within each league
in chunks (already the pattern used by `analyze`). Subsequent runs hit
cache and complete in seconds.

## Testing

### Unit tests

- **`api/sleeper.py`** — Each new method, tested with `respx`/`httpx_mock`
  against canned Sleeper responses captured to fixtures.
- **`engine/trade_history.py`**
  - `walk_league_history`: chain termination, single-season league, missing
    parent.
  - Trade normalization: 2-team trade, 3-team trade, picks-only, FAAB-only,
    mixed.
  - Asset resolution: resolved pick, unresolved pick, missing player.
- **`engine/trade_grader.py`**
  - Hand-built fixtures covering each lens independently.
  - Cross-cutting: trade involving a pick that resolved into another
    player who was then traded again (full chain).
  - Edge: received player never started (zero impact, nonzero value).
  - Edge: received player carried team in playoffs (high impact, low
    value at time).

### End-to-end smoke

A single fixture league with 2–3 hand-built trades; assert grader output
matches hand-computed expected values for all three lenses.

## Out of scope (future work)

- Waiver / free-agent grading
- Historical KTC snapshots (third-party effort, not from KTC directly)
- `analyze --include-trades` flag to embed in main report
- Owner activity timeline (when each user joined / left the league)
- Visual charts (cumulative net KTC over time per owner, etc.)
- Replace v1's `_derive_user_slot_map` heuristic with Sleeper's
  `draft.slot_to_roster_id` field for correct slot attribution on traded
  round-1 picks

## Post-implementation revisions

The original spec called for Google Docs output and assumed certain Sleeper
field semantics. Real-data testing surfaced four issues that required design
changes; this section documents the deviations.

### 1. Output pivoted from Google Docs to Google Sheets

**Surfaced:** First real-data run produced a Google Doc with cells of
multi-line bullet lists, page breaks splitting trade tables in half, and
multi-minute runtimes from hitting the Docs API's 60-write-per-minute rate
limit. User feedback: "this looks terrible."

**Change:** New `output/google_sheets.py` module emits a three-tab
spreadsheet (Definitions, Trade Ledger, Owner Standings) using a single
`spreadsheets.values.update` per tab. One row per trade-side instead of
one table per trade enables sort/filter/pivot directly in Sheets. The old
`write_tab_trade_ledger` / `write_tab_owner_standings` methods on
`GoogleDocsReport` were removed. The `analyze` subcommand continues to use
`GoogleDocsReport` unchanged.

**OAuth scope change:** Added `spreadsheets` scope; first run after the
pivot re-prompts for consent.

### 2. Season comparison bug in `_is_post_trade`

**Surfaced:** A 2026 trade made days ago showed `Hindsight pts: −406.8`
and `17 SW · 4 PS` despite the 2026 NFL season not having started.

**Cause:** `_is_post_trade` assumed the caller had pre-filtered matchups
to only chain-forward leagues. The orchestrator actually passed every
season's matchups, so for a 2026 trade, every week of 2023/2024/2025
counted as "post-trade" — three years of pre-trade production was being
attributed to a fresh trade.

**Change:** Thread `league_season_by_id: dict[str, int]` through
`grade_hindsight_production`, `grade_realized_impact`, and `grade_trade`.
`_is_post_trade` now compares `(matchup_season, week)` against
`(trade_season, trade_week)` properly: later season → True, earlier
season → False, same season → `week > trade_week`.

### 3. PlayerAsset names never populated; pick origin shown as raw user_id

**Surfaced:** Trade ledger rendered as `Received: • • •` with empty
bullets. Pick origins showed raw Sleeper user_ids like
`(from 900000000000000007)`.

**Cause:** `normalize_trade` created `PlayerAsset(player_id=X, name="")`
and never populated the name — the players blob was only consulted by
`resolve_assets` for picks. The asset renderer showed `original_owner_user_id`
literally instead of looking up the user's display name.

**Change:** `build_trade_history` now post-walks every PlayerAsset across
every side and fills in `name` from the `player_names` map. The Sheets
`_render_asset` helper takes a `display_names` parameter and resolves
pick origins through it.

### 4. Swapped `roster_id` / `previous_owner_id` semantics on draft_picks

**Surfaced:** User reported 3-team trades the league never made, a player
(Brock Bowers) appearing in trades he was never part of, and a pick
"missing" from a trade he remembered.

**Cause:** Sleeper's transaction `draft_picks` entries use:

- `roster_id` = the **ORIGINAL drafting team** (the roster whose
  end-of-season standings determined this pick slot)
- `previous_owner_id` = the **prior holder** before this transaction
  (the actual GIVER in this trade)
- `owner_id` = the new owner after this transaction (the RECEIVER)

The original spec had `roster_id` and `previous_owner_id` semantically
swapped, which meant:

- `normalize_trade` created phantom trade sides via `sides.setdefault` on
  the original drafter, even when that team wasn't in `roster_ids`
- Every `PickAsset.original_owner_user_id` was actually the prior-tx
  holder, not the original drafter
- `resolve_assets` looked up the WRONG user's draft slot, attaching
  unrelated drafted players (Bowers) to picks they had nothing to do with

**Change:** `normalize_trade` swapped to the correct semantics
(`previous_owner_id` = giver, `roster_id` = original drafter metadata).
Test fixture `transactions_trade.json` updated to use realistic Sleeper
shapes. New regression test verifies that a pick whose `roster_id` is
outside `roster_ids` does NOT add a phantom side.

### 5. Hardcoded transaction-ID blacklist

**Surfaced:** User has two known-junk Sleeper transactions in their
league history (probably canceled/erroneous trades the API still returns)
that must never surface in the report.

**Change:** New `BLACKLISTED_TRANSACTION_IDS = frozenset({...})` constant
in `engine/trade_history.py`. Filtered at fetch time (in
`_fetch_league_season_data`) before normalization or counting, with an
INFO log on each skip for auditability. Specific IDs are baked into the
code; extending the blacklist is a one-line change.
