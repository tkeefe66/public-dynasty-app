# Asset Journey (A-frontend, phase 2) — Design

**Date:** 2026-06-09
**Status:** Approved (brainstorm, prototyped + signed off) → ready for implementation plan
**Builds on:** the per-player stat tables (`TradeStatTable`, already shipped on this branch).

## Context

The per-player stat tables answered "what did each player do." But the trade page still
split one asset's story across three sections: the direct stat table (interim production),
"Where it went" (the flip date), and "What it became" (terminal players' stats) — and never
showed **who** a flipped asset was traded to. The user wants one coherent **asset journey**:
for each received asset, *acquired → what it did for you → (if flipped) traded to whom,
when → what it became* — with the flip **linked to that trade**.

A static prototype was built and signed off. This spec turns it real.

## Decisions (brainstormed + prototyped)

1. **Inline-expand, direct-primary.** The direct stat table is the spine. Each row's
   headline is the *received* asset's own line (KTC + interim production). A **flipped**
   asset gets a `▾` that expands to its journey; **kept** assets show a tag; the TOTAL row
   is the direct received total.
2. **Flipped row expansion shows:** `traded to <counterparty> · <date> → became`, then the
   terminal players as stat sub-rows, capped by a `became` subtotal. **The "traded to
   <counterparty>" is a link to that flip trade's detail page.**
3. **Kept asset:** an `on roster` / `dropped` tag, no expansion. **Pick:** expands to what
   it became if resolved/flipped, else a `not drafted yet` tag.
4. **Absorb & remove** the separate "Where it went" (`TradeLineage`) and "What it became"
   (`TradeBecame`) sections from the trade page — the journey table replaces both.
5. Side-level "your haul is now worth X" became total is dropped (lives as per-asset
   `became` subtotals); a side-level summary line can be added later if missed.

## Data model

Extend the per-asset breakdown (`AssetLine`) into a journey-aware shape:

```python
@dataclass
class AssetFlip:
    to_owner: str          # counterparty owner display name ("BillyBob")
    trade_id: str          # the flip trade's transaction_id  (for the link)
    league_id: str         # the flip trade's league_id        (for the link URL)
    date: str              # YYYY-MM-DD
    became: list[AssetLine]  # terminal leaves, each with its own KTC + production line

@dataclass
class AssetLine:
    # ... existing: label, kind, player_id, ktc, production_total/regular/playoff/toilet
    terminal_state: str | None = None   # "on_roster" | "dropped" | "undrafted" | None
    flip: AssetFlip | None = None        # present iff this received asset was flipped
```

Each received asset is therefore self-describing: it carries its own interim line, plus
EITHER a `terminal_state` tag (kept/dropped/undrafted) OR a `flip` (with link + became
leaves). `became` subtotals are summed in the UI from `flip.became`.

## Components & changes

### Engine
- The lineage walk (`engine/lineage.py`) already resolves each root received asset to its
  first flip and terminal leaves. Surface, per root asset: the flip trade's
  `transaction_id` + `league_id` + date + **counterparty owner** (the other side of that
  flip trade — new; the walk knows the flip trade, just doesn't expose its other side).
- Enrich `build_asset_breakdown` (`engine/trade_grader.py`) so each received `AssetLine`
  carries `terminal_state` (for kept/pick assets) and `flip` (for flipped assets). The
  `flip.became` leaves reuse the per-terminal-player stat computation already added to the
  became grade (`_points_while_owned` per leaf, KTC per leaf), grouped **per root asset**
  (today the became grade aggregates per side — group it by originating root instead).
- Counterparty owner name resolves via the existing roster→user / owner display maps.

### Cache
- Bump `SCHEMA_VERSION` 4 → 5 (grade payload gains `flip`/`terminal_state`). Re-grade on
  read; cold-start handles it.

### API (`api/app/models/trade.py`, `trade_view.py`)
- Add the `AssetFlip` Pydantic model; add `terminal_state` + `flip` to the `AssetLine`
  model. Map them through in `trade_view`. (Became's `breakdown` stays for any other
  consumer, but the trade page stops using the `BecameMetrics` section.)

### Frontend
- `web/lib/types.ts`: add `AssetFlip` + `terminal_state`/`flip` on `AssetLine`.
- `web/components/TradeStatTable.tsx`: render a row's expansion when `flip` is present —
  a native `<details>` whose summary is the asset row and whose body is:
  - a line `traded to <Link href={/league/{flip.league_id}/trade/{flip.trade_id}}>{to_owner}</Link> · <date> → became`,
  - the `flip.became` leaves as stat sub-rows,
  - a `became` subtotal row (sum of leaves).
  For `terminal_state`, render a compact tag (`on roster` `text-pos`, `dropped`/`not drafted
  yet` `text-dim`) — compact/fixed so it doesn't wrap next to long names (prototype showed
  the wrap; fix with a fixed-width or below-name placement).
- `web/app/league/[id]/trade/[tid]/page.tsx`: remove `<TradeLineage>` and `<TradeBecame>`
  (absorbed). The journey table per side now tells the full story.
- Mobile: the flipped row's `<details>` expands to the journey (the existing mobile
  collapse pattern already uses `<details>`); the became leaves render compactly.

### Removal
- `TradeLineage.tsx` and `TradeBecame.tsx` are no longer used by the trade page. Keep the
  files only if another route uses them (grep); otherwise delete with their tests.

## Testing

- **Engine:** a flipped received asset's `AssetLine.flip` carries the right counterparty +
  flip trade id + became leaves whose stats match the became grade; a kept asset carries
  `terminal_state="on_roster"` and no flip; a pick carries `undrafted` or a flip.
  (`tests/test_trade_grader.py`, `tests/test_lineage.py`/`test_regrade.py`).
- **API:** trade detail response carries `flip` (with `trade_id`/`league_id`/`to_owner`)
  and `terminal_state` per breakdown row (`api/tests/test_trade.py`).
- **Web:** `TradeStatTable` renders the expansion with a working link to the flip trade,
  shows the `became` subtotal, renders the kept/pick tags, and the trade page no longer
  renders the removed sections. Run all three suites + `tsc`.

## Open questions / iterate-live

- Tag placement to avoid wrapping (live mockup).
- Whether the expansion is open-by-default for single-flip hauls or always collapsed.
- Whether to keep a small side-level "became total" summary line.

## Out of scope

Sub-project B (outcomes-dominant GM Rating + toilet sign). The "cumulative realized
production" idea (interim + became summed) stays out — became remains end-state.
