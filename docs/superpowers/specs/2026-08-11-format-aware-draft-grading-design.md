# Format-aware draft grading — design

**Date:** 2026-08-11
**Status:** approved, ready for implementation plan

## Problem

Draft grading exists but is built entirely around the **dynasty rookie draft**. Three
pieces ship today:

- `engine/draft_signals.py::draft_skill` — per-owner skill signal, 0.30 of the Skill
  pillar in every Franchise Rating weight tree.
- `engine/draft_results.py::build_drafted_pick_results` → `PastPicksTable.tsx` — per-owner
  all-time pick rows.
- `engine/draft_results.py::build_draft_review` → the `phase == "draft"` dashboard lead.

None of it is format-aware. Concretely:

1. **Rookie-vs-full drafts are inferred from a heuristic.** `build_rookie_picks` excludes
   any draft whose season equals the chain origin, calling it "the startup draft." In a
   redraft chain every season is a full draft, so year one is silently discarded. It also
   loses the rookie class in a dynasty league that ran a startup *and* a rookie draft in
   the same origin season.
2. **Keepers are graded as draft picks.** Nothing reads `is_keeper`. A kept player scores
   for his owner *and* sits in the round's peer group, dragging the baseline for everyone
   who actually picked there.
3. **The per-pick table is unreachable in redraft leagues.** `owner_view` ships
   `draft_picks_by_season`, but `PastPicksTable` renders inside `FutureDraftTab`, and the
   Outlook tab is dropped wholesale for redraft. The data exists; no screen shows it.
4. **The value axis is wrong for redraft.** KTC is skipped for redraft chains and
   `snapshots-redraft/` starts empty, so the value half of the skill blend, the value arc,
   and `avg_slot_value` are structurally meaningless.
5. **There is no league-wide draft view at all**, in any format. The only league-level
   surface is the three-figure dashboard lead.
6. **Auction drafts would grade as nonsense** — `pick_no` is chronological, so a slot
   delta is pure noise.

A redraft league is connected with its draft on ~2026-08-16, which sets the delivery bar:
something real must render on draft night, before any production exists.

## Verified data sources

All confirmed live on 2026-08-11 against `api.sleeper.app`, not assumed.

### Draft objects — `GET /league/{id}/drafts`

`settings.player_type` is the rookie-vs-full discriminator: **`1` = rookies only,
`0` = all players**. Confirmed `1` on the dynasty league's 2026 rookie draft. Also
carries `type` (`snake` | `linear` | `auction`), `settings.rounds`, `settings.teams`,
and `draft_order` (`{user_id: slot}`).

`slot_to_roster_id` came back **empty** on a real completed draft — do not depend on it.
`picked_by` + `draft_slot` on each pick are the reliable pair, which is what the current
ingestion already uses.

### Draft picks — `GET /draft/{draft_id}/picks`

Each pick carries `round`, `pick_no`, `draft_slot`, `roster_id`, `picked_by`,
`player_id`, **`is_keeper`**, and `metadata` (including `years_exp`, `"0"` for rookies —
a useful cross-check that a class really is a rookie class).

### ADP and projections — `SleeperClient.get_projections(season)`

**This method already exists and already works.** It hits
`/v1/projections/nfl/regular/{season}` and returns a dict keyed by Sleeper `player_id`.
The backend has never called it; only the CLI simulator does.

For season 2026 it returns 9,412 players. Fields that matter:

| Field | Real values (2026) |
|---|---|
| `adp_std` | 310 |
| `adp_half_ppr` | 311 |
| `adp_ppr` | 311 |
| `adp_2qb` | 329 |
| `adp_dynasty` | **0 — unpopulated** |
| `adp_rookie` | **0 — unpopulated** |
| `pts_std` / `pts_half_ppr` / `pts_ppr` | 1,065 |
| raw stat projections (`rec`, `rush_yd`, …) | 474 receiving / 376 rushing |

Genuine-ADP coverage by position (2026, `adp_ppr` < 999): **WR 101, RB 76, TE 35,
K 35, QB 33, DEF 31 — 311 total.** Kickers and defenses are covered, which was the
open question that drove this source selection.

Three properties make this strictly better than the FantasyCalc redraft set that was
originally proposed:

- **Native Sleeper `player_id`** — no id mapping, no `sleeperId` matching, no unmatched
  drops.
- **Scoring variants** (`std` / `half_ppr` / `ppr` / `2qb`) so the baseline calibrates to
  the league, where the FantasyCalc fetch hardcodes `numTeams=12, ppr=1`.
