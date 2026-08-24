# Realized Trade Value — design

- **Date:** 2026-06-11
- **Status:** Draft for review
- **Sub-project:** 1 of 2. (Sub-project 2 — "Owner Trade Value progression" — builds on this and is out of scope here; see *Out of scope*.)

## Problem

Trade Value (KTC) is the one metric that violates the app's own "while on roster"
rule. The four production metrics (`production_total`/`regular`/`playoff`/`toilet`)
are **received-only and bounded to the owner's tenure**: they count only what an
asset did *for you, while you held it*. But `net_ktc` / `snapshot_value_swing` is a
**perpetual mark-to-market swing** — it re-prices both sides of every trade at
today's KTC, forever, regardless of who currently holds the assets.

That produces a wrong story. Concretely:

> Owner A trades B (KTC ~5,000) for C (KTC ~4,800). A holds C for two strong years,
> banks the production, then drops/trades C while C is worth ~6,000. C then declines
> to ~1,500 over the next five years on someone else's roster.
>
> - **Today's `net_ktc`:** values C at 1,500 → A's swing ≈ **−500. "A lost."** Wrong.
> - A bought low, banked two years, and exited near the top. C's post-A decline is
>   not A's outcome.

KTC's natural mean-reversion over a player's career means a trade an owner clearly
*won* can later render as a *loss* purely because the asset aged out — on someone
else's roster. The decline happened off A's roster and should not touch A's grade.

## Goal

Redefine Trade Value as a **realized, received-only, tenure-bounded** metric that
obeys the same "while on roster" rule the production metrics already follow, then
point everything that reads `net_ktc` (standings, trade detail, GM Rating, summary
cards) at the new definition. The mark-to-market swing is **replaced**, not kept
alongside.

### Non-goals

- No new ingestion of Sleeper drop/waiver transactions (disposition is inferable —
  see *Algorithm*).
- No change to the production metrics, playoff-phase classification, or the
  became-grade.
- The time-series progression curve is a **separate** sub-project (out of scope).

## The model

**Each side of a trade is scored on the realized worth of the haul *it received* —
no swing, no subtraction of the given side.** A trade renders as two independent
head-to-head numbers (e.g. *"A got 6,000 · D got 4,100"*), exactly like Total /
Playoff Points already render. This unifies all five metrics under one rule and
removes Trade Value's lone "swing" special case.

Realized worth of a single received asset, by what the owning side did with it:

| Disposition | Realized value |
|---|---|
| **Still holds it** (on current roster) | **today's** KTC (you still own that future; if a keeper fades on your watch, that loss is correctly yours) |
| **Traded it away** | KTC at the **flip date** (you cashed it in for that; the deal you flipped it into is a separate, independently-graded trade — no double-count) |
| **Dropped it** | **0** (forfeited by choice; a dropped asset that pops off later is a bad GM move and *should* read as 0 here) |

**Picks** resolve through the existing lineage walk to the player(s) they became,
then each terminal player is valued by the same three rules under that owner's
tenure. A future/undrafted pick still held is valued at today's round-level pick
table (held).

### Behavioral property (why this is the right base for the curve)

An owner's Trade Value now **floats** with the players they still hold (marked to
today) and **locks in** for everything they've exited (frozen at flip date, or 0 if
dropped). The off-roster-decline bug is gone: an exited asset's later fate never
moves the original trade's grade.

## Algorithm

Disposition + relinquish-date is already encoded in `engine/lineage.py`'s
`build_trade_lineage`, at exactly the right boundary:

