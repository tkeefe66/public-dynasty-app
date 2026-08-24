# Outlook tab — Assets-led redesign

**Date:** 2026-08-18
**Status:** design approved, not implemented
**Branch:** `owner-outlook-refresh`
**Revision:** rev 3 — two independent review passes against the codebase. Rev 1's stage rule
was non-monotone; rev 2 orphaned three consumers that sit upstream of the Franchise Rating.
See *Rev 1 / 2 / 3 corrections*.

## Why

The owner page's Outlook tab is a stack of ~10 cards built on a v1-era model. Three
things are wrong with it, and two are measurable rather than matters of taste.

### 1. Over half of the Trajectory axis cannot discriminate between owners

`engine/dynasty.py::trajectory_inputs` (`:336-341`) weights four inputs:

| Input | Weight | State |
|---|---|---|
| `draft_skill` | 40% | v2 **deleted this signal** from Franchise Rating because it was measured as noise (~+0.10 season-over-season correlation). Outlook leans its trajectory on it harder than on anything else. |
| `draft_capital` | 30% | Live. |
| `youth` | 15% | Live. |
| `yoy_momentum` | 15% | **Dead constant.** |

The `yoy_momentum` chain, verified end to end:

- `leaderboard.py::compute_season_ratings` (`:38-54`) returns `{}` with no branch.
- `refresh_service.py:174` **unconditionally overwrites** `entry.season_ratings` with `{}`
  before `_backfill_yoy` runs, so even a populated cached blob cannot feed it.
- `refresh_service.py::_backfill_yoy` (`:116-117`) early-returns at `len(sr) < 2`.
- `grader.py:1319` passes `yoy_rating_by_uid={}`, so the raw is `0.0` at build time too.

Therefore `yoy_score = max(0, min(100, (0+200)/4)) = 50` and the contribution is
`0.15 × 50 = 7.5` **exactly, for every owner in every league**. No CLI, migration, or
cache-reuse path reaches it. 55% of the axis is discredited or constant, and the constant
term compresses the axis for everyone equally.

### 2. It is a second model answering a question the v2 rating already answers

`compute_strength_score` reads roster-value percentile and playoff rate.
`compute_trajectory_score` reads youth, draft capital, draft skill, momentum. The v2
Assets pillar reads `roster_value_share`, `young_core_share`, `draft_capital`. Two
independent arithmetics over substantially the same evidence, on adjacent tabs of one
page, free to disagree. That is the root cause; the bad weights are a symptom of a model
nobody recalibrated.

### 3. Mean age leads the tab, and we already know better

`overall_avg_age` is printed twice (`OwnerDeepDive.tsx:238`, `RosterHealthTab.tsx:79`) and
`avg_age_by_position` drives a four-rail chart. `engine/franchise_outlook.py:56-65` already
records why mean age was pulled from the LLM facts packet: it measures bench filler rather
than the core, and produced prose calling a roster "trending downward" in the same sentence
as its "legitimate young core". It also survives inside `_describe_trajectory`, which embeds
it verbatim ("avg 27.4") into the `trajectory` string the tab renders today.

Secondary: `classify_window` returns `Competing now / Ascending / Peaking / Descending /
Rebuilding`; `.design/components/data/WindowCell.prompt.md` specifies the ordered five as
`Rebuilding / Retooling / Competing / Contending / Dynasty`.

## Decision

**Outlook becomes the Assets pillar's own page.** The independent window model is retired
rather than reweighted; the competitive-window stage is **derived from the Franchise Rating
itself**. `draft_skill` and `yoy_momentum` leave Outlook by deletion of the model that
consumed them.

Rejected alternatives: reweighting the window to four live inputs (keeps two models — the
root cause survives), and the Buy/Sell/Hold decision desk (needs a *pay-with* derivation and
a 12-month value drift that `KtcSnapshotStore` can answer for dynasty and **not** for
redraft; deferred, composes on top of this later).