- **Real fractional ADP** aggregated from actual Sleeper drafts (Gibbs 1.6, Bijan 1.8) —
  the same drafting population as the league being graded. FantasyCalc's `overallRank` is
  a trade-value rank, which is a different measurement.

`normalize_projection(stats, league.scoring_settings)` already exists and converts raw
stat projections into *this league's* points, so projected points can be league-native
rather than generic PPR.

**Gotcha: `999.0` is the undrafted sentinel, not an ADP.** It must be filtered or it
becomes a catch-all bucket — the same failure mode as DynastyProcess's literal `"NA"`
already documented in CLAUDE.md.

### Rejected sources

- **Sleeper `search_rank`** — position-scoped, not overall ADP. Bijan (RB) and Josh Allen
  (QB) are both rank 1; two players at 3, two at 5. Unusable as drafted.
- **FantasyPros ADP** — has K/DST and is a true multi-site consensus, but HTML-scraped and
  needs name matching. Strictly worse than a native-id JSON endpoint we already call.
- **ESPN / Yahoo ADP** — no clean public API. Yahoo is separately blocked on entitlement.
- **nflverse / DynastyProcess** — dynasty values and id crosswalks, not redraft ADP.
- **Building our own ADP** — infeasible. ADP is a crowd statistic requiring thousands of
  observed drafts; we see only this user's leagues. Building our own projections means
  modeling player performance, a larger project than this entire feature.

## Approach

**A `DraftClass` descriptor normalized once at ingestion**, consumed by everything
downstream. Format branching happens at one boundary rather than being re-derived at each
call site.

This follows two existing patterns in the codebase: `engine/capabilities.py` answers
format questions once so nothing downstream re-derives them, and `api/platform.py`
normalizes ingestion once so no platform encoding leaks inward. It also makes the auction
refusal a single `gradeable=False` at the boundary instead of a guard in four functions.

Rejected: threading `format` into every function (the "is this dynasty?" question gets
re-asked in five places and they drift), and parallel `rookie_draft.py` / `full_draft.py`
modules (~80% duplicated — the ranking method is genuinely format-agnostic).

## Results and grades are different things with different availability dates

This is the central design decision, forced by the draft landing before any production
exists.

- **Results** — who took whom, at what slot, in what round — exist the instant the draft
  completes.
- **Grades** — peer delta, production rank, `draft_skill` — need played games.

Every current guard is production-gated: `build_draft_review` returns `None` when nothing
has scored. Applied naively to a just-completed draft, the app shows nothing for weeks.
The board therefore renders **results from day one and layers grades in as production
arrives**. Refusing to show a hollow *grade* is correct; refusing to show the *results* is
just an empty screen.

## Three baselines, three columns — not one blend

Skill is always *result − expectation*. Each baseline answers a different question, so
they stay separate rather than being averaged into a composite whose weights cannot be
defended without data:

| Baseline | Question | Availability |
|---|---|---|
| **Peer delta** | did you draft better than your leaguemates at the same slot? | always; grades past seasons |
| **ADP delta** | did you beat the market? | redraft/keeper, draft-day snapshot onward |
| **Projection delta** | did you beat expected points at your slot? | redraft/keeper; separates process from luck |

**`draft_skill` feeding Franchise Rating stays the peer baseline in every format.** It is
the only baseline available for every league, season, and format — `adp_rookie` is
unpopulated, so dynasty rookie drafts have no market reading. Pinning the rating to it
means an owner's grade never shifts because an external source happened to resolve or not.
ADP and projection deltas are board-facing only.

### ADP is a point-in-time measurement

Sleeper's ADP is *current* ADP and moves through the preseason. Grading a draft in
December against December's ADP turns "beat ADP" into "beat hindsight" — production
ranking with extra steps and more failure modes.

Mitigation: **capture the draft-day ADP snapshot**, using the mechanism that already
exists. `KtcSnapshotStore` writes dated snapshots on refresh and the `snapshots-redraft/`
namespace is already in place. The auto-refresh scheduler stamps the ADP baseline when
`phase == "draft"` and the draft completes. Accuracy is within one refresh interval,
which is immaterial for a season-long ranking.

Consequence: ADP grading works **going forward only**. Past redraft seasons have no
draft-day snapshot and grade on the peer baseline alone.

## Format matrix