- A received **player** becomes either a **flip node** (carries `flipped_at`, set by
  `_first_flip` = the owner's first flip strictly after acquisition) or a **terminal
  node** with `terminal_state` ∈ {`on_roster`, `dropped`} (via `current_holders`).
- A received **pick** is followed through flips/draft until it resolves to a player
  (terminal `on_roster`/`dropped`) or stays `undrafted`.

So realized valuation is a walk over the **root received assets** of a trade that
values each at its relinquish boundary — a *shallower* walk than the became-grade
(which deliberately follows assets onward *past* the owner's exit). New logic, but
it reuses the same flip-detection (`_first_flip`) and disposition (`current_holders`)
the lineage already computes.

### Valuing at a past date

Flip-date and "today" valuations both go through the existing snapshot machinery:

- **Today:** the current `ktc_values` map already passed to the grader.
- **At a flip date:** `api/app/services/ktc_snapshot_store.py::KtcSnapshotStore.match(flip_date, cutoff)`
  returns the nearest dated KTC snapshot (with an `approx` flag and a fallback to the
  earliest snapshot for dates after the cutoff). Reuse it; do **not** invent a second
  historical-lookup path.
- Asset → number conversion reuses `engine/trade_grader.py::_ktc_value` with the
  appropriate snapshot map and the existing `fmt` / `pick_values` / tiering args.

### Proposed shape

- New engine function (in or adjacent to `engine/lineage.py`, the "extend lineage"
  approach) — e.g. `realized_received_value(resolved_trades, root_trade_id, current_holders, snapshot_provider, ...) -> dict[uid, float]` —
  returning each side's realized received total for one trade.
- The grader's per-side received total (`TradeGrade.received_ktc`, today already
  `{uid: sum(r.ktc ...)}` from `build_asset_breakdown`) becomes the **realized**
  total. `snapshot_value_swing` (the zero-sum swing) is removed from the metric path.
- Per-asset rows in `build_asset_breakdown` (`AssetLine.ktc`) are repriced to each
  asset's realized value so the trade-detail per-player table and its TOTAL reflect
  realized worth (the existing winner-highlight + `for <given>` footer are unchanged
  structurally).
- `aggregate_owner_records` rolls `net_ktc` from the realized per-side totals instead
  of the swing.

The snapshot provider must be injected from the API layer (the engine stays pure;
the store lives in `api/`). Define a small callable/protocol the grader accepts, so
`engine` does not import `api`.

## Touchpoints

| File | Change |
|---|---|
| `engine/lineage.py` | add realized-received valuation walk (reuses `_first_flip`, disposition) |
| `engine/trade_grader.py` | `received_ktc` ← realized; drop the swing from the metric; reprice `AssetLine.ktc`; `aggregate_owner_records.net_ktc` ← realized roll-up |
| `engine/regrade.py` | confirm became-grade's value lens uses realized rules consistently (it already walks terminals; align its KTC valuation) |
| `api/app/services/ktc_snapshot_store.py` | reused as the historical-price source (likely no change beyond a provider adapter) |
| `api/app/services/at_trade.py` | revisit — at-trade swing may be subsumed/retired by the realized model |
| `api/app/services/aggregations.py` | `_aggregate_owner_rows`: `net_ktc` now realized; recheck `net_ktc_at_trade` / `net_ktc_aged` (see *Open questions*) |
| `api/app/services/leaderboard.py` | `owner_pillars` `value` signal auto-picks-up via `net_ktc` (verify, no logic change) |
| `api/app/services/trade_view.py` | assembles trade detail — verify realized totals/winner render correctly |
| `api/app/models/league.py` | `StandingRow` — `net_ktc` semantics change; possibly retire `net_ktc_at_trade`/`net_ktc_aged` |
| `web/components/StandingsTable.tsx` | Trade Value column tooltip/formatting; **no longer zero-sum** |
| `web/components/HeroStatsRow.tsx` + summary cards | re-add Trade Value to the league summary (now a meaningful, non-zero total) |
| Grade derivation (see below) | letter-grade mapping must be re-derived |

## Semantics & consequences (read carefully)

1. **Not zero-sum anymore — this is intended and useful.** Today every trade's swing
   mirrors exactly, so the league sums to 0 (the reason Trade Value was omitted from
   the new summary cards). With each side frozen at different moments/dispositions,
   the sides no longer mirror and a league-wide **total/avg realized Trade Value is
   meaningful** → Trade Value goes back on the summary cards.

2. **Trade Value becomes gross acquisition, not net win/loss.** Because the given
   side is no longer subtracted, an owner's Trade Value is "realized value I brought
   in through trades," not "did I win the swap." Overpaying isn't subtracted directly;
   it surfaces as the *other* side's high received total and as your own lower
   realized return when the asset you got underperforms. This matches the existing
   received-only production model. **Confirmed desired** (received-only chosen over
   swing during design).

3. **Letter grade must be re-derived.** Today's grade maps thresholds on the
   zero-sum `net_ktc` (A ≥ 1500, … D below). Realized received totals are all-positive
   and on a different scale, so fixed thresholds break. Options for planning: a
   league-relative grade (z-score or rank over realized Trade Value), or fold the
   grade into the existing GM-Rating z-machinery. **Decision deferred to the plan.**

4. **GM Rating shifts, by design.** The `trade_impact.value` signal (weight 0.30 ×
   0.22 ≈ 0.066 of the composite; ~18 rating points per league SD) now z-scores
   realized acquisition instead of mark-to-market swing. z-scoring is
   distribution-agnostic, so the pillar math is unaffected; the *meaning* of the
   signal improves (rewards realized, tenure-bounded value).

## Data & constraints

- Daily KTC snapshots exist only from **~May 2026** (`BACKFILL_CUTOFF`). Flip-date
  valuations after that are exact; before it, `KtcSnapshotStore.match` falls back to
  the earliest snapshot and flags `approx`. Surface "approximate" where a flip
  predates the snapshot history; never present an approximate number as exact.
- "Still held" and "dropped" need **no** historical price (today's KTC / 0). Only
  **flipped** assets need a flip-date price. So the historical-data dependency is
  limited to the flip path.

## Edge cases

- **Pick flipped before the draft:** value the pick (round-level table) at the flip
  date; do not telescope to a later-drafted player.
- **Pick → drafted → still held:** today's KTC of the drafted player.
- **Pick → drafted → flipped:** flip-date KTC of the drafted player.
- **Asset received, never appears again, not on current roster:** `dropped` → 0
  (the inference that yields 0 without a drop transaction).
- **Multi-team trades:** each side valued independently on its own received haul
  (already how `rt.sides` is structured).
- **FAAB / unknown assets:** 0 (unchanged).
- **Re-acquisition** (owner trades a player away, later trades for him again): each
  trade is independent; the second acquisition starts a fresh tenure. Confirm
  `_first_flip`'s "strictly after acquisition" handles this per-trade.

## Testing

- Pure unit tests on the realized valuation walk: held / flipped / dropped player;
  each pick disposition; the multi-year example from *Problem* (assert the dropped
  case reads correctly, not the −500 mark-to-market artifact).
- Snapshot-provider seam mocked with fixed dated prices (no network).
- Regression: trade-detail per-asset rows sum to the side's realized total; winner
  highlight matches the higher realized side.
- Approx-flag path: a flip before the snapshot cutoff flags approximate.
- GM Rating: existing pillar tests still pass with realized `value` (z-score
  invariant to the redefinition).

## Out of scope (sub-project 2)

The **Owner Trade Value progression** curve — a per-owner time series of realized
Trade Value (floating on held assets, locked on exited assets) overlaid with the
monotonic Production line, reconstructable from stored daily KTC snapshots back to
~May 2026 and growing forward, surfaced on the owner detail page. Specced separately
once this lands.

## Open questions for planning

1. **Grade derivation** — league-relative (z/rank) vs. recalibrated thresholds vs.
   reuse GM z-machinery. (Consequence 3.)
2. **`net_ktc_at_trade` / `net_ktc_aged`** — does the realized model retire these
   StandingRow fields, or do they retain a distinct meaning?
3. **`at_trade.py`** — fully subsumed by the realized model, or still needed for the
   trade-detail "value at the time" context line?
4. **Cache invalidation** — realized grades change cached `ChainCacheEntry` values;
   confirm a full recompute on next refresh and whether a cache-version bump is
   warranted.