## Stage derivation

`engine/gm_rating.py::rating_to_stage(rating: int) -> str`, sitting **beside
`rating_to_letter` and sharing its mechanism**: sd multiples of the composite, converted
through the measured `REFERENCE_COMPOSITE_SD` (0.6854) via `POINTS_PER_SD`.

```
_STAGE_SD = [(0.90, "Dynasty"), (0.30, "Contending"),
             (-0.30, "Competing"), (-0.90, "Retooling")]   # else "Rebuilding"
```

Three properties, all of which rev 1 lacked:

- **Monotone by construction.** The rung is a function of one scalar, so a better composite
  can never land on a lower rung. Rev 1 mixed a level test with the *relation*
  `assets_z >= results_z` and put the result on an ordered rail — which made a
  league-average team (`+0.1 / +0.2` → contending) outrank a `+1.9 / +1.8` one
  (→ competing). Relation rules cannot be monotone on a rail.
- **No new prior.** Rev 1's `+0.8` cut is gone. These bands are the letter bands' own
  units, so they inherit the one measured constant instead of introducing a second guess.
- **Correct units.** A pillar z is a weighted average of correlated signal z's, so its sd
  is well below 1.0 — `z >= 0.8` on a *pillar* is nowhere near the ~21st percentile a
  reader assumes. Banding the composite through `REFERENCE_COMPOSITE_SD` avoids the trap.

The bands align with the letter scale — the `Dynasty` edge lands **exactly** on `A−`, and
`Competing` spans **C− through B−**, containing all of the C band that is league-average by
definition. They are league-relative, matching the methodology page's existing "percentile
within your league, not an absolute scale" claim.

Populations, computed against a normal composite (verified 2026-08-18): Dynasty 18.4%,
Contending 19.8%, Competing 23.6%, Retooling 19.8%, Rebuilding 18.4% — **2.2 to 2.8 owners
of twelve per rung, symmetric.** That check is the point of stating it: `gm_rating.py`'s own
comments record the `F`-band failure where a band "could only ever fire by construction or
never", and a five-rung rail is exactly where that recurs. **The bands are honestly derived
but share the letter bands' `n=12, one league` caveat** — re-measure with the
`franchise-rating-calibration` skill whenever the tree or bands move.

### Tilt is a readout, not the rung selector

`tilt = assets_z - results_z` becomes its own signed field. It carries the reading rev 1
tried to encode in the rung ("the roster is ahead of the trophy case") and belongs in the
hero's verdict sentence, where prose handles it better than a ladder position can.

### Unrated owners have no stage

`live_ratings` returns `{}` when both signal dicts are empty (`franchise_redesign.py:111-115`),
and `rated_owners` (`:40-57`) excludes anyone without a completed season. So `window`
becomes **`str | None`**: first-season owners, new franchises, and any league whose signal
stage threw render the ladder as an absence, captioned by the `unrated_reason`
(`"first_season"` / `"new_franchise"`) that `owner_view.py:288-290` already computes.
`classify_window` always returned a label; this deliberately does not.

## The screen

Five sections, ~2.2 viewport-heights.

1. **Hero** — "Assets — 40% of your A−" kicker, a verdict line naming the pillar's point
   contribution, the five-stage ladder with the derived stage lit, and the pillar z's plus
   the tilt as its receipt.
2. **What the Assets pillar is made of** — one ledger, `Signal · Figure · Rank · vs average
   · Adds`, closed by `Assets — N signals × 40% weight`. Same diverging-bar grammar
   `OverviewTab.tsx:130,140` already draws via `ContributionRow` (`web/components/RatingBars.tsx:57`).
   `Figure` and `Rank` are **separate headed columns**: a combined "Reads" column rendering
   `9.8% · 3rd` was built and read as one unlabelled run-on.
3. **Draft needs** — the existing needs ledger, each row gaining filled/hollow depth pips
   and `held of ideal`.