| | **Dynasty** | **Redraft** | **Keeper** |
|---|---|---|---|
| Drafts graded | rookie only (`player_type=1`) | every season's full draft | full draft, keeps flagged |
| Year one | excluded (startup) | **included** | included |
| Peer baseline | yes | yes | yes |
| ADP baseline | no (`adp_rookie` empty) | yes | yes |
| Projection baseline | no | yes | yes |
| Keeper picks | n/a | n/a | **shown, not scored** |
| Value-arc columns | yes | **omitted** (no price history) | omitted |
| Feeds Franchise Rating | peer, 0.30 of Skill | peer, 0.30 of Skill | peer, 0.30 of Skill |
| Auction | results only, no grade | results only, no grade | results only, no grade |

Value columns are **omitted, not zeroed**, for redraft and keeper — following the
established redraft-Outlook precedent where absent data means an absent column.

## Stage timeline

| | Draft night (~Aug 16) | Midseason | Year end |
|---|---|---|---|
| Columns live | ADP delta, projected total | + actual points, actual vs projected | + peer delta, production rank |
| Headline | **Draft Grade** | is it holding up? | **Draft Recap**, and did the draft-night grade hold |

The year-end "did the grade hold up" reading exists *only because* the draft-day snapshot
was captured. "You had the best draft on paper and finished 9th" is not recoverable
after the fact.

Coverage is always stated — "graded on 13 of 15 picks". Picks with no ADP (undrafted
sentinel, or outside the 311) are **excluded from the ADP grade and counted**, never
silently normalized and never scored as zero.

## Components

### `engine/draft_class.py` (new)

```
DraftClass:
    draft_id: str
    season: int
    kind: "rookie" | "full"
    type: "snake" | "linear" | "auction"
    gradeable: bool          # False for auction
    axis: "blend" | "production"
```

`axis` is set from the chain's format: dynasty → `"blend"` (value + production, today's
behavior), redraft and keeper → `"production"`. Auction classes carry `gradeable=False`
regardless of axis.

`build_draft_classes(...)` replaces `build_rookie_picks`'s origin-season heuristic:

| `player_type` | dynasty chain | redraft / keeper chain |
|---|---|---|
| `1` (rookies only) | include, `kind="rookie"` | include if present (rare) |
| `0` (all players) | exclude — startup draft | **include, `kind="full"`, every season** |

Pure. No I/O.

### `engine/draft_signals.py`

`DraftedPick` gains `draft_kind` and `is_keeper`. `draft_skill` filters `is_keeper` before
computing peer baselines, so a keep neither scores for its owner nor drags the round's
expected outcome for anyone else. `axis == "production"` drops the value term and the
`min_games` unplayed-rookie carve-out (a redraft pick that never played scored nothing,
and that is the real answer, not missing data). `axis == "blend"` is today's behavior,
unchanged. `gradeable=False` excludes the class from skill entirely.

### `engine/draft_results.py`

Per-pick rows gain ADP and projection fields. `build_draft_review` gains the
results-without-grades state: it returns a populated review with grade fields absent
rather than `None` when a class has zero production.

### API layer

Threads ADP + projections in at refresh via the existing `SleeperClient.get_projections`.
Best-effort throughout. The scheduler stamps the draft-day ADP snapshot.

### `web/app/league/[id]/draft/[season]/page.tsx` (new)

One draft class, all owners, picks in draft order. Per-owner class summary reads the
already-persisted `draft_skill_by_season`. Season selector across available classes. A
`graded: bool` on the response drives the two states — pre-production the grade columns
are absent, post-production they appear.

### `PastPicksTable` relocation

Moves out of `FutureDraftTab` onto its own owner-page **Draft** tab, gated on
`draft_picks_by_season` being non-empty rather than on `outlook`. This is the specific bug
that hides draft grading from redraft leagues today.

### Dashboard lead

Gains a pre/post-draft results source so a league with no prior gradeable class and no
trade history is not blank through the draft window. Same fixed three-figure skeleton.

## Error handling

Every external read is best-effort, matching how KTC and FantasyCalc failures already
degrade in this codebase:

- ADP/projection fetch fails or changes shape → log, drop those columns, peer baseline
  carries the board. Never fails refresh.
- Draft fetch fails → empty classes, as today.
- No draft-day snapshot → ADP columns absent for that class, permanently. Stated on the
  readout rather than silently missing.
- Auction draft → results only, with the reason stated.

## Caching

Projections cached through `FileCache` on the existing daily pattern. Draft-day ADP
snapshotted into `snapshots-redraft/`.

`drafted_picks` is value-layer and recomputed on every refresh, so new fields on it need
no `SCHEMA_VERSION` bump. `DraftClass`, if persisted, must be run through the
`chain-cache-field` skill's rubric before landing.

