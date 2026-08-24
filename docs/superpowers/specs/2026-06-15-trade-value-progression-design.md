# Trade Value Progression Curve — Design Spec

**Date:** 2026-06-15
**Sub-project:** #2 of the Trade Value roadmap (follows #1 Realized Trade Value, already shipped)
**Status:** Design approved, ready for implementation plan

## Goal

Show, over time, whether a trade *panned out* — for a single trade and for an owner's whole trade history. The reader is a non-math fantasy manager: the display must be plain signed numbers (+/−) with up/down arrows and a one-sentence plain-English verdict. **No index, no "100", no z-scores in the UI.**

Built on the same realized received-only Trade Value model as #1: each received asset is valued by its real tenure (held → floats with today's market; flipped → locks at flip-date value; dropped → falls to 0 on the drop date). This sub-project adds the **time dimension** — value at each historical snapshot date, not just a single "now" — and a **given-side counterfactual** so "I sold high" is visible.

## Two views, two baselines

Approved shape **C**: an owner-aggregate curve AND a per-trade view.

### Per-trade (on the trade detail page)
- Baseline = the trade completion date.
- Two lines: **what you got** (the received haul) and **what you gave up** (the given haul).
- The gave-up line keeps being priced *as if you'd held it* — that's the counterfactual that reveals "sold high." If the player you traded away declined, that's **good for you** and the verdict says so.
- Readout: two signed numbers with arrows (▲ green / ▼ red) + a verdict card.

### Owner-aggregate (on the owner Overview tab)
- Baseline = the first stored snapshot date (~Jun 2026, "since we started tracking").
- One **Trade Value** line summing every asset the owner ever received across all trades, plus a parallel **Production** line (points produced).
- Value and Production are different units, so they do NOT share a raw axis — twin readouts (signed change each) + a single trend verdict, not an overlaid dual-axis chart.

## The one engine primitive: `value_series`

A single new function powers both views. It reuses `make_price_providers` from #1 (`api/app/services/realized_value.py`) — no new pricing logic.

```
value_series(asset, snapshot_dates, price_fn) -> list[(date, value)]
```

