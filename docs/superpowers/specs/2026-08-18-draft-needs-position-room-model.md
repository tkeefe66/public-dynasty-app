# Draft Needs — Position-Room Model

**Date:** 2026-08-18
**Status:** proposed — design only, ready to plan an implementation from
**Depends on:** `docs/superpowers/specs/2026-08-17-draft-needs-phase5-design.md` (both sections —
the original shape and the 2026-08-17 revision that moved the line onto league-scoring points)
**Scope:** the replacement-line model in `engine/draft_needs.py`, and the "Going in" panel's
column semantics on top of it. No implementation in this document.

## What this is

The 2026-08-17 revision fixed the replacement line's *value axis* — points in this league's own
scoring instead of a national ECR consensus. It did not touch the line's *depth axis* — how many
players deep the line is drawn, per position. This spec is about the depth axis: a live look at
the shipped panel found the depth measure itself is silently wrong, in a way that produces
confident, readable-looking output ("no holes") that is not true of the roster it describes.
Found this session, working through the panel with real numbers rather than trusting the column
text.

## The premise, measured

### 1. Column semantics were unreadable before any of the arithmetic was examined

Read cold, "Holes going in" mixes two unrelated sentence types with no visual distinction between
them:

- A **real hole** — `is_hole=True`, margin negative, e.g. `WR-0`, `QB-97`.
- A **"softest slot" fallback** — shown only when an owner has *zero* real holes, e.g.
  `softest RB +14`. The margin here is positive: this is not a hole, it is "no problem, but here
  is your weakest spot anyway." The only thing distinguishing it from a real hole in the rendered
  text is the word "softest."

`Drafted into` / `Started` compound this: they match at **position-label granularity**, not the
specific hole slot. One owner (`waterboyboucher`, `Example League`, 2026 draft) has exactly one
hole — a single FLEX slot occupied by a WR at margin **−0.08** (a rounding-scale non-event, not a
meaningful deficiency) — yet the panel reports `Drafted into: WR · WR · WR · WR`, `Started: 0/4`,
because every non-keeper WR pick that owner made gets credited against the one WR-labeled hole,
regardless of whether it filled the marginal slot. That reads as "drafted four WRs, none of which
ever helped," when the actual gap being described is a coin-flip-width margin.

`—` in `Drafted into`/`Started` is also overloaded: it means both "no holes existed" and "holes
existed but nothing addressed them," and the cell gives no way to tell which.

### 2. The replacement line itself is distorted by FLEX demand-borrowing — the substantive defect

`build_draft_needs` computes each position's demand `N` **empirically**: across every owner's
independently-solved best lineup, how many league-wide starting slots — direct slots *and* FLEX
slots a real position happened to win — ended up filled by that position. The line is then drawn
at the `N`th-best rostered player at that position. Flex-eligible positions can therefore have
their demand — and their line — pulled arbitrarily deep by what *other* owners chose to do with
their own FLEX slots that particular year.

Measured against the reference league (`Example League`, `league_id 9000000000000000001`, 12
dynasty owners, 2026 rookie draft, `roster_positions = QB, RB, RB, WR, WR, TE, FLEX, FLEX, K,
DEF, BN×10`; player values are 2025 season points, this league's own scoring, matching the
2026-08-17 revision):

| pos | direct-slot demand | actual engine demand | line at direct count | line at engine's actual N | gap |
|---|---|---|---|---|---|
| RB | 24 (2×12) | **34** (+10 FLEX) | #24 — TreVeyon Henderson, 158.8 pts | #34 — Bucky Irving, 119.4 pts | **39.4 pts** |
| WR | 24 (2×12) | **35** (+11 FLEX) | #24 — Deebo Samuel, 182.1 pts | #35 — DJ Moore, 147.2 pts | **34.9 pts** |
| TE | 12 (1×12) | **15** (+3 FLEX) | #12 — Dalton Schultz, 138.3 pts | #15 — Mark Andrews, 119.8 pts | **18.5 pts** |
| QB | 12 (1×12) | **12** (+0) | #12 — Baker Mayfield, 311.7 pts | same | **0** |

QB is untouched because it is not FLEX-eligible in this league — direct proof the distortion
tracks FLEX eligibility, not some general noise in the method. RB and WR carry the largest gaps
because they are the positions most often worth playing in FLEX; TE's gap is real but smaller
because TE wins FLEX far less often.

**Concrete case that surfaced this.** Owner "Amir" (`ChocGummyBear`, `user_id
900000000000000003`) starts Kenny Gainwell (193.1 pts, RB1) and Rachaad White (133.2 pts, RB2).