4. **Your rooms vs the league** — one dot plot on a **relative** axis, zero = that
   position's league average.
5. **Draft** — the skill ordinal demoted to a meta line on the section header; the pick
   arsenal ledger is the body.

### Why the rooms axis is relative

An absolute age axis cannot carry a verdict: a 27.0 TE room is young and a 27.0 RB room is
old, so every dot has a different reference. The absolute version with unlabelled
league-average ticks was built and rejected — the ticks could not be attributed to their
dots. Zero is now each room's own league average; left-of-centre *is* the verdict. Raw age
rides beneath each dot.

Three implementation requirements:

- **Label collision is real, not cosmetic.** Rooms collide whenever two sit within ~0.3
  years. The component must walk dots left-to-right and bump an overlapping label to a
  second row with a longer stem. Hand-placing passes on one league's data and breaks on the
  next.
- **The position set is not fixed at four.** `avg_age_by_position` is built from whatever
  non-K/DEF positions the roster carries (`dynasty.py:124-131`, `_SKIP_POSITIONS = {"K","DEF"}`),
  so an FB yields a fifth key, and a position the owner holds none of yields no key at all.
  §4 plots **the owner's own keys**, intersected with the league map; `league_avg_age_by_position`
  will carry keys with no dot and those are simply not drawn. The dot count is load-bearing
  for the collision walk, so this must be explicit rather than assumed.
- **Younger reads as positive**, via a **new sign-based tone helper**. Do *not* cite
  `RosterHealthTab.ageTextTone` as precedent: it thresholds on *absolute* age
  (`>=27` neg, `<=24.5` pos, `:28-32`), which is exactly what this section argues cannot
  carry a verdict, and it is module-local anyway. The stance is consistent; the existing
  implementation is not reusable. The stance is also **not universally true** — a room can
  be too young to produce now. Accepted; the sign alone is the alternative.

## Data flow

### The stage is only available where a Franchise Rating is

This is the constraint the whole section turns on, and rev 2 missed it. `rating_to_stage`
takes a rating, so **every consumer of `window` must sit downstream of `live_ratings`.**
Three current consumers do not:

| Consumer | Why it has no rating |
|---|---|
| `franchise_outlook.py:79` (LLM facts packet) | Called from `grader.py:1893`. **Resolvable** — `entry` is constructed at `grader.py:1775`, so `live_ratings(entry)` is in scope by then. |
| `html_report.py:829` | CLI path (`cli.py:677`), Monte-Carlo pipeline, no rating anywhere. |
| `google_docs.py:1110` | Same. |

**Resolution.** The facts packet is fixed properly; the two CLI exports **drop the Dynasty
Window chip**. Inventing a second, engine-side stage derivation so the CLI can keep a chip
would recreate exactly the two-models problem this redesign exists to kill — the exports lose
a column instead. That is a real product cost and it is accepted deliberately.

### Engine

- **Rewrite `build_dynasty_outlook`** (`dynasty.py:592-690`). It is the only producer of
  `DynastyOutlook` and calls `strength_inputs` (`:659`), `trajectory_inputs` (`:661`),
  `classify_window` (`:667`) and `WindowBreakdown` (`:690`) directly. Callers:
  `outlook_build.py:113` (API) and `cli.py:677` (CLI); both must keep working.
- **The surviving `DynastyOutlook` is three fields**: `age_profile`, `draft_capital`,
  `draft_needs`. `window`, `trajectory`, `strength_score`, `trajectory_score` and
  `window_breakdown` all go. `ktc_position_rankings` still feeds `assess_draft_needs`, so the
  remaining object is coherent — but state the shape, because six parameters die with it.
