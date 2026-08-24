# Draft board redesign — design

**Date:** 2026-08-17
**Status:** approved
**Branch:** `new-draft-board`

## Problem

`/league/{id}/draft/{season}` is effectively orphaned: nothing in either nav points at it, and
the only link is the dashboard's draft-window lead, which appears for a few weeks a year.

When it is reached, it says almost nothing. The Owners panel shows **Total Points** and two
columns that are structurally blank on every dynasty season — **ADP +/-** and **Coverage**.
Past classes with full production history render as a single figure per owner.

The blank columns are not a bug. `grader.py` skips the ADP block for any class whose
`DraftClass.axis != "production"`, and `draft_class.py` assigns `axis = "blend"` to dynasty. The
comment gives the reason: Sleeper's `adp_rookie` is unpopulated, and the overall-NFL ADP that
*is* published would grade a 1.01 rookie against ~30th overall and print a 29-pick reach. The
gate is correct; the screen showing two permanently-dead columns is not.

Three things follow. There is no external baseline for a dynasty rookie class. The five-metric
production data already computed per pick is discarded at the view layer. And ranking owners by
Total Points rewards drafting early rather than drafting well.

## What this is, stated plainly

A rebuild of the draft board around one question — **what did this draft actually return** —
plus the first external baseline dynasty rookie classes have ever had. Most of the data already
exists in `build_drafted_pick_results` and is thrown away before render. The genuinely new work
is the rookie consensus baseline and the cohort-measured pick verdict.

## Decisions

| Question | Decision |
|---|---|
| Rookie baseline | **FantasyPros dynasty rookie ECR** (`ecr_type = "drk"`), dated on-or-before each draft |
| Baseline delivery | **Commit the history** (74KB gz), capture forward from the 1MB weekly CSV |
| ADP / Coverage columns | **Removed** for dynasty; ADP retained where it populates (redraft/keeper) |
| Owner sort | **Points Above Round** — pick total minus its class-round average, on **Total Points** |
| Pick verdict | **Hit / Average / Bust** vs the 25th/75th percentile of its ECR cohort |
| Verdict gating | **Owner-gated on both sides** — `N = seasons held`, matched to the cohort's N |
| Position adjustment | **Out.** Dynasty rookie ECR already prices position in |
| Franchise Rating | **ECR never feeds it.** The league-native peer delta stays the only baseline that does |
| `SCHEMA_VERSION` | **No bump.** Additive display fields, `league_phase` precedent |
| Scope | League board + owner Draft tab + nav entry |

## Baseline: the rookie consensus board

### Source

DynastyProcess mirrors FantasyPros ECR with a `scrape_date`, weekly, back to 2020. `drk` is the
**dynasty rookie** board. All three of this league's rookie drafts resolve within 0–5 days:

| Draft | Board | Gap | Ranked | Picks matched |
|---|---|---|---|---|
| 2024-05-12 | 2024-05-10 | 2d | 144 | 36/36 |
| 2025-05-16 | 2025-05-16 | 0d | 127 | 36/36 |
| 2026-05-06 | 2026-05-01 | 5d | 144 | 36/36 |

Verified with negative controls: a veteran (Mahomes) and a wrong-year rookie (Bijan) both miss
the 2025 board, and 200 random crosswalk ids hit 10 times. The board is year-specific, not a
catch-all.

This is strictly better than the existing ADP machinery, which works **going forward only**.
FantasyCalc and KTC publish no dated history — that is why `AdpSnapshotStore` and
`KtcSnapshotStore` exist. This source backfills.

### The mirror trap — do not use the `.csv.gz`

`files/db_fpecr.csv.gz` is **104,685,532 bytes**, just over GitHub's 100MB limit. The automated
weekly scrape can no longer commit it, so it is **frozen at 2025-08-08** while still serving a
clean gunzip of 25,819 well-formed rows. Reading it silently costs the entire 2026 class.

`files/db_fpecr.parquet` is 37MB and still committed weekly (current 2026-08-14). **It is the
source of record.** The same trap applies to nflverse below.