## Testing

Pure unit tests per format, on fixtures recorded from real Sleeper payloads:

- rookie class (dynasty) — confirmed shapes already captured
- full draft, year one included (redraft)
- keeper picks flagged, excluded from skill, present in rows
- auction → `gradeable=False`, results only
- zero-production class → results with no grades, **not `None`**
- `999.0` ADP sentinel filtered
- picks with no ADP excluded from the ADP grade and counted in coverage
- peer baseline unchanged for dynasty (regression guard on existing behavior)

Frontend: Agate guard test must pass; all new UI follows the `agate-styling` skill.

## Out of scope

- Rookie-draft ADP — does not exist in the source (`adp_rookie` unpopulated).
- Redraft pick-trading valuation — the known KTC-skipped gap, separately deferred.
- Parameterizing FantasyCalc's hardcoded `numTeams` / `ppr`.
- Any change to trade valuation.
- Retroactive ADP for past redraft seasons — no historical ADP endpoint exists.

## Open item

The connected **redraft league id has not been provided**. Pre-draft fixtures should be
recorded before ~2026-08-16; that window does not reopen. Implementation proceeds on
synthetic fixtures built from the verified real payload shapes, and live verification
happens post-draft.

---

## Post-merge follow-ups — ALL CLOSED 2026-08-11

Shipped 2026-08-11 (merged to `main` as 34 commits). Everything below was found by the
final whole-branch review, adjudicated as non-blocking, and deliberately not fixed — the
detail is preserved here because the execution ledger it came from was scratch.

**All seven were subsequently fixed** on `fix/draft-grading-followups`. Kept below as the
record of what was wrong and why it mattered. Two notes on what the fixes revealed:

- **#5 was nearly fixed the wrong way.** Broadening `FileCache.invalidate_all`'s glob past
  `*.json` would have deleted `identity.db`, which lives in the same directory — the
  restriction is a guard, not an oversight. `cache.py` now says so.
- **#7 was smaller than described.** `e2e/viewport.spec.ts` already implemented the exact
  `scrollWidth <= innerWidth` assertion across three widths and both themes; the gap was
  only that the two new screens weren't in its sweep. Both defects of that class shipped
  on those two screens.

**Still unverified:** #1's fix cannot be exercised until the February gap it guards
against actually arrives.

**Deploy timing is the one hard deadline.** Daily ADP capture only begins once the code
is *running*, not merged. A draft completing before capture is live gets no ADP baseline,
ever — there is no historical ADP endpoint to backfill from.

1. **`nfl_state.season` rollover assumption.** The draft window's "current season" test
   assumes Sleeper rolls `season` forward the moment a season ends. If it instead holds
   the finished year while `season_type` flips to `off`, a completed May draft could
   reopen the window in that gap. Bounded (the `post` season_type covers the NFL
   postseason) and mild (a prior-class graded lead displaces trade-of-the-week), with the
   risk window in February. Sleeper publishes `league_season` explicitly as the upcoming
   league year — that is the unambiguous field to switch to.
2. **An all-auction or all-keeper newest class yields no lead.** `build_draft_review` now
   correctly filters both, so such a class returns `None` and the draft window falls back
   to trade-of-the-week. Strictly better than the previous bogus grade, but the honest
   "results, no grade" lead does not exist for auction leagues — and auction is common in
   redraft.
3. **Owners whose entire class is keepers/auction vanish** from the board's owner ranking
   (they never enter the scored set). Consistent with the absent-not-zero convention, but
   the ranking may not list every owner.
4. **`board.graded` is computed over all rows** including keepers and auction picks, so an
   all-auction class that has played reports `graded: true` with an empty owners list.
5. **Orphaned cache files.** Adding the `.json` suffix to the projections `FileCache` key
   leaves any pre-existing suffix-less `sleeper_projections_{season}` file unreachable and
   un-purgeable (one per season).
6. **`web/lib/types.ts`** still describes `draft_review` as "How the last rookie draft
   panned out" — the one stale comment the format-neutrality sweep missed.
7. **Responsive regressions are invisible to the test suite.** jsdom does not evaluate CSS
   media queries, so `vitest` asserts presence in the DOM, never reachability at a
   viewport. Two defects of this class shipped and were caught only by reading compiled
   CSS. A single Playwright assertion at 375px — `document.documentElement.scrollWidth <=
   clientWidth` — would cover the whole class, and the e2e harness already exists.