- **Delete the dead-input tail.** After the deletion these are unreachable and must go
  together or the signature lies about what it needs:
  - `build_dynasty_outlook` params `projected_rank_pct`, `ktc_value_by_player`, `draft_skill`,
    `playoff_rate`, `yoy_rating_delta`, `draft_capital_pct_rank`, plus the whole
    `youth_quality_pct` block (`dynasty.py:641-657`).
  - `outlook_build.py`: `roster_value_rank_pct` (exported and unit-tested at
    `tests/test_outlook_build.py:26-27`), `rank_pct` (`:88`), the `dc_pct_rank_by_uid` block
    (`:90-105`), and params `draft_skill_by_uid` / `playoff_rate_by_uid` / `yoy_rating_by_uid` /
    `outlook_signals_by_uid`.
  - `grader.py:1300-1320`: `_draft_skill_by_uid`, `_playoff_rate_by_uid`, `yoy_rating_by_uid={}`.
- **Delete** from `dynasty.py`: `compute_strength_score`, `compute_trajectory_score`,
  `strength_inputs`, `trajectory_inputs`, `classify_window`, `_describe_trajectory`, and the
  `WindowInput` / `WindowBreakdown` dataclasses. **`outlook_build.py::window_input_dict` is
  deleted, not edited** — its only argument is a `WindowInput` and its only other caller is
  `_backfill_yoy`.
- **`DynastyOutlook.trajectory` is deleted, not migrated.** Its only producer,
  `_describe_trajectory` (`:536-581`), branches on the retired stage strings — every owner
  would fall through to the else-branch's "Young, developing roster…" — and it embeds mean age
  verbatim, the thing §3 argues against. The hero's verdict line replaces it.
- **Add** `gm_rating.py::rating_to_stage` + `_STAGE_SD`. Pure, unit-tested at every band edge.
  No new module and no engine plumbing — it takes an `int`.
- **Add per-position league mean ages, and give them a channel.**
  `build_outlooks_by_owner` returns `dict[str, DynastyOutlook]` (`outlook_build.py:61-127`),
  which has nowhere to put a league-wide map. Change its return to
  `tuple[dict[str, DynastyOutlook], dict[str, float]]`, or set the map on every
  `AgeProfile` — **pick one and say so**; rev 2 specified the value without a route and it
  reached nothing. `outlook_to_dict` (`:170-175`) must then **emit** it: today `age_profile`
  serializes exactly four fixed keys.
- **Add `held` / `ideal` to `DraftNeed`, and scope the claim.** `assess_draft_needs` has four
  branches and **only one is a depth shortfall** (`dynasty.py:504-511`). The starter-quality
  branch (`:490-499`) fires at any count, and the aging-out branch (`:512-521`) is an `elif`
  reached *only* when `current_count >= ideal_depth`. So pips on those rows would draw a
  **full room on a live need**. Emit `held`/`ideal` on every need, but the UI renders pips
  **only** for the depth branch; the others show their reason without a depth graphic.
  `outlook_to_dict:181-184` serializes `draft_needs` as exactly `{position, urgency, reason}`
  and must carry the new keys.
- **Do NOT emit a row per position** — an `urgency=""` row can surface as `"QB ()"` as the
  owner's top need in the live LLM packet (`franchise_outlook.py:70-75` →
  `HeroBand.tsx:240-242`), and it would permanently kill `FutureDraftTab.tsx:63-67`'s empty state.

### The LLM facts packet

- **`build_franchise_facts` stops reading `window` off the blob.** `franchise_outlook.py:79`
  is `window=outlook.get("window", "")` — a **stale-read path**: with no schema bump a
  pre-feature blob still carries `"Peaking"`, and this would feed a retired string into a
  packet whose `_VOCABULARY` just had `Peaking` removed. Make `window` a **parameter** and
  have `grader.py:1893` pass `rating_to_stage(...)` from `live_ratings(entry)`.
- Unrated owner → `window=""`, which `FranchiseFacts.to_dict()` already prunes (`:56-60`).
- This keeps the `_VOCABULARY` severity **low**, as rev 2 argued: `_packet_tokens`
  (`franchise_validation.py:90-105`) allows the subject's own stage off `FranchiseFacts.window`,
  so only a *different* owner's stage needs the allowlist. Dropping `window` instead would have
  inverted that and made the model fail validation for naming its own stage.