### Delivery

- **`src/sleeper_dynasty/data/rookie_ecr.json.gz`** — committed. 309 boards, 29,082 entries,
  2020-10-17 → 2026-08-14, **74KB gzipped**. Historical boards are immutable; a committed file
  also survives a cache-volume wipe, which the snapshot stores do not. Needs a `pyproject.toml`
  package-data entry to survive the wheel build.
- **`api/app/services/rookie_board_store.py`** — going forward, on the `AdpSnapshotStore`
  pattern. Captures from `db_fpecr_latest.csv` (1MB plain CSV, weekly, **no parquet reader at
  runtime**), pinned write-once per `draft_id`. Resolution merges committed history and captured
  dailies into **one timeline**, so there is no seam between backfilled and live.
- **`scripts/extract_rookie_boards.py`** — kept and re-runnable. Its docstring must state that
  the committed file has an end date and that a fresh install deployed long after generation has
  a gap until its first capture, closed by re-running the script.

### Engine

`engine/rookie_board.py`, pure, mirroring `draft_baselines.py`:

- `parse_boards(rows) -> {date: {sleeper_id: ecr}}`
- `resolve_board(dates, drafted_on)` — nearest board **on or before**, never after
- `board_delta(pick_no, ecr) -> pick_no - ecr`; `None` when unranked

### Crosswalk

`fantasypros_id → sleeper_id` from `db_playerids.csv`, which `api/yahoo_ids.py` already fetches
and parses for `yahoo_id → sleeper_id`. Lift its fetch/parse into a shared loader with two typed
accessors rather than pulling the same 2.6MB CSV twice. R's literal `"NA"` must be filtered on
both columns or it becomes a catch-all key. An unmapped player is **dropped, never zero-ranked**.

### Grader wiring

Replace the `cls.axis != "production"` gate with a fork: `production` → Sleeper ADP as today;
dynasty rookie classes → rookie ECR. Pick rows gain `baseline`, `baseline_delta`,
`baseline_source` (`"sleeper_adp" | "rookie_ecr"`). **`adp`/`adp_delta` keep their exact current
meaning** — redefining them is a shape change and would force a `SCHEMA_VERSION` bump.

## Metrics

### What counts as a played week

`grader_io.py::_assemble_played_matchups` emits a roster-week only when Sleeper
returns it as **exactly two paired entries with at least one non-zero score**.
Byes, eliminated rosters and unplayed weeks are dropped — in this league's 2025
season, week 15 (4 roster-weeks), week 17 (4) and week 18 (all 12).

Every production figure in this design is computed over that filtered set. An
independent reconstruction that reads raw Sleeper matchups instead lands about
**6% high** across most owners; reproducing the pairing filter reconciles it to
12/12 exact. The app is correct.

This is also the direct cause of the Started % trap below: those dropped weeks
are why a phase-summed numerator cannot equal a bench-inclusive denominator.

### The Started % trap

`(regular + playoff + toilet) / total` **undercounts**. `playoff_phase.py`'s own docstring:
"anything absent is a dropped week (bye, winners placement game)". A bye or a 3rd/5th-place game
belongs to no phase, so a top seed who started a rookie through a bye loses those points from the
numerator. The better the team, the more the metric lies.

Fix: add a `"started"` phase to `started_points_while_on_roster` — `started_only=True`, no phase
filter. **Start % = `production_started / production_total`**, exact by construction. `None` when
`production_total == 0`; a pick that never scored has no ratio, and 0/0 rendered as 0% reads as a
verdict.

**Consequence:** Regular + Playoff + Toilet ≤ Started, the gap being bye and placement weeks.
Those three must never be presented as summing to anything. They are a breakdown of *where*
started points landed, not addends.

### Points Above Round

Each pick's production minus the **class-round average**, summed per owner. Computed on **Total
Points**.

Round-average rather than a per-slot curve: with 36 picks there is one observation per slot, so
"average at that slot" is that pick itself and every delta collapses to zero. Rounds give 12
observations. It is also the existing pattern — `build_drafted_pick_results` already groups
`avg_slot_value` on `(draft_season, round)`.

