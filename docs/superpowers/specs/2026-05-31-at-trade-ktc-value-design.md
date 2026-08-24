# At-Trade KTC Value — Design

**Date:** 2026-05-31
**Status:** Approved, ready for implementation plan
**Scope:** Add a second snapshot-lens value for each trade — its KTC value **as
of the trade date** — alongside the existing "today" value, plus the aged delta
between them. Builds on the snapshot grader and the pick-value table shipped in
the provenance-aware-pick-grading work.

## Problem

The snapshot lens ("Value Swing — KTC · Today", `net_ktc`) values every trade at
*current* KTC. That conflates two different questions: **was this a good trade
when it was made?** (market consensus at trade time) and **how has it aged?**
(value movement since). Today's-only KTC can't separate manager skill from luck.

KTC publishes only current values — there is no historical feed — so we cannot
recover what an asset was worth on a past date. The only way to get at-trade
value is to **start capturing dated KTC snapshots now** and read from them going
forward.

## Decisions (locked during brainstorming)

1. **Capture: opportunistic on refresh.** Every refresh already fetches the KTC
   table; persist it as a dated snapshot (once per calendar day). No new infra.
   Coverage is dense for active leagues; idle-day gaps are absorbed by the match
   rule below (KTC moves slowly day-to-day).
2. **Backfill: post-draft trades only.** We have one snapshot today (the first
   capture). Stamp trades dated on/after `BACKFILL_CUTOFF` (default
   **2026-05-01**, just after the NFL draft settled) with the earliest snapshot,
   tagged "approx." Earlier trades (distorted by free agency + the draft) stay
   **blank** — never faked. The offseason is one of KTC's most volatile windows
   *despite* no games being played, so pre-draft approximation would mislead.
3. **Show the aged delta**, and provide **both** a per-trade at-trade value and an
   owner-level at-trade aggregate.

## What "no historical KTC" forces

- At-trade value is a *start-collecting-now* feature: genuine for trades from the
  first capture forward; an explicit, labeled approximation for the recent
  post-draft window; blank before that.
- Every displayed at-trade number is either a real dated snapshot or tagged
  "approx." No silent fabrication.

## Architecture

A new `KtcSnapshotStore` persists/reads dated KTC tables. A new at-trade grading
pass (in the API grader) computes, per trade, a snapshot-lens swing against the
snapshot matched to that trade's date. Results flow into `TradeGrade` (per-trade)
and `OwnerTradeRecord` (aggregate), then to the UI. The existing "today" lens,
`ChainCache` blob, and 409/SSE contract are unchanged.

## Components

### 1. `KtcSnapshotStore` — *new, `api/app/services/ktc_snapshot_store.py`*

- Persists one JSON file per day: `snapshots/ktc_YYYY-MM-DD.json` under
  `TRADE_GRADER_CACHE_DIR`, holding the raw name-keyed KTC table (serialized
  `KTCValue` list, same shape `fetch_ktc_values` returns — **includes pick
  entries**, needed to rebuild the dated pick table).
- `capture(ktc_values, today)` — writes today's file **only if absent**
  (idempotent; one capture per calendar day regardless of refresh count).
- `match(trade_date, cutoff)` — the three-branch rule:
  1. **latest snapshot with date ≤ `trade_date`** → return it (genuine; absorbs
     gaps), with `approx=False`.
  2. **else if `trade_date ≥ cutoff`** → return the **earliest** snapshot,
     `approx=True` (backfill stand-in).
  3. **else** → `None` (blank).
  Returns `(name_keyed_ktc | None, snapshot_date | None, approx)`.
- `list_dates()` / internal date parsing from filenames. No TTL — snapshots are
  immutable history, kept indefinitely (small, ~one file/day).

### 2. Capture hook — *modified `api/app/services/grader_io.py`*