Per asset, evaluated at each stored snapshot date `d`:
- **held** (still on the owner's roster) → priced at `d` (floats with the market).
- **flipped** (traded away on `flip_date`) → priced at `d` for `d <= flip_date`, then **locked** at the flip-date price for all later `d`.
- **dropped** (waived/released on `drop_date`) → priced at `d` for `d < drop_date`, then **0** for all `d >= drop_date` (a cliff).

Both cards are sums of these series over different asset sets:
- **Per-trade** → sum the received haul into one series; sum the given haul into a second series (given assets priced as if still held — the counterfactual).
- **Owner-aggregate** → sum every received asset across all trades into one Trade Value series; the Production line is the existing received-only production rolled per snapshot date.

### Pre-snapshot honesty
For any asset whose relevant dates precede the first snapshot, the series is flat at the first-snapshot value until that snapshot, then moves. There is no backfill before ~Jun 2026.

## Drop-timestamp ingestion

Drop dates come from the Sleeper transaction stream already pulled for trade-finding — no new API calls.

- Add a pass in the transaction/trade-history builder that scans `type: "drop"` transactions (and the drop leg of waiver/free-agent moves) and records `{player_id, dropped_at, owner}` per owner-tenure.
- `value_series` reads this to place the dropped cliff at the real `drop_date` instead of assuming 0-from-trade or held-to-today.

## Verdict classification (plain English, no math shown)

Computed from the **change** between the baseline value and the latest value, per side. A side reads as **flat** when `|Δ| < 5%` of its own baseline (kills noise on tiny moves); only beyond that does it read up or down.

### Per-trade — compare received-Δ vs given-Δ

| received | given (as-if-held) | verdict |
|---|---|---|
| up | down | **"Great trade."** What you got rose; the player you gave up cooled off. |
| up | up (less than received) | **"Good trade."** Both rose, but yours rose more. |
| up | up (more than received) | **"Mixed, they got the better of it."** |
| down | down | **"Trash."** Both cooled off. |
| down | up | **"Brutal."** What you got cooled; the player you gave up took off. |
| flat | flat | **"Boring."** Neither side has moved much yet. |

(Flat on exactly one side collapses to the nearest row by the non-flat side's direction, e.g. received up + given flat → "Good trade.")

### Owner-aggregate — single trend on the received-value line vs baseline

- **"Trending up."** / **"Flat."** / **"Down."** on the Trade Value line.
- A confirming second sentence from the Production line ("…and scoring more than when tracking began.").

### Color rule
Color is literal on the number — green ▲ for up, red ▼ for down — but the **verdict sentence always carries the meaning**. So a red ▼ on the gave-up side, which is *good for you*, is never ambiguous because the sentence states the outcome.

## File structure

| Layer | File | Change |
|---|---|---|
| Engine | `engine/value_series.py` *(new)* | the `value_series` primitive |
| Engine | trade-history / transaction builder | drop-timestamp ingestion pass |
| Engine | verdict classifier (`engine/value_series.py` or sibling) | pure per-trade + aggregate verdict functions |
| Backend | `ChainCacheEntry` (`api/app/services/chain_cache.py`) | new `field(default_factory=...)`: per-trade series, per-owner aggregate series, verdicts, snapshot dates used. **No SCHEMA_VERSION bump** — follows the `became_grades` / `drafted_picks` precedent |
| Backend | refresh path (`refresh_service.py` + signal builders) | compute series incrementally during refresh; store the snapshot dates used on the entry |
| Backend | API models (`api/app/models/`) | series + verdict on the trade-detail response and the owner response |
| Web | `web/components/TradeValueProgress.tsx` *(new)* | per-trade got-vs-gave card, inline SVG (follows the `TradeValueSpark` precedent in `OverviewTab.tsx:30`), placed on the trade detail page near `TradeStatTable` |
| Web | owner Overview tab (`web/components/ownerdeepdive/OverviewTab.tsx`) | aggregate card: Trade Value + Production readouts + trend verdict |

No chart library is introduced — all charts are inline SVG, consistent with the existing codebase.

## Testing

- **Engine `value_series` unit tests:** held-floats-with-market; flipped-locks-at-flip-date; dropped-cliffs-to-zero-on-drop-date; pre-snapshot case (flat until first snapshot, then moves).
- **Verdict classifier unit tests:** every row of the per-trade table, the 5% flat-threshold boundary, single-side-flat collapse, and the aggregate up/flat/down trend.
- **Drop-ingestion test:** a `drop` transaction produces the correct `{player_id, dropped_at}`; the waiver-leg drop is captured too.
- **Web render tests:** one per card (per-trade got-vs-gave, owner aggregate), asserting signed numbers, arrow direction, and verdict sentence render; assert no "KTC" string leaks (it's "Trade Value" / "Value").

## Honesty limits (surfaced in plain words in the UI)

1. **No pre-2026 backfill.** Lines begin at the first stored snapshot (~Jun 2026). The aggregate baseline is labeled "since we started tracking."
2. **Trades made before the first snapshot** read flat until that snapshot, then move. Trades from launch forward get the full arc.
3. *(resolved)* **Dropped-asset timing** is now exact via the drop-timestamp ingestion above (previously the weakest point).

## V2 / Backlog (explicitly out of scope for v1)

- **Injury acknowledgement.** A value cliff/decline can be injury-driven rather than GM skill or market timing, so the "sold high / rough / great trade" verdict can misread it (a player you gave away who cratered from a season-ending injury isn't really a genius "sold high"). V2 adds an injury-context layer: annotate the value-series points (or the verdict sentence) where a decline coincides with a known injury window, so the read is "value fell, but it was an injury." Injury-window data source TBD (Sleeper player status, an injury feed, or news). Pairs with the asset value career-arc work.
- **Free-agent pickup value.** Credit value created off the waiver wire (assets acquired for nothing that became valuable), reusing this same value-series substrate and the drop-timestamp ingestion. Deferred — tracked separately.