- Against the honest 24-deep bar (#24 = Henderson, 158.8): `133.2 − 158.8 = −25.6` — **a real
  hole.**
- Against the FLEX-inflated 34-deep bar the engine actually draws today (#34 = Irving, 119.4):
  `133.2 − 119.4 = +13.8` — **reads as no hole at all.**

The panel currently reports Amir has zero holes and surfaces `softest RB +14` — worded as
reassurance. It is masking a real, replacement-level-thin RB2. The mechanism: because *other*
owners chose to start extra RBs in their own FLEX slots this year, every RB slot leaguewide —
including owners like Amir who never used RB in FLEX at all — gets graded against a bar that has
nothing to do with their own roster shape.

## Full-league measured impact (old model vs. new model)

Computed by re-running `build_draft_needs`'s solved lineups (identical under both models — demand
only affects the line-draw pass, not who starts) against both demand definitions, for every owner
and every real-position slot instance. Reconstructed old-model demand (RB 34, WR 35, TE 15, QB 12)
matched the app's real cached values exactly, confirming the shared lineup solve is correct. The
ECR veto is a no-op in this reconstruction (`board={}`), so these margins are veto-free by
construction; cross-checked against the real cached `vetoed` flag and **no flip below has a
`vetoed=True` counterpart** — the veto would not have changed any verdict in this table.

**Replacement lines, old vs. new:**

| Position | Old demand | Old line (player, pts) | New demand | New line (player, pts) |
|---|---|---|---|---|
| QB | 12 | Baker Mayfield (311.7) | 12 | Baker Mayfield (311.7) — unchanged |
| RB | 34 | Bucky Irving (119.4) | 24 | TreVeyon Henderson (158.8) |
| WR | 35 | DJ Moore (147.2) | 24 | Deebo Samuel (182.1) |
| TE | 15 | Mark Andrews (119.8) | 12 | Dalton Schultz (138.3) |
| K | — (excluded today) | N/A | 12 | Matt Prater (55.0) |

**Hole flips (old → new disagreement), all 15, sorted by owner:**

| Owner | Slot | Pos | Player (pts) | Line old | Margin old | Hole old | Line new | Margin new | Hole new |
|---|---|---|---|---|---|---|---|---|---|
| bigegos01 | WR2 | WR | Justin Jefferson (176.1) | 147.2 | +28.9 | No | 182.1 | −6.0 | **Yes** |
| bigegos01 | FLEX1 | WR | Quentin Johnston (156.4) | 147.2 | +9.2 | No | 182.1 | −25.7 | **Yes** |
| ChocGummyBear | RB2 | RB | Rachaad White (133.2) | 119.4 | +13.8 | No | 158.8 | −25.6 | **Yes** |
| ChocGummyBear | WR2 | WR | Stefon Diggs (180.9) | 147.2 | +33.7 | No | 182.1 | −1.2 | **Yes** |
| ChocGummyBear | FLEX1 | WR | Keenan Allen (167.4) | 147.2 | +20.2 | No | 182.1 | −14.7 | **Yes** |
| CormacHatesYou | FLEX2 | WR | Rashee Rice (148.1) | 147.2 | +0.9 | No | 182.1 | −34.0 | **Yes** |
| johnago | FLEX1 | RB | Zach Charbonnet (136.5) | 119.4 | +17.1 | No | 158.8 | −22.3 | **Yes** |
| johnago | FLEX2 | RB | Bucky Irving (119.4) | 119.4 | 0.0 | No | 158.8 | −39.4 | **Yes** |
| keegs246 | FLEX1 | RB | Tony Pollard (157.1) | 119.4 | +37.7 | No | 158.8 | −1.7 | **Yes** |
| oliverc7 | RB1 | RB | Kareem Hunt (137.9) | 119.4 | +18.5 | No | 158.8 | −20.9 | **Yes** |
| oliverc7 | TE | TE | Chig Okonkwo (121.8) | 119.8 | +2.0 | No | 138.3 | −16.5 | **Yes** |
| oliverc7 | FLEX1 | WR | Romeo Doubs (164.4) | 147.2 | +17.2 | No | 182.1 | −17.7 | **Yes** |
| Parksalottafantasay | WR2 | WR | Jakobi Meyers (158.5) | 147.2 | +11.3 | No | 182.1 | −23.6 | **Yes** |
| waterboyboucher | RB2 | RB | Woody Marks (126.4) | 119.4 | +7.0 | No | 158.8 | −32.4 | **Yes** |
| waterboyboucher | FLEX1 | WR | Khalil Shakir (154.9) | 147.2 | +7.7 | No | 182.1 | −27.2 | **Yes** |

Every flip runs the same direction — not-a-hole under the old model becomes a hole under the new
one. The new model, drawing on less-diluted demand, never *rescues* a slot the old model already
called a hole; it only ever surfaces ones the old model was hiding.

**Summary.**

- Total hole flips league-wide: **15** — RB: 6, WR: 8, TE: 1, QB: 0, K: 0.
- K holes under the new model: **zero**. The line lands on the worst rostered K in the league
  (Matt Prater, 55.0), so no rostered K falls below it — 10 of 12 owners roster exactly one K and
  clear it trivially; 2 owners (`crh121`, `Bobster565`) roster none, so there is no K slot to grade
  for them at all (not a hole — nothing to compare).
- Owners who read **zero holes** under the old model and gain at least one under the new model:
  **`ChocGummyBear` only** (Amir — 0 → 3: RB2, WR2, FLEX1). This is the case that surfaced the bug
  and it is not an isolated artifact of that one owner — see the per-owner counts below.
- Per-owner hole counts, old → new, every owner whose count changed: `ChocGummyBear` 0→3,
  `CormacHatesYou` 1→2, `johnago` 1→3, `waterboyboucher` 1→3, `keegs246` 2→3,
  `Parksalottafantasay` 3→4, `bigegos01` 3→5, `oliverc7` 2→5. Unchanged: `tkeefe6689` (3→3, same
  slots), `MikeyJauquet`, `crh121`, `Bobster565` (0→0 for all three).

Two-thirds of the league (8 of 12 owners) gains at least one previously-hidden hole under the
corrected model — this is not a narrow edge case, it is the common case for this league's 2026
class.

## Decision: freeze demand at direct-slot counts, not a second "flex line"

**Considered and rejected: two parallel lines.** Compute `strict_line` (N = direct-slot count
only) alongside today's `flex_line` (N = empirical demand including FLEX overflow), and surface
both — e.g. a slot flagged a hole under the strict bar but not the flex bar. Rejected: this
relocates the § "Column semantics were unreadable" defect rather than closing it. It is more
honest than a single diluted line, but it adds a second axis a reader has to hold in their head
to know which claim a given cell is making — the same "one column, two unrelated sentence types"
failure this spec exists to remove, just moved one level down.

**Decision: demand per position becomes a fixed number — that position's own dedicated slot
count, leaguewide, full stop** (this league: RB 24, WR 24, QB 12, TE 12; see § K below for that
position's count). It is never inflated by whichever real position happens to win a FLEX slot in
a given year.

Rationale, stated the way it surfaced in review: nobody drafts "a FLEX." A Sleeper draft pick is
QB, RB, WR, TE, or K. FLEX is something a *roster* does with players it already has, after the
fact — it should not be allowed to reach back into the league-wide replacement line and redefine
what "replacement level" means for a position, diluting the bar for every other owner who never
put that position in FLEX at all.

**FLEX slots do not disappear from the panel.** A FLEX slot is still evaluated individually — but
against the fixed, honest line for whatever real position actually occupies it. A FLEX filled by
a TE is graded against the honest 12-deep TE line, not a blended "FLEX line" that corresponds to
nothing draftable. What changes is that FLEX occupancy no longer feeds back into and dilutes the
shared line every *other* owner is compared against. One honest line per position, not two
competing ones.

**Shape of the fix, for whoever implements this** (not prescribed in detail here): this changes
`build_draft_needs`'s Pass 1 demand tally (`draft_needs.py:541-557`) — today, `demand[label] =
demand.get(label, 0) + 1` for every `known`-source slot check, FLEX occupants included. The fix is
for demand to come from `_starter_slots`'s own direct-label counts (excluding FLEX-type labels),
not from tallying what the solved lineups happened to occupy. Pass 2's `_nth_best` line-draw
(`draft_needs.py:583-592`) and Pass 3's per-slot margin check stay structurally the same; they
simply read from the corrected, fixed demand.

**Precedent already in the app for "a position's bar shouldn't depend on what everyone else did
with FLEX":** the Outlook tab's Rooms chart (`RosterHealthTab.tsx::RoomsSection`) already grades
each position room against a league average independent of any FLEX bookkeeping. Noted as
supporting precedent for the framing, not a suggestion to share code — that component solves a
different problem (relative room strength, not hole detection) on a different page.

## Noted assumption: the replacement pool is league-rostered, not NFL-wide

Separate from the FLEX-demand fix above, and not a bug — but worth writing down so it isn't
mistaken for one later. `all_by_position`'s pool (`draft_needs.py:569-581`) is built by walking
`rosters.values()` — every player *someone in this specific league has rostered* — never the full
NFL player pool. So "QB replacement level" here means the `N`th-best QB among whatever this
league's 12 owners happen to be stashing, not the `N`th-best QB in the NFL.

Measured on the reference league: 34 QBs are rostered across 12 teams (roughly 2.8 per team) even
though only one QB slot exists per roster and QB isn't FLEX-eligible here — owners are hoarding
bench QBs well beyond what they can start. The `#12` line (Baker Mayfield, 311.7 pts) sits behind
11 *better* rostered QBs, including four (Josh Allen 420.6, Matthew Stafford 386.8, Drake Maye
377.7, Jared Goff 353.8) who outscore every other position's line-setter in this league by a wide
margin — evidence the pool itself is unusually stacked, not evidence of a modeling error.

This cuts both ways depending on league behavior, and that is exactly why it needs to be named
rather than assumed: a league where owners hoard backups pulls the line deeper (harder to clear,
`N`th place is a better player) than a league where owners stream and roster only starters (line
stays close to "the `N` teams' actual starters," which is close to the intuitive fantasy meaning
of replacement level). The number the panel shows is always relative to this league's own rostering
behavior, never to a universal external ranking — worth stating plainly wherever the replacement
line is documented for a reader, so nobody later "fixes" a QB line that looks unusually deep by
importing outside rankings instead of recognizing it as an artifact of this league's own hoarding.

## Decision: include K, scoped correctly

Kicker data exists and is real: Sleeper scores K normally, and the reference league carries 13
rostered kickers with real 2025 point totals. K is currently excluded wholesale —
`EXCLUDED_SLOTS = {"K", "DEF"}` (`draft_needs.py:148`) strips it out of `_starter_slots` before
any of this module's math runs, so it can never accumulate demand and can never be flagged a
hole.

**Scope check performed this session.** The panel's gate (`grader.py:1476-1479`) is:

```
capabilities.format == "dynasty"
AND capabilities.roster_continuity
AND capabilities.multiyear_history
AND at least one gradeable draft class
```

Redraft is excluded outright by the format check. Keeper is excluded for a separate, harder,
already-documented reason — `roster_asof` cannot distinguish a kept roster from the full
draft-day pool without a signature change (see the "OBVIOUS FIX DOES NOT WORK" note,
`grader.py:1440-1462`, and the phase-5 spec's own § Format gating). A first-season dynasty
startup is excluded by `multiyear_history`. Net effect: this panel *only ever* fires for the
newest draft in a **returning** dynasty league — which in practice is always the annual rookie
draft, since a startup draft happens exactly once and is excluded by the same gate that excludes
year one.

Measured: **zero kickers were drafted** in the reference league's actual 2026 rookie draft.
Rookie-draft K speculation essentially does not happen.

**Decision: add K to "Holes going in."** A thin K room is real, useful diagnostic signal — "your
K room is weak" is worth surfacing — independent of whether a rookie draft was ever going to be
the mechanism that fixes it.

**Decision: do not expect or design around K ever populating "Drafted into" / "Started" in this
panel's current scope.** Given the gate above, it will read `—` for K by construction, the same
reading an owner with zero holes gets elsewhere in the panel — a correct reading, not a display
gap. State this plainly wherever K is documented, so a future reader does not treat a permanently
empty K "Drafted into" column as evidence something is broken.

**Explicitly out of scope:** widening the panel's gate to redraft or startup boards, where K
genuinely does get drafted (typically late, speculatively). If that widening happens later, K's
"Drafted into"/"Started" columns become live in a way they structurally cannot be today, and this
reasoning would need revisiting at that time.

## Open questions / explicitly out of scope

These are real design questions surfaced by the same review, not resolved in this pass:

- **How should "Holes going in" visually distinguish a real hole from the no-holes "weakest room"
  fallback?** Today the only signal is the word "softest" inside the string. A reader should not
  need to parse prose to know which of two unrelated claims a cell is making.
- **Should `Drafted into` / `Started` match at the specific slot-instance level instead of
  position-label level?** The `waterboyboucher` case above (one marginal FLEX hole "addressed" by
  four unrelated WR picks) is a direct consequence of matching at the coarser granularity.
  Resolving this is a data-model change to `drafted_into`/`started` (currently keyed on the
  deduped position-label list, `draft_needs.py:488-500, 674-679`), not a rendering change.
- **How should the two meanings of `—` in `Drafted into`/`Started` be disambiguated** — "no holes
  existed" versus "holes existed but nothing addressed them"? These currently render identically.
- **Per-season persistence and an engine-logic invalidation signal for `draft_needs`** — both
  already named as unresolved in the phase-5 spec's § Cache — are unaffected by this spec and
  remain open on their own track.

This document does not include an implementation task breakdown or a file-by-file change list —
it exists to align on the model (frozen direct-slot demand; K in scope for holes, out of scope
for drafted-into/started) before that plan gets written.