In `pull_supporting_data`, immediately after `ktc_values = await
fetch_ktc_values()` succeeds, call `snapshot_store.capture(ktc_values, today)`
when a store is provided. The store + `today` are threaded in from
`GraderService.run` (which owns the cache dir). KTC-unavailable → no capture
(don't persist an empty table).

### 3. Reusable KTC→player_id resolver — *refactor in `grader_io.py`*

Extract the existing name→`player_id` matching + FantasyCalc-fallback logic
(currently inline in `pull_supporting_data`) into
`resolve_ktc_to_player_id(ktc_values, raw_players) -> dict[str, KTCValue]` so the
same logic builds both the **today** table and each **dated** table. The dated
pick table reuses `build_pick_value_table(snapshot_values)`.

### 4. At-trade grading pass — *new, `api/app/services/at_trade.py`*

For a list of resolved trades + the players blob + the snapshot store:
- Group trades by `trade.traded_at.date()`; for each distinct date, `match()` the
  snapshot once and build `(dated_ktc_by_pid, dated_pick_table, approx)` (memoized
  per date).
- Per trade, compute the at-trade swing via the snapshot lens against the dated
  tables. **Picks are valued as picks** — see the nuance below.
- Emit per trade: `at_trade_value_swing: dict[uid,float] | None`,
  `at_trade_approx: bool`, `at_trade_snapshot_date: str | None`, and
  `aged_value_swing` = today_swing − at_trade_swing (per uid; only when at-trade
  is present).

**Pick nuance (key):** at trade time a traded pick had **not** been drafted (if it
had, you'd trade the player, not the pick) — so its at-trade value is the dated
round-level pick value, **never** the player it later became. The grader must
ignore the `drafted_player_id` annotation for at-trade valuation. Add an
`ignore_drafted_player: bool = False` param to `_ktc_value` / `grade_snapshot_value`
(`trade_grader.py`); the at-trade pass passes `True`. The "today" lens is
unchanged (defaults `False`). This is conceptually cleaner than the today lens,
which intentionally uses the drafted player.

### 5. Data model additions

- `TradeGrade` (`models/trade.py`): add `at_trade_value_swing: dict[str,float] |
  None = None`, `aged_value_swing: dict[str,float] | None = None`,
  `at_trade_approx: bool = False`, `at_trade_snapshot_date: str | None = None`.
- `OwnerTradeRecord`: add `net_ktc_at_trade: float = 0.0`, `net_ktc_aged: float =
  0.0`, `at_trade_trade_count: int = 0`. `aggregate_owner_records` sums at-trade
  swings **only over trades that have at-trade data**, and computes
  `net_ktc_aged` as today-minus-at-trade **over that same subset** (so the aged
  delta is an apples-to-apples comparison, not today-over-all vs at-trade-over-some).

### 6. UI — *modified `web/`*

- **Trade detail Value Swing card:** show **Today** (existing), **At Trade**, and
  **Δ aged**. Backfilled at-trade values carry an "approx" tag; blank at-trade
  renders as "—" with a short tooltip ("no KTC snapshot from before this trade").
- **Owners tab:** add **Net KTC (at trade)** and **Aged** columns next to the
  existing Net KTC, over the at-trade-having subset.

### 7. Threading

`GraderService.run` constructs the `KtcSnapshotStore` from `cache_dir`, passes it
to `pull_supporting_data` (capture) and to the at-trade pass (grade). The at-trade
results merge into the per-trade `grades` dict and the aggregate path. All gated
so a missing store / empty snapshots degrades to blank at-trade values, never an
error.

## Data flow

```
refresh -> pull_supporting_data:
   fetch KTC -> capture today's snapshot (once/day)
   resolve today ktc_by_pid (refactored helper)
grade today (existing)
at-trade pass:
   per distinct trade date -> match snapshot -> dated ktc_by_pid + pick table
   per trade -> at-trade swing (picks as picks) + aged delta
merge into grades; aggregate_owner_records adds net_ktc_at_trade / aged
write ChainCache (now also carries at-trade fields in each grade)
```

## Match-rule examples (cutoff = 2026-05-01; first capture = today, 2026-05-31)

- Trade 2026-05-03 (post-cutoff, no earlier snapshot) → earliest snapshot
  (today), **approx=True**. As daily snapshots accumulate this stays frozen on
  today's value (acceptable, labeled).
- Trade made 2026-06-10 (future) → a snapshot ≤ 2026-06-10 will exist → real,
  approx=False.
- Trade 2026-03-15 (pre-cutoff) → blank.
- Idle-gap: trade 2026-06-03 with snapshots only through 06-01 → uses 06-01
  (2 days stale, approx=False).

## Edge cases

- **KTC unavailable on a refresh** → no capture that day; existing snapshots
  untouched; today's at-trade grading for new trades falls to the nearest prior
  snapshot or blank.
- **Trade with no players, only FAAB/picks** → at-trade swing still computes
  (picks via dated table; FAAB = 0), consistent with the today lens.
- **Owner with zero at-trade-having trades** → `net_ktc_at_trade`/`aged` = 0,
  `at_trade_trade_count` = 0; UI shows "—".
- **Snapshot file corrupt/unparseable** → treated as absent for matching (logged).

## Testing

- `KtcSnapshotStore`: write/read round-trip (pick entries preserved); capture is
  once-per-day idempotent; `match()` three branches (≤-date latest, backfill
  earliest+approx, blank); corrupt file ignored.
- At-trade grading: picks valued via the **dated pick table**, not the drafted
  player (the `ignore_drafted_player` path); aged delta = today − at-trade;
  backfilled trade flagged approx; pre-cutoff trade blank.
- `resolve_ktc_to_player_id` refactor: today-lens output unchanged (regression).
- `aggregate_owner_records`: at-trade sums + aged computed over the at-trade
  subset only.
- Follow `superpowers:test-driven-development`.

## Out of scope

- Backfilling pre-`BACKFILL_CUTOFF` trades, or any use of a third-party historical
  KTC source (unreliable; explicitly rejected).
- A scheduled daily capture job (opportunistic-on-refresh chosen; can be added
  later if idle-day gaps prove material).
- Changing the today lens, the `ChainCache` blob TTL, or the 409/SSE contract.
- Per-week in-season snapshot granularity beyond one capture/day.