### API

- `OutlookView` (`api/app/models/owner.py:112`): **drop** `window_breakdown`, `strength_score`,
  `trajectory_score`, `trajectory`. `window` becomes `str | None`, the derived stage. **Add**
  `results_z`, `assets_z`, `tilt`, `assets_signal_ranks`;
  `age_profile.league_avg_age_by_position`; `draft_needs[].held` / `.ideal`.
- **Delete** `WindowBreakdownView` (`:104`) and `WindowInputView` (`:96`).
- `results_z` / `assets_z` / `tilt` need **no new derivation** — `PillarBreakdown.z`
  (`api/app/models/leaderboard.py:19`) is already populated from `compute_gm_ratings`
  (`gm_rating.py:257-263`) and reachable as `gm_row.pillars["assets"].z`.
- **`assets_signal_ranks` needs a route, which rev 2 did not give it.** `owner_view` receives
  only `gm_row: GMRow` (`owner_view.py:51`, injected at `routes/owner.py:37-45`), `GMRow` has
  no rank field, and `leaderboard.py:113` rebuilds pillars through `PillarBreakdown(**pd)` —
  Pydantic drops an extra key. **Add `signal_ranks: dict[str, int]` to `PillarBreakdown`**,
  populated in `franchise_redesign.py` over the same `out` dict. This is a public `/gm`
  response-shape change and must be called out as one. Read-time only — written to no
  `ChainCacheEntry` field.
- **`window` is computed at read time, never persisted.** `owner_view` calls
  `rating_to_stage(gm_row.rating)`. `owner_view.py:194` currently reads `raw_ol["window"]` and
  `raw_ol["trajectory"]` by **bracket access**, so it must stop touching both keys rather than
  be left to fall back — a new blob lacking them would `KeyError`, not degrade. And
  `outlook_view` is assembled at `:186-207` while `gm_row` is first used at `:275`, so the
  outlook block moves below the rating block (or `window` is assigned after `gm_row` resolves).
- **`StandingRow.window` must stay redraft-gated.** Deriving it from the rating silently
  re-enables the Outlook columns for redraft: `dynasty_outlooks` is gated
  (`aggregations.py:755-757`, `_outlooks_apply`) but `ratings` is **not** (`:725`,
  `_all_time_ratings` → `live_ratings`, which scores redraft under `v2_redraft`). Ungated,
  every redraft row gets a non-null `window`, `StandingsTable.tsx:163`'s `hasOutlookColumns`
  flips true, and redraft franchises are labelled "Dynasty". Gate it on `_outlooks_apply`, the
  same condition `draft_capital_value` already uses.
  Otherwise this is a one-line change in the idiom already on the adjacent line
  (`aggregations.py:794-795`), and consistency with the owner page is structural — both read
  the same `live_ratings` builder.
- `strength_score` / `trajectory_score` are deleted from `StandingRow`, and with them the
  standings `s/t` column.
- **Delete `refresh_service.py::_backfill_yoy`** (`:99-155`) and its call site.

### Persistence — no SCHEMA_VERSION bump (stays 17)

Verified: `dynasty_outlooks` appears in **none** of the `_reuse_prior` copy blocks
(`grader.py:1035-1044`, `:1073-1076`, `:1150-1157`) and is recomputed unconditionally at
`:1276-1324` — always-recomputed value layer, no change needed.

Under `.claude/skills/chain-cache-field/SKILL.md`'s cost table this is the no-bump row
(additive display data, `league_phase` precedent): removed keys are no longer read, and added
keys are display data with a read-time fallback. A pre-feature entry serves the tab with the
rooms chart and pips absent, and `auto_refresh_loop` (`main.py:48`) re-warms every cached
league ~2s after boot — minutes, not the TTL.