PAR is **zero-sum within a class**, which is the property that makes it fair: it rewards drafting
well from a bad slot instead of rewarding whoever picked first.

On Total rather than Started points: a rookie's year-one usage is mostly roster construction, and
`engine/skill_signals.py::lineup_skill_signals` already grades lineup decisions separately.
Start % sits adjacent so a bench hoard stays visible.

### Verdict — Hit / Average / Bust

Measured against what players ranked in the same ECR band **actually scored**, scored under the
league's own settings. 389 rookie seasons across four classes:

| ECR | n | Bust below | Median | Hit above |
|---|---|---|---|---|
| 1–4 | 12 | 176.6 | 207.1 | 273.6 |
| 5–8 | 17 | 94.0 | 202.5 | 245.0 |
| 9–12 | 15 | 103.5 | 151.3 | 194.4 |
| 13–18 | 21 | 54.8 | 93.5 | 143.1 |
| 19–24 | 29 | 9.6 | 61.5 | 126.0 |
| 25–36 | 37 | 14.7 | 53.1 | 116.1 |
| 37–60 | 114 | 1.7 | 15.6 | 48.4 |
| 61+ | 144 | 0.0 | 0.0 | 5.6 |

Above the cohort's p75 is a **Hit**; below p25 a **Bust**; between, **Average**. Nothing is
invented, and it fixes the round-3 floor problem — PAR is bounded below by the round average, so
a 3rd-rounder could never bust under a fixed cut, while cohort percentiles let him.

**Band edges must be continuous.** ECR is fractional (8.7, 12.5, 18.2). Integer bands with gaps
dumped 32 of 389 players into the bottom cohort and manufactured false hits. Bind as
`ecr <= edge`, first match wins.

**Scoring must come from raw components, not nflverse's precomputed `fantasy_points_ppr`.** That
column uses 4-point pass TDs; this league uses 6. The mismatch inflated every QB against a cheap
bar and moved the ECR 9–12 hit bar from 166.5 to 194.4.

#### The window

**Owner-gated on both sides.** `N = seasons the owner held the player` (a season counts if held
at least one week), matched to the cohort's cumulative-through-N curve. A pick traded after year
one is judged against N=1. Gating the actual without gating the window would brand every
traded-away player a bust as its cohort kept accruing.

Cumulative cohorts build cleanly — **33 of 40 `(band, N)` cells have n≥8, coverage through N=5**:

| ECR | N=1 | N=2 | N=3 | N=4 |
|---|---|---|---|---|
| 1–4 | 207 (12) | 405 (12) | 724 (9) | 850 (6) |
| 9–12 | 151 (17) | 288 (17) | 378 (11) | 457 (6) |
| 25–36 | 47 (38) | 112 (38) | 177 (26) | 256 (19) |
| 61+ | 0 (139) | 1 (139) | 4 (83) | 4 (50) |

#### Rules

- **Thin cells fall back, never guess.** Below n=8, fall back **exactly one step** to N−1; if
  that cell is also missing, **no verdict** — the walk does not continue further down. The
  comparison is an owner-gated cumulative total over N seasons against a cohort's cumulative
  total over the same N; falling back k steps compares an N-season total against an (N−k)-season
  bar, which inflates the pick, and the inflation grows with k. At k=1 it is modest and is often
  the only alternative to no verdict at all. At k=8 — a pick held nine seasons judged against a
  rookie-year bar — it makes almost anything a Hit. Bounding the walk to one step keeps the bias
  small instead of unbounded.
- **Not every pick gets one.** Unranked, keeper and auction picks return `—`, read from the same
  shared `scored` list `build_draft_review` and `draft_board_view` already filter on. Two
  definitions of "this owner's draft" in one response is the bug that list exists to prevent.
- **Position adjustment is out.** TE has n=3 in ECR 1–12. Dynasty rookie ECR also already prices
  position in; adjusting again would double-count it.