**The one stale-read path is `franchise_outlook.py:79`, and it is closed by making `window` a
parameter** (above) rather than by bumping. Verify this specifically: a pre-feature blob must
not be able to put `"Peaking"` into a facts packet.

### Consumers

All seven change together.

| Consumer | Location | What actually happens |
|---|---|---|
| Facts packet | `franchise_outlook.py:79` | Stale read + permanent loss of the stage. Fixed by parameterising `window`. |
| HTML export | `html_report.py:829-830` | **`AttributeError`**, not a silent chip fallback — `outlook.window` is gone. Drop the chip, its `WINDOW_CHIP_CLASSES` map (`:64-70`) **and its CSS block** (`.chip-competing`…`.chip-rebuilding`, `:385-390`). Also reads `trajectory` at `:944` (rendered `:626-628`). **Four sites in one file.** |
| Docs export | `google_docs.py:1110`, `:1115` | Same `AttributeError`; drop the chip and the colour map (`:116-119`). Also reads `trajectory` at `:1262`. |
| Methodology page | `MethodologyContent.tsx:598-604` | Publishes the retired formula to users — "40% draft skill … 15% year-over-year momentum" and all five old stage names. Rewrite; state the bands are *n=12, one league*. |
| Standings tooltips | `StandingsTable.tsx:86-92` | **Also publishes the retired formula** — the Window tooltip describes "Strength × Trajectory" and the `s/t` tooltip points at the Outlook tab "for the full breakdown". Not just a column-count edit. |
| Standings columns | `StandingsTable.tsx:62` (`FRANCHISE_COLS`) + three derived arrays + four `grid-cols-[…]` strings (`:145-155`) | Each drops one track. Written out in full because Tailwind's JIT only sees literal class names (`:151-153`). `:533` guards orphaned sort state against `OUTLOOK_COL_KEYS` — migrate or clear a persisted `sort.column === "strength_trajectory"`. |
| Validator | `franchise_validation.py:81-84` | Add `Retooling`, `Contending`; remove `Now`, `Peaking`, `Ascending`, `Descending`. Engine-side Python. Low severity **only because** the facts packet keeps `window`. |

### Frontend

- **`web/lib/types.ts` is the TS mirror of every deleted model** and rev 2 omitted it: delete
  `WindowInput` (`:372`), `WindowBreakdown` (`:380`), and the removed `OutlookView` (`:389-394`)
  and `StandingRow` (`:71-73`) fields; add the new ones.
- **`OwnerDeepDive.tsx:227-249` is the call site that breaks.** It renders `<WindowSection>`,
  and at `:234-236` a `Stat label="Window"` fallback reading `window_breakdown`/`window`.
  Rev 2 deleted the component without listing its caller. **The Hero (§1) and the Assets
  ledger (§2) live here**, in the `activeTab === "outlook"` block — they were specified in
  §The screen and assigned to no file.
- **Delete** `WindowSection.tsx` and its test.
- **Rewrite** `FutureDraftTab.tsx` as the Draft section + needs ledger, `RosterHealthTab.tsx`
  as the rooms chart. The young-core / aging-risk ledgers move under a disclosure; the
  four-rail chart and both `overall_avg_age` strips go.
- `web/lib/window.ts`: keep `WINDOW_STAGES` as the design system's five; delete
  `WINDOW_THRESHOLDS`, `WINDOW_INPUT_LABELS`, `formatWindowRaw` and `web/tests/window.test.ts`.
  Note `WindowSection.tsx:4` is its **only** importer today, so the new Hero must import it or
  the file is dead. The ladder itself already exists as
  `.design/components/data/WindowCell.jsx` with exactly these five stages — port it rather
  than redrawing.
- Position codes render in **Geist Mono**. `RosterHealthTab.tsx:98` already does;
  `FutureDraftTab.tsx:78` renders `{n.position}` in `font-display` and **changes**. Bricolage's
  `Q` carries a long baseline tail, so `QB` in the display face reads as underlined at label
  sizes.

## Costs

- **A full franchise-blurb regeneration.** `franchise_facts_hash`
  (`models/franchise_outlook.py:65-73`) is coarsened to move on a window shift, and every stage
  name changes. One full regen on the next ungated LLM pass — price it from `llm_costs.jsonl`
  (`llm-cost-analysis` skill) **before** the first prod refresh.
- **The CLI exports lose their Dynasty Window chip**, permanently, for the reason at the top of
  Data flow.
- **Test fallout across ~20 files**, two deleted whole (`web/tests/window.test.ts`,
  `web/tests/ownerdeepdive/WindowSection.test.tsx`). Beyond rev 2's list, all real:
  `api/tests/test_aggregations.py:98-100,282,287-310`, `api/tests/test_franchise_blurb_gen.py:14`,
  `tests/test_outlook_build.py:26-27,66-71`, `web/tests/FutureDraftTab.test.tsx:7`,
  `web/tests/ownerdeepdive/FutureDraftTab.test.tsx:7` (**there are two files by that name**),
  `web/tests/ownerdeepdive/RosterHealthTab.test.tsx:7`.

## Testing

**Pure engine:**

- `rating_to_stage` at **every band edge, from both sides** — `1747`/`1748`, `1581`/`1582`,
  `1417`/`1418`, `1251`/`1252`. Eight assertions, not four.
- Banker's rounding: every edge is an exact `.5`; `round(82.5) == 82`, not 83. A naive
  `int(x + 0.5)` gives 83 / −82 and breaks symmetry.
- Monotonicity: sweeping the rating range, `rating + 1` never yields a lower rung.
- League mean ages: a two-owner fixture where per-position means differ, proving the value is
  the *league's*.
- `assess_draft_needs`: `held`/`ideal` correct; **no row for a position without a need**
  (the `"QB ()"` regression guard); and pips suppressed on the two non-depth branches.

**The risky changes — rev 2 tested none of these:**

- **Redraft `window` stays `None`** on `StandingRow`, with a fixture whose `season_records` are
  **populated**. `api/tests/test_capabilities_api.py:124-131` asserts this today but passes for
  the wrong reason — its fixture has empty `season_records`, so `rated_owners` returns `[]` and
  `live_ratings` returns `{}`. Fix the fixture or the test proves nothing.
- **A pre-feature blob cannot leak a retired stage into the facts packet** (the one stale-read
  path).
- **`owner_view` block ordering**: `gm_row` resolves before `window` is assigned. A `None` or
  `NameError` here is the subtle failure the spec itself flags.
- `assets_signal_ranks` reaches the response; `tilt` carries the right sign.
- An unrated owner renders an absence on **both** the owner page and standings.

Per `mutation-first-tests`, each of the above asserts an ordering, a boundary, or a filter —
**prove each bites** by mutating the implementation out before trusting green (set
`PYTHONPYCACHEPREFIX`).

**Cache — an adapted pair**, not the standard quartet, because there is no bump and no new
persisted computation:

1. Round-trip the two new `dynasty_outlooks` keys (`tests.helpers.minimal_chain_cache_entry`).
2. A pre-feature blob serves the tab with the rooms chart and pips absent, no exception —
   **and** its stale `window`/`trajectory` keys reach nothing.

**Frontend:** `furniture-rules.test.ts` must stay green (`adhoc-size` exists at `:216`;
`UNSCOPED` is `[]` at `:145`), but it carries **no** rule for label collision or axis
correctness, so green is not evidence the chart is right. Add unit tests for the collision walk
(two rooms 0.1 years apart) and a five-position roster.

## Out of scope