#### Cohort delivery

The bars are **league-scoring-specific**, so a table of points cannot be shared across installs.
The inputs can: commit the ranked rookies' **raw component stats** (~2,000 rows of a dozen
integers, comparable to the 74KB ECR file) and score them with each league's settings at refresh.
No nflverse fetch at runtime; correct for every league's scoring.

**Use `stats_player/stats_player_week_{season}.csv`.** The legacy `player_stats/` path returns
200 for `player_stats_1999.csv` and **404s for 2025** — nflverse renamed the release and the old
path silently serves history only. Same failure mode as the `.csv.gz` above.

## Needs reconstruction

### Roster as of a date

New pure module `engine/roster_asof.py`. Seed from the **prior season's final-week roster** per
owner, then apply every completed transaction with `status_updated`/`created` **on or before**
the draft date, in timestamp order, across both the prior and current league ids.

Validated for 2025-05-16: **12 rosters, 362 transactions applied, sizes 18–24**, coherent
positional make-up. Offseason moves **are** recoverable — Sleeper carries Feb–July transactions,
57 in May 2025 alone.

### Quality at that date

Counts are not need: one QB for one QB slot is "covered" and fragile. Quality comes from the
**`dynasty-overall` ECR board** (`ecr_type = "do"`; superflex reads `"dsf"`) dated on-or-before
the draft — 360 boards, 751–956 players ranked, resolving 0–5 days before each draft, from the
same parquet and crosswalk. No new dependency.

### Defining a hole

Fill each **starting slot** in `roster_positions` from the reconstructed roster by draft-day ECR
using `engine/lineup.py::solve_optimal_lineup` — reused rather than hand-rolled, which keeps FLEX
handling identical to the lineup-skill signal.

> A slot is a **hole** if the player filling it ranks below the league's replacement line at that
> position.

The replacement line is computed **from the league itself** — for a 12-team league starting one
QB, the 12th-best QB across all 12 reconstructed rosters. No external constant, no assumed league
size, and it moves with the league's own depth.

**K and DEF are excluded.** `dynasty-overall` does not meaningfully rank them, they are streamed,
and no rookie draft addresses them. A K "hole" is noise dressed as a finding.

### The three verdicts

1. **Drafted into the need?** Does the pick's position match a hole open at draft time.
2. **Filled it?** Did the pick start at that slot — from `games_started`, already computed and
   owner-gated.
3. **Did the unfilled hole cost them?** The hole's actual starter's production versus the
   replacement line's, over the season.

## The column budget

**Decided 2026-08-17, after phase 2 shipped.** A width audit showed the desktop pick table needs
**988px before the Player column gets anything** once phases 3–4 add the Verdict column plus
sort arrows and tooltip triggers — roughly **1188px** of viewport for a legible player name. The
gate at the time was 870px, so the table would have overflowed by 168px. The breakpoint had
already been raised once (701 → 870) for the same reason.

Raising it again would have put a 1024px laptop on the phone layout. Instead, **the board's pick
rows carry only what the board is for.**

| Surface | Question it answers | Pick-row columns |
|---|---|---|
| League board | *Who drafted well?* | pick · owner · player · baseline · slot +/- · verdict · **Total Points** · **Start %** · GS · now |
| Owner Draft tab | *How did my picks do?* | the above **plus Regular Season · Playoff · Toilet Bowl** |

Two consequences, both deliberate:

- **Projected points drop once a class is graded.** A preseason estimate is superseded by what
  actually happened; on a graded row it is trivia. It stays on an **unplayed** class, where it is
  the only forward-looking figure there is. This also collapses the pick-grid templates from
  eight to six, since `graded` now implies no projection.
- **Regular / Playoff / Toilet leave the board's PICK rows** — they remain on the board's **owner
  rows** (where the per-phase split is a real question about a manager) and in full on the owner
  Draft tab. Phase 2 added them to the pick rows; this removes them again. That is a reversal, and
  it is cheaper than a third breakpoint negotiation.

The five-metric vocabulary is unchanged. This governs which metrics earn a **column on one
screen**, never what the metrics are or what they are called.

## GroupedHead — a sanctioned primitive

**Decided 2026-08-17.** The grouped two-tier header is added to `.design/` through design review
rather than built as a local dialect. Its spec:

- **68px** — an 18px naming tier over `SortButton`'s mandated **44px** target. The 44 is not
  negotiable; `Row variant="head"` is 44px *specifically* so a SortButton fits, and stacking a
  tier on top is what makes this a new shape rather than a variation.
- **Only for tables with 8 or more columns.** Below that a single-tier head is not crowded and
  the extra 24px buys nothing.
- **Group caps must encode real structure**, never decoration. The case that earns it: a "Points"
  cap lets the columns beneath read *Total · Regular Season · Playoff · Toilet Bowl* instead of
  printing "Points" four times across one header. Factoring out a genuinely shared word is the
  point; grouping unrelated columns to look tidy is not.
- Cap type is mono at `--text-label`, `--dim`, with a `--rule-strong` underline spanning exactly
  its group.

Until it exists in `.design/`, phase 4 does not ship its header. **Adding an entry to the drift
guard's exception list is not an alternative** — that is how a design system stops meaning
anything.

## Screens

### Nav

Both navs gain **Draft**: `TopBar`'s inline run (four → five) and `DashboardTabs` (four → five
full-width cells; 78px each at 390px, 44px height untouched).

- **No icon.** Nothing in the nineteen marks reads as "draft," and Bets already sets the
  precedent of an unmarked item. Drawing a twentieth is how a drawn set stops being a set.
- **New route `/league/[id]/draft`** redirecting to the newest draft season. The nav cannot link
  to a season it does not know, and `TopBar` has no dashboard data.

### League board

Season selector · **Owners** · **Picks** · **Going in**.

Owners: rank · owner · Points Above Round · Total · Start % · Regular Season · Playoff · Toilet
Bowl · Hit/Bust · Picks.

**Hit/Bust is derived from the same per-pick verdicts the Picks ledger renders**, never computed
independently. The owner column's totals must equal the pick column's counts — the house rule
that a headline figure equals the rows beneath it, which has no exceptions.

> **SHIPPED 2026-08-18.** Hit/Bust is on the Owners table as a ninth column
> (`OWNER_GRID_GRADED_VERDICT`, 822px against the 860px budget) and Picks
> rides in the Owner cell as a dim mono suffix, costing no track at all. The
> width decision the block below asked for was made as **"add only where it
> fits"**: `OWNER_GRID_GRADED_ADP` deliberately does NOT get the column, so
> nothing was trimmed and the 910px gate did not move. Three facts drove it —
> the table below was measured against a 870px gate and is **stale** (the real
> figures are 724px for GRADED_ONLY and 858px for GRADED_ADP against an 860px
> budget, not 678/868); ADP is captured going-forward-only from dated daily
> snapshots, so **no league reaches the ADP template at all today** (all 108
> picks on the reference league carry `adp: null`); and raising the gate to fit
> both would have pushed it past the 1024px viewports that would then fall back
> to cards. Verified in a real browser at 910/1024/1280px: no row overflow, no
> document scroll, header single-line at 44px, and only a 23-character owner
> name truncates, only at the 910px gate itself.
>
> The rest of this block is kept as the reasoning of record.
>
> **NOT SHIPPED, and deferred deliberately — 2026-08-17.** Phase 3 shipped the per-pick Verdict
> but never rolled it up to the owner row; the Owners table's 9th/10th slots are ADP +/- and
> Coverage. This surfaced during phase 4 only because a sort accessor was written for a column
> that turned out not to exist.
>
> It is **not** a mechanical addition, and this section is in tension with **The column budget**
> below, which is the later and more specific decision. Measured against the current templates
> (tracks + `gap-2.5` + `px-3.5`, against the `min-[870px]` gate):
>
> | Owners template | tracks | min width | + Hit/Bust | + Hit/Bust + Picks |
> |---|---|---|---|---|
> | `OWNER_GRID_MIN` | 2 | 202px | 288px | 350px |
> | `OWNER_GRID_ADP_ONLY` | 4 | 392px | 478px | 540px |
> | `OWNER_GRID_GRADED_ONLY` | 8 | 678px | 764px | 826px |
> | `OWNER_GRID_GRADED_ADP` | 10 | **868px** | 954px | 1016px |
>
> Two readings, both important. **The widest owners template already sits at 868px against an
> 870px gate — two pixels of headroom before anything is added.** That is the same disease as the
> parked picks-table finding (the widest picks template leaves the Player column 36px at 870px and
> stays illegible to ~950-1000px); the owners table has it too, and neither is fixed. And adding
> both required columns puts it 146px over, which re-opens exactly the breakpoint negotiation the
> column budget resolved by trimming rather than raising the gate.
>
> So Hit/Bust needs a **width decision first** — trim, compact into one column, or accept it only
> on the non-ADP templates where it fits (826px on `GRADED_ONLY`). That is design work, not
> implementation, and it does not belong as a rider on a phase-4 task. It gets its own scoped
> piece, starting from this table rather than rediscovering it.
Picks: Round·Pick · owner · player · ECR · Slot +/- · Verdict · the five-metric run · GS · Now.