- Buy / Sell / Hold and its `pay-with` + value-drift derivations.
- Redraft Outlook of any kind — no Assets pillar, so `owner_view.py:216-218` keeps setting
  `outlook_view = None`. Keeper *does* get one: `gm_rating.py:113-116` drops `young_core_share`
  and renormalises `0.45/0.20` over `0.65`, so its Assets ledger has two rows.
- Restoring a window reading to the CLI exports.
- Per-season Outlook history — `season_ratings` is `{}` under v2.
- Re-measuring `REFERENCE_COMPOSITE_SD`. It **was** recalibrated to 0.6854 on 2026-08-17
  (`gm_rating.py:126-143`); the live caveat is `n=12, one league`.

## Rev 1 corrections

Recorded so the reasoning is not re-litigated:

1. **Stage rule replaced.** Rev 1's five z-pair rules were non-disjoint and non-monotone;
   `+0.8` was applied to a pillar z whose sd is well under 1.0.
2. **Compute location resolved**, and the SCHEMA_VERSION bump dropped with it.
3. **`build_dynasty_outlook` added** to the rewrite list — rev 1's delete list left it
   referencing dead symbols, making the Engine section unimplementable.
4. **`trajectory` addressed** — rev 1 never mentioned the field.
5. **Row-per-position dropped** (LLM packet corruption).
6. **Four consumers added**: `html_report`, `google_docs`, `MethodologyContent`, and the
   `franchise_validation` severity corrected + relocated to Engine.
7. **`REFERENCE_COMPOSITE_SD` claim corrected** here and in `CLAUDE.md`.
8. **`ageTextTone` precedent withdrawn**; position set, `Rank` field, unrated-owner case,
   LLM regen cost, and test fallout all specified.

## Rev 2 corrections (self-verified 2026-08-18)

Rev 2's own three judgment calls were checked directly rather than re-reviewed:

- **Stage bands verified populated** (2.2–2.8 owners of 12 per rung) and the letter
  alignment made exact. Pass.
- **`StandingRow.window` verified derivable and provably consistent** with the owner page.
  Pass, and simpler than rev 2 assumed.
- **Two `trajectory` consumers were missing** from the consumer table
  (`google_docs.py:1262`, `html_report.py:943`). Rev 2 repeated rev 1's mistake in a
  narrower form: it listed each output file once, for its stage-string map, and did not
  keep looking within the same file for a second read of the outlook. Fixed above.

## Rev 3 corrections (second review, 2026-08-18)

A review of rev 2's implementation sections found **seven** hard errors. The governing one:

1. **`rating_to_stage` orphaned three consumers upstream of the rating.** The facts packet is
   fixed by parameterising `window`; the two CLI exports lose the chip. Rev 2 asserted "both
   must keep working" without specifying how, and mis-ranked their breakage as cosmetic when
   it is an `AttributeError`.
2. **`franchise_outlook.py:79` was a live stale-read path**, falsifying rev 2's claim that no
   stale value could survive the no-bump decision — and inverting its downgrade of the
   `_VOCABULARY` severity.
3. **Redraft regression**: deriving `StandingRow.window` from the ungated `ratings` re-enables
   the Outlook columns for redraft. The existing guard passes for the wrong reason.
4. **`league_avg_age_by_position` and `held`/`ideal` had no route into the blob**;
   `assets_signal_ranks` had no route to `owner_view` (Pydantic drops the extra key).
5. **`web/lib/types.ts` and `OwnerDeepDive.tsx` were on no list**, the latter being the call
   site of the component rev 2 deletes — and the home of two screen sections assigned to no file.
6. **The dead-input tail was unenumerated**, and `window_input_dict` must be deleted, not edited.
7. **`held of ideal` was scoped wrong** — only one of `assess_draft_needs`'s four branches is a
   depth shortfall, so pips would draw a full room on a live need.

Judgment calls taken: `StandingsTable`'s tooltips also publish the retired formula;
`html_report.py` touches the stage at four sites, not two; the test-fallout list was a third
short; the testing section covered the three lowest-risk additions and none of the risky changes.