Header is **grouped** — a naming tier over the labels, with the **Points** group supplying the
shared word so the columns beneath read Total / Regular Season / Playoff / Toilet Bowl. Every
column sorts, via `SortButton` (`aria-sort`, the system's own sort marks). **Sorting must reorder
the phone cards from the same array** — reordering only the desktop rows desynchronises them,
which is invisible on desktop and wrong on a phone.

Definition tooltips on every non-identity column, per `Tooltip.prompt.md`: the `info` mark (not a
circled "?"), the **26px** target that must not be raised to 44, `position: fixed` so `Panel`'s
`overflow: hidden` cannot clip it. Identity columns — Round·Pick, Owner, Player, `#` — carry no
trigger; their names are the whole explanation.

**Now** follows `PastPicksTable.tsx`'s existing treatment: coloured mono text, not chips.
Rostered `pos-strong`, Dropped `neg-strong`, Traded and Inactive `dim` — trading a player away is
a decision, not a failure. **Sleeper publishes no "Retired" status** (Active / Inactive / Injured
Reserve / PUP / Practice Squad / Non Football Injury), so the fourth state is **Inactive**,
derived from `active: false` / no NFL team.

The `graded` gate still governs the Points group. **ECR and Slot +/- render from draft night**,
which is the whole point — a class can be assessed months before it plays.

### Owner Draft tab

`PastPicksTable.tsx` gains ECR, Slot +/-, Verdict and Start %, keeping its value arc and All-Time
selector. Stays gated on `draft_picks_by_season`, **not** `outlook` — that gate is what used to
hide draft grading from redraft leagues entirely.

The two screens must not diverge: same verdicts, same cohort, same `scored` list.

## Cache

**No `SCHEMA_VERSION` bump.** Additive display fields with `default_factory` plus read-time
fallback, on the `league_phase` precedent. A bump makes every prod entry a miss and 409s
dashboards until rebuild.

The rookie ECR baseline is **display-only and must never feed Franchise Rating**. That is what
keeps this a no-bump change: the moment a baseline feeds a rating, stale is silently wrong and
the rubric demands a bump. It also keeps this work clear of `franchise-rating-calibration`.

**Placement: value layer, always recomputed.** `drafted_picks` already lives there, so the new
fields ride along at no rebuild cost — a dict lookup against a pinned board. Compute best-effort
(`try/except` + `log.exception`) so refresh never fails on the new field.

## Testing

Per the `chain-cache-field` quartet, for each new persisted field: round-trip through
`ChainCache`; pre-feature default; grader stamps it (with the wiring mutated out to prove the
test bites); surface fallback on a pre-feature entry.

Plus pure unit tests on `rookie_board.py` (on-or-before invariant, unranked → `None`),
`roster_asof.py` (transaction ordering, missing timestamps skipped), and the cohort binning —
specifically that **fractional ECR lands in the correct band**, which is the bug that produced
false hits during design.

Frontend: extend `web/tests/furniture-rules.test.ts` coverage over the new components.

## Sequencing

This is larger than one sitting, and the pieces have clean seams. The implementation plan should
phase it, each phase shippable on its own:

0. **Done.** Phases 1 and 2 have shipped on `new-draft-board` (phase 1 in PR #10; phase 2
   committed, unpushed). The list below is amended by **The column budget** and **GroupedHead**
   above, both decided after phase 2.

1. **Baseline** — committed ECR history, `rookie_board.py`, the store, the grader fork. Ships
   ECR + Slot +/- on the existing board; nothing else changes.
2. **Metrics** — the `"started"` phase, Start %, PAR, the full five-metric run on both screens.
3. **Verdict** — committed component stats, cohort scoring, the Verdict column.
4. **Screens** — grouped header (gated on the `GroupedHead` review), sorting, tooltips, nav.
5. **Needs** — `roster_asof.py`, `dynasty-overall` quality, the "Going in" panel.

**Phase 2.5 — the column trim.** Between phases 2 and 3: drop Projected on graded classes, and
remove Regular / Playoff / Toilet from the board's PICK rows (keeping them on its owner rows and
in full on the owner Draft tab). Small, and it must land *before* phase 3, because phase 3 adds
the Verdict column and the table has no room for it otherwise.

Phase 5 is the softest and depends on nothing above it, so it can slip without blocking the rest.
Phase 4's header work is blocked on `GroupedHead` reaching `.design/`; the rest of phase 4 is not.

## Risks and open questions

**~~Reconciliation, unresolved.~~ CLOSED 2026-08-17 — the app was right.** The ~6% gap
(Mikey 528.8 against the board's 494.8, consistently, across 7 of 12 owners) was an artefact of
the *independent recomputation*, not of `build_draft_board`. `_assemble_played_matchups` drops
unpaired roster-weeks; the check did not, and counted weeks the app correctly excludes. No code
change was needed. Worth keeping as a lesson: the reconciliation was run to catch a bug in the
app and instead caught one in the check, which is the outcome a reconciliation is *for* — but it
spent a release cycle sitting in this section as though the shipping code were suspect.

**~~The grouped header is a new shape.~~ CLOSED 2026-08-17 — `GroupedHead` shipped in `3f1e973`.**
Authored in the Dynasty Analyzer Design System project, synced to `.design/components/ledger/`,
mirrored at `web/components/furniture/GroupedHead.tsx`. Resolutions to its four open questions are
in `docs/superpowers/specs/2026-08-17-groupedhead-design-proposal.md`. No drift-guard exception was
added. One thing the proposal did not anticipate: the consumers render inside `role="table"`, so
the naming tier had to become a real `role="row"` of `role="columnheader"` cells carrying
`aria-colspan` — that markup lives in the web mirror only, since `.design/` primitives are
style-only and take their roles through `...rest`.

**Needs is inferred, not measured.** Everything else on the board is a measurement; "need" is a
judgment built on measurements. Commissioner roster edits do not appear as transactions, so a
manually-adjusted roster drifts silently. A transaction missing a timestamp is skipped, not
guessed at.

**Cohort sample is four classes.** The 2020 board fell outside the April 20 – May 31 window and
was skipped. Widening it and going back to 2020 gets ~470 observations and steadies the thin top
bands (ECR 1–4 is n=12).

**Committed data files need periodic regeneration.** Both the ECR history and the rookie
component stats have an end date. A fresh install deployed long after generation has a gap until
its first capture. This is a maintenance task, not a runtime one, and must be stated in each
script's docstring.

**Redraft and keeper leagues are unaffected** by the rookie baseline and keep Sleeper ADP, which
populates for them. The new production columns, PAR and the nav entry apply to every format.
