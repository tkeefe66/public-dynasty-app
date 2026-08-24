# Franchise Rating v2 — winning, building, and what you hold

**Date:** 2026-08-16
**Status:** design approved in outline; calibration run outstanding before implementation
**Replaces:** the `results_led` / `keeper_led` / `redraft_led` three-pillar tree
(Results / Skill / Outlook)

## The premise

Dynasty is about winning and about building a good franchise. The rating should
score exactly that and nothing else:

```
v2    Franchise Rating = 0.60 · Results  +  0.40 · Assets
v2.1  Franchise Rating = 0.50 · Results  +  0.30 · Growth  +  0.20 · Assets
                         (winning)          (what you added)   (what you hold)
```

Winning on one side, building on the other, 50/50. The name **Franchise Rating**
is kept: it was only the wrong word when the number graded a *person*.

**Growth ships in v2.1, not v2** — it needs a roster-composition timeline whose
ingestion gap and test fixture are scoped below. The interim v2 weights are set
deliberately at 0.60 / 0.40 rather than renormalized proportionally (which would
give 0.71 / 0.29 and drift back toward the results-dominance this design exists
to fix). When Growth lands it takes its weight out of Assets, because a share
*delta* is the better-measured version of what a share *level* is standing in
for.

## What was wrong with v1

Measured on the live 12-team league (`chain_9000000000000000001`, seasons
2023–2025), not asserted.

**1. One fact charged four times.** `championships`, `playoff_depth`,
`made_playoffs` and `final_seed` all encode the same binary — did you make the
playoffs — and carry 0.90 of the Results pillar between them. They correlate
pairwise at r +0.61 to +0.91. An owner who has never made the field is charged
for it four times.

**2. Stated weights were not realized weights.** Realized pillar sd: Results
0.906, Skill 0.544, Outlook 0.793 — shares of composite spread 58.5 / 21.1 /
20.5 against stated 50 / 30 / 20.

**3. The Skill pillar does not measure skill.** Year-over-year persistence:

| signal | between-period correlation |
|---|---|
| `draft_skill` | +0.02, +0.11, +0.16 |
| `lineup_skill` | −0.17, −0.29, +0.57 (mean +0.04) |
| trade value (split-half) | **−0.40** |
| trade production (split-half) | **−0.71** |
| `expected_wins` | +0.34, +0.61 |
| `actual_wins` | +0.25, +0.18 |

Nothing in Skill persists; two of its four signals are *negatively* correlated
with themselves. `draft_skill` + `lineup_skill` carried 0.24 of the rating on
signals with roughly zero reliability. n = 12, so the confidence intervals are
wide — but there is no evidence of persistence in any of them, and weighting 0.40
on that is a bet the data does not support.

**4. Signals weighted past their evidence.** Lineup efficiency spans .804–.875
league-wide — a 1.6pp gap from the mean is worth about half a win a season — yet
z-scores to a −1.92…+1.76 spread. Roster mean age spans 24.33 to 26.39 across all
twelve teams and yields −1.30…+2.35.

**5. A straight mean over a roster measures roster filler.** Mean age ranked one
owner 10th of 12 on youth while his most valuable assets were a 24-year-old QB
and two young receivers.

**6. The bands are calibrated to a spread the model does not produce.**
`SCALE = 275` converts composite z as though its sd were 1.0. It is 0.70, so
realized rating sd is 192 against a `C` band spanning ±20 points, or ±0.10 sd.
`D+` begins at −0.52 sd. Roughly 30% of *any* league is D+ or worse by
construction.

## What the review pass changed, and why the first draft's remedy was wrong

The first draft of this design kept Skill, added per-signal sample-size shrinkage,
and re-standardized each pillar to unit sd so stated weights would equal realized
ones. Three independent reviews converged on the same structural error, and all
three are load-bearing here:

- **Shrinkage before re-standardization is bit-exactly a no-op.**
  Re-standardizing divides out any scalar applied to the pillar, and when every
  owner has the same `n` the reliability factor *is* a scalar. Measured on the
  Results pillar: `max |delta| = 2.22e-16`. It also made the amplification it was
  introduced to cure *worse*, 1.99× → 2.59×.
- **Re-standardization hands the least reliable pillar its full stated share.**
  The "weight leakage" diagnosed as defect #2 was an accidental reliability
  discount, and a directionally correct one: independent noisy signals average
  toward the mean; collinear reliable ones do not. Removing it is not a fix.
- **The single-pillar exemption's justification was false.** Signals are z-scored
  across the league before any pillar exists, so absolute level is destroyed at
  the first step. Compressing the entire league's raw roster spread 20-fold
  produced **bit-identical letters**.

**Consequence, stated plainly and published on the methodology page: this rating
is league-relative. The letter is a percentile within your league.** A global
cross-league scale is out of scope permanently — it is not what this app is for
(see `2026-08-11-cross-league-owner-grade-design.md`, which reaches the same
conclusion from the other direction).

So v2 does **not** re-standardize pillars and does **not** apply per-signal
shrinkage. It fixes collinearity where collinearity actually is, and calibrates
the scale to the spread the model really produces.

## Results (0.50)

| signal | weight | definition |
|---|---|---|
| `expected_wins` | 0.55 | decay-weighted mean of per-season all-play win % |
| `playoff_success` | 0.30 | decay-weighted mean of `0.5·berth + 1.0·title-path rounds won + 1.5·championship` |
| `luck` | 0.15 | `actual_wins − expected_wins`, decay-weighted |

`made_playoffs`, `final_seed` and `points_for_rank` are gone. `points_for_rank`
is subsumed by `expected_wins` at r = 0.955 on a finer grain; the other two are
the quadruple-count.

All-play win % is, for each regular-season week, the share of the other rosters
this roster outscored (ties count half). It is the most reliable quantity in the
model (adjacent-season r ≈ 0.47 against 0.16 for actual wins) and needs only
week-level `team_points`, already an input to `standings_as_of`.

`luck` is **residualized by construction** — it is the close-game component that
`expected_wins` cannot see, orthogonal to it by definition. This replaces raw
`actual_wins`, which was `expected_wins` plus schedule noise and re-injected 20%
of the thing the pillar exists to remove.

`playoff_success` is deliberately *not* residualized, and the pillar therefore
still correlates ~0.93 with `expected_wins`. That is a choice, not an oversight:
trophies are terminal facts and a league expects them counted. The difference
from defect #1 is that three signals at different resolutions is not four signals
encoding one binary. Residualizing `playoff_success` on `expected_wins` remains a
tunable if calibration says the pillar is too monotone.

## Growth (0.30) — asset-share trajectory

The honest replacement for Skill. It measures the same thing — did your moves add
value — through **consequence** rather than per-event scoring, aggregating every
trade, draft pick and waiver claim into one number instead of grading each in
isolation at n = 10.

| signal | weight | definition |
|---|---|---|
| `asset_share_delta` | 0.60 | share of league asset value now − share at chain origin |
| `asset_share_delta_recent` | 0.40 | the same delta over the last two played seasons |

**Asset value** = market value of rostered players plus owned future picks.
**Share** = this owner's asset value ÷ the league's total. Shares sum to 1, so
the signal is zero-sum and league-relative by construction, with no z-scoring
sleight of hand. Recency is built into the second signal rather than applied as
decay.

### The pricing decision, which is forced

There is no historical price data. FantasyCalc publishes no historical endpoint
and `KtcSnapshotStore.capture()` writes today, so prices before the snapshot
store began do not exist and never will.

Therefore **both endpoints are priced at today's values**, over the roster
composition that existed at each date. Growth is explicitly **outcome-based**: an
owner is credited for acquiring a player who *became* valuable, not for a trade
that looked smart on the day. That is the right reading of "did you build a good
franchise", and it matches the app's existing realized-value philosophy — but it
is hindsight by construction and the methodology page must say so in those words.

### Roster-composition timeline

Growth needs to know who held what, when. Inputs, all already fetched:

- **Trades** — `resolved_trades`, with both sides.
- **Drops** — `SleeperClient.get_drops`.
- **Draft picks** — `get_draft_results`.
- **Adds** — *currently discarded.* `get_drops` filters
  `type in ("drop", "waiver", "free_agent")` and then requires a non-empty
  `drops` dict, throwing away the `adds` side of the very same transactions. The
  data already arrives on a feed that is fetched and memoized per league
  (`_all_week_transactions`); recovering it is a filter change plus a protocol
  method, not a new ingestion path.

New protocol member `LeaguePlatform.get_adds(league_id)`, mirroring `get_drops`.
Yahoo implements it from its typed transaction collections. New engine module
`engine/roster_timeline.py` replays the event log to produce
`(owner, date) -> set[player_id]` plus pick ownership.

**The safety net is a round-trip test:** replaying chain-origin rosters forward
through every trade, add, drop and draft pick must reproduce today's rosters
exactly. If it does not, the timeline is wrong and Growth is not trustworthy.

### Scoping probe — measured, 2026-08-16

Replaying the 2023 startup draft forward through every cached transaction in
`created` order, **drops applied before adds within a transaction** (Sleeper
keys a trade's `drops` by the *giving* roster, so the reverse order reports a
100% false mismatch):

| event class | replay disagrees with the log |
|---|---|
| trade gives | **2 / 76 — 2.6%** |
| waiver/FA drops | **143 / 760 — 18.8%** |

Trade lineage is essentially exact. The 18.8% is the add-only gap and nothing
else: a drop of a player the replay never saw arrive. Paired rows survive fine
(161/254, 204/293, 168/213 of cached rows carry their `adds`).

Three constraints the probe surfaced:

- **Add-only rows never reach disk**, so this is not a filter change against
  existing caches — the raw bundles must be re-fetched behind a `schema_version`
  bump. Same feed, same memoized 18-week walk, no new network cost.
- **Chain origin is reconstructable but not from `drafted_picks`.** That field
  holds rookie drafts only (36 per season, 2024–26). The 2023 startup draft — 276
  picks, 23 rounds — exists only in the raw bundle, so the timeline builder must
  read raw draft results.
- **The round-trip test cannot be written against a local cache.** The current
  season's raw bundle is not cached (the chain covers 2026→2023; only three raw
  files exist), which is why a naive end-to-end replay scored 66% against
  `current_holders` — a missing season, not a broken algorithm. The test has to
  run in-process during a refresh, or against a fixture captured while every
  league in the chain is in hand.

Pick ownership is a **second timeline**, unprobed: origin is trivial (everyone
owns their own) and trades replay onto it, but it is separate work from the
player timeline.

Estimate: 3–5 days, with the risk in the fixture rather than the algorithm.

## Assets (0.20)

| signal | weight | definition |
|---|---|---|
| `roster_value_share` | 0.45 | share of league roster value (scale-free, replaces raw value) |
| `young_core_share` | 0.35 | share of *this roster's* value held by players aged ≤ 25 |
| `draft_capital` | 0.20 | tiered value of owned future picks (unchanged) |

`young_core_share` replaces negated mean age. `rating_signals.py` already holds
all three inputs keyed by Sleeper `player_id` — `ktc_by_player_id`,
`player_ages`, and `current_holders` — so no new plumbing is needed and
`AgeProfile.core_young` (which runs in a later stage) is not involved.

**Players with an unknown age must be excluded from both numerator and
denominator.** Present in the denominator only would systematically penalise
deep-bench rookies — exactly the owners the signal exists to reward.

`form` is **cut**. It was monotone in how bad you were (the worst prior season
has the most headroom, a defending champion can only regress) and was a
difference of two noisy numbers at 0.15 weight. Growth measures direction
properly.

## Recency

Season weight `w(s) = min(1.0, 0.5 ** ((latest_played_season − s) / 2))` — a
two-season half-life, **clamped at 1.0**. Applies to the Results signals.

The clamp is not cosmetic: `draft_skill_by_season` already holds a 2026 class,
and without it that class draws weight **1.414** — more than the anchor — while
being graded on market price alone, since it has played no games. Any season
with no played weeks is excluded outright.

`latest_played_season` is the most recent season with played regular-season
weeks, never the calendar season. It must additionally require a **minimum
played-week count** before a new season becomes the anchor; otherwise the whole
chain's decay re-anchors in week 2 and every owner's grade jumps for reasons
unrelated to their play. Reuse the existing phantom filter
(`wins + losses + ties > 0`) rather than inventing a new one.

Decay is directionally justified — lag-2 correlation ≈ lag-1², a clean AR(1)
signature — but the implied half-life is nearer 0.9 seasons than 2, and at n = 12
over three seasons it cannot be estimated. **Two seasons is a chosen prior and
the methodology page must present it as one.**

## Normalization — what we deliberately do not do

- **No pillar re-standardization.** The natural compression of an independent
  blend is a reliability discount and is kept.
- **No per-signal shrinkage.** Inert wherever `n` is uniform, which is the normal
  case, and it worsened the amplification it targeted.
- **`draft_skill`'s existing raw-space shrink is removed along with the signal
  itself.** Nothing in v2 shrinks in raw space, so the double-shrink question
  (raw `k=3` compounding with a z-space `k=6`, a 3.46× undisclosed differential)
  disappears rather than being resolved.
- **Trade-signal z populations no longer contain placeholder zeros**, because the
  trade signals are gone from the tree entirely.
- **Contribution additivity is preserved.** `compute_gm_ratings` emits
  `contribution = SCALE · w · w2 · z` per signal, and `OverviewTab` visibly
  reconciles `1500 + Σ contributions` against the rating. Re-standardization
  would have broken that invariant on every owner; not doing it keeps the
  guarantee for free. A guard test asserts it.

## Thin evidence — absence, not a confident letter

Two cases where v1 would have graded confidently on nothing, both raised
independently in review.

**A league with no played season.** `latest_played_season` is undefined, every
Results signal is undefined, and missing keys read `0.0` — which for
`expected_wins` means "lost every all-play matchup". Render **`—` with the
caption "first season"**, not a letter. The same rule covers the preseason gap
before week 1 of a new chain.

**An owner who joined mid-chain.** Their Results correctly cover only the seasons
they played, but `asset_share_delta` measured from chain origin charges them for
a roster they did not build, and `Assets` is a census fact about someone else's
decisions. Measure Growth from **the owner's own first season**, not chain
origin, and suppress the letter entirely until they have completed one season —
`—` with the caption "new franchise". A replacement manager handed an orphaned
team must not receive a D− on day one for the previous owner's work.

This is the one place a reliability discount survives, and it is applied as a
**gate on the whole rating**, not as a per-signal factor — which is precisely the
placement the shrinkage analysis showed is the only one that is not cancelled
downstream.

## Letter bands and SCALE

**`SCALE` is calibrated from the measured composite sd, not assumed to be 1.0.**
This is defect #6 fixed at the level where it actually occurs. Bands are stated
as sd multiples and convert through the calibrated `SCALE`, so the two columns of
the table can no longer disagree.

Starting ladder, **final values to be set by the calibration run**:

| letter | sd |
|---|---|
| A+ | ≥ +1.40 |
| A | +1.15 |
| A− | +0.90 |
| B+ | +0.68 |
| B | +0.45 |
| B− | +0.22 |
| C+ | +0.07 |
| C | −0.22 |
| C− | −0.45 |
| D+ | −0.68 |
| D | −0.95 |
| D− | below |

Three deliberate changes: **C+ is restored** (v1's proposal dropped it silently,
making the mirror of C− a B−); **C is widened** so the grade the scale centres on
is actually occupied — at ±0.12 sd it held about one owner in twelve while five
held Bs; and **F is removed from the ladder.** A twelve-owner league spans roughly
±1.75 sd, so F could only ever fire by construction or never. Announcing A+
through D− is the truthful scale. Note the composite is right-skewed (measured
skew +0.99; `roster_value` +2.08 with a max |z| of 3.01), so the top band is
reached more easily than the bottom — consider winsorizing signal z at ±2.5.

## Format trees

- **Dynasty** — as specified: 0.60 / 0.40 in v2, 0.50 / 0.30 / 0.20 in v2.1.
- **Keeper** — same pillar split as dynasty; Assets drops `young_core_share` (two
  or three keepers is not a young roster) and renormalizes `roster_value_share`
  0.70 / `draft_capital` 0.30.
- **Redraft** — Results only, at weight 1.0, in both v2 and v2.1. Nothing carries
  over, so neither Growth nor Assets has a subject. `redraft_led` is retired.

Every tree must sum to 1.0; `tests/test_gm_rating.py` already asserts this across
all registered trees and the new ones go in the same list.

## Surfaces

### Owner hero

- **The franchise blurb is removed.** `HeroBand.tsx:133-134` is its only render
  site anywhere in the app, so deleting it means the `franchise_blurbs`
  generation path produces something nobody reads — **retire the writer too**,
  which is a straight LLM cost saving. (This is the blurb that described a salary
  cap in a league that has none, and called a roster both "trending downward" and
  holder of "a legitimate young core" in one sentence.)
- **The receipt returns under the letter**, which is the actual fix for the
  complaint that started this work. The Furniture port reduced `VerdictRail` to a
  bare letter on the reasoning that the Overview tab carries the receipt; the
  owner saw an unlabelled F and concluded the model was broken. `HeroBand.tsx`
  still imports `ratingDrivers` and still declares a `Trend` component, **neither
  of which is used anywhere in the file** — the helpers survived the cut, so
  restoration is close to free.

```
tom                              B−
                          ROSTER #6 OF 12
                          1487 ▲12 · drag: Playoff Points

TITLES —   PLAYOFF TRIPS 0/3   RECORD 16-26   BEST FINISH 9th
```

The rings strip stays. Add one line beyond the old receipt: **"what would move
this most"** — the signal with the largest `|weight × (league-best z − your z)|`.
It converts a verdict you argue with into something you can act on.

### Roster rank

`roster_rank` is already computed, persisted, and in the copy-receipt string, but
renders in exactly one place — a `Stat` inside the Outlook tab. It gets three
more homes: the hero (above), a `Roster` column on the standings table, and the
same column on the `/gm` leaderboard. Nullable on both sides and dropped for
redraft, exactly as the Outlook columns already are (`hasOutlookColumns`).

### Everything else

| surface | change |
|---|---|
| standings row | `gm_letter` keeps its name and meaning; gains a `Roster` rank column |
| `/gm` leaderboard | pillar receipt renders Results / Growth / Assets |
| `Leaderboard.tsx:385` | redraft detection via `"outlook" in r.pillars` is now permanently false — must move to the capabilities format |
| `OwnersTab.tsx:127` | `o.gm_letter ?? o.grade` silently falls back to the *trade* grade in identical styling; fix rather than inherit |
| methodology page | rewrite — see below |
| OG cards | gm and owner cards render a letter; band/tone maps must follow |
| three tone maps | `ownerdeepdive/util.tsx`, `lib/og-card-data.ts`, `StandingsTable.tsx` each re-derive from `letter.charAt(0)` |

### Methodology page — not optional cleanup

`MethodologyContent.tsx` **re-declares `LETTER_BANDS` in TypeScript** as a
hand-copied table with no import and no cross-language test, hardcodes
`1500`/`800`/`2200`, hardcodes "Results leads at 50% / Skill 30% / Outlook 20%",
and publishes the promise *"not year-scoped, so a one-year blip doesn't whipsaw
your letter"* — which recency decay directly reverses. It is the only surface
that explains the grade, and it will be actively lying the moment this ships.

It must additionally state three things v2 makes true: the letter is a percentile
within your league; Growth is priced at today's values and is therefore hindsight
by construction; and the two-season half-life is a chosen prior, not a measured
one.

## Persistence

New persisted signals: per-season all-play win %, `luck`, `young_core_share`,
`roster_value_share`, `asset_share_delta`, `asset_share_delta_recent`.

**Placement matters and v1 got it half wrong.** `grader.py`'s incremental path
reuses five fields and *deliberately omits* `outlook_signals`, with the comment
"stays freshly computed (current roster value/youth)". So:

- `outcome_signals` (**frozen rollup**) — all-play per season, `luck`,
  `playoff_success`. They describe seasons that are over.
- `outlook_signals` (**value layer, always recomputed**) — `young_core_share`,
  `roster_value_share`, `draft_capital`, and both Growth signals. Freezing these
  would stall roster value through the entire offseason, which is precisely when
  dynasty value moves most.

**`SCHEMA_VERSION` bump required.** A pre-feature entry lacks the new keys and
`_raw` reads a missing key as `0.0`, which for `expected_wins` means "lost every
all-play matchup in every week" — a catastrophic wrong value, not an absent one.
The bump forces a full rebuild and closes it. Run the `chain-cache-field` skill
for the rubric and the test quartet, and update
`test_grader_reuse_equivalence.py`'s enumerated frozen-field list.

**Keep the retired signals in the persisted dicts.** `compute_gm_ratings` only
reads keys named in `signal_weights`, so extra keys cost nothing — and
`championships` / `made_playoffs` are read by three non-scoring consumers:
`grader.py::_playoff_rate_by_uid` (feeds `strength_score` → `classify_window` →
`StandingRow.window`), and `gm_rating_blurb.py` twice. Dropping them from the
dict would silently tell a three-time champion's blurb writer he has no titles.

## Snapshots

`RatingSnapshotStore` carries no model stamp. After deploy the first refresh
writes a new-meaning rating under a new week key and `load_prev_ratings` diffs it
against an old-meaning one, producing a large phantom trend that can persist for
months (the offseason week key barely moves). Deleting `ratings_*.json` as a
deploy step is insufficient — the R2 backup tars the cache volume, so a restore
reintroduces them.

**Stamp the model on each week key and have `latest_before` skip keys from a
different model.** The trend degrades to "—" until two new-model weeks exist,
which is the honest reading and survives a restore.

`season_ratings` currently feeds `_backfill_yoy` → `yoy_rating_delta` →
`trajectory_score` → `classify_window`. With recency decay, a "2023 rating" is
decayed toward the latest played season regardless of scope and becomes *less*
meaningful, not more. Either scope the decay anchor per season-rating or drop
`season_ratings` from the trajectory path.

## Blurb pipeline

`BLURB_PROMPT_VERSION` bump, plus the pillar keys change from
`{Results, Skill, Outlook}` to `{Results, Growth, Assets}` in four places:
`llm/gm_rating_blurb_writer.py::_PILLAR_KEYS`, the persona prompt (which names
the three keys and references "close on Outlook or Skill"),
`engine/gm_rating_blurb.py`'s `PILLAR_LABELS` / `SIGNAL_LABELS` / `_PILLAR_ORDER`,
and `OverviewTab`. `SIGNAL_LABELS` needs entries for every new signal or the raw
snake_case key reaches the LLM and then the page. Redraft emits `{Results}` only.

## Validation

All of it runs offline from the local cache — see the
`franchise-rating-calibration` skill.

1. **Scale calibration** — `SCALE` is derived from the fixture league's measured
   composite sd, and `SCALE × sd_multiple == band delta` for every band. Letters
   span at least five distinct values across twelve owners, and no owner falls
   below D−.
2. **Contribution additivity** — `Σ signal.contribution == pillar.contribution`
   and `BASE + Σ pillar.contribution == rating`, the invariant `OverviewTab`
   reconciles against on screen.
3. **Residualization** — `corr(luck, expected_wins) ≈ 0` on the fixture.
4. **Growth is zero-sum** *(v2.1)* — shares sum to 1.0 and `asset_share_delta`
   sums to 0 across owners, within tolerance.
5. **Timeline round-trip** *(v2.1)* — replaying chain-origin rosters forward
   through every trade, add, drop and draft pick reproduces today's rosters
   exactly. Cannot run against a local cache; see the scoping probe.
6. **Pure unit tests** — `all_play_win_pct`, `playoff_success`, `luck`,
   `young_core_share`, `asset_share_delta`, the decay clamp, and the
   minimum-played-weeks anchor rule.
7. **Format trees** — every registered tree sums to 1.0; redraft produces a
   Results-only rating; keeper's Assets tree sums without `young_core_share`.

## Sequencing

Steps 1–3 each ship green on `main` with **no grade change**.

1. **Engine, inert.** `all_play_win_pct`, `playoff_success`, `luck`,
   `young_core_share`, `roster_value_share`. Nothing consumes them.
2. **Persist, additive.** Emit the new keys while keeping the retired ones.
   `SCHEMA_VERSION` bump. Update the frozen-field list and the reuse block with
   the placement above.
3. **Scoring, defaults off.** Register the new trees behind a flag; land the
   additivity, residualization and zero-sum guards.
4. **The atomic PR.** New trees + calibrated `SCALE` and bands + hero (blurb out,
   receipt in) + roster-rank columns + `Leaderboard.tsx` redraft detection +
   `OwnersTab` fallback + three tone maps + methodology page + OG cards +
   receipts + snapshot model stamp + `BLURB_PROMPT_VERSION` + persona + labels +
   the `franchise-rating-calibration` skill. Splitting any of it ships a letter
   computed by one model and documented by another.
5. **Post-merge.** Force-refresh every cached league, then run the calibration
   harness against the live league and record the result here.

### v2.1 — Growth

Sequenced after v2 ships and its calibration is recorded.

6. **Ingestion.** `get_adds` on `LeaguePlatform` + `SleeperClient` + Yahoo;
   raw-bundle shape change behind a `schema_version` bump to force re-fetch.
7. **Timeline.** `engine/roster_timeline.py` (player) and pick ownership, with
   the round-trip test running in-process during a refresh or against a
   full-chain fixture.
8. **Scoring.** `asset_share_delta` / `asset_share_delta_recent`; tree moves to
   0.50 / 0.30 / 0.20, taking Growth's weight out of Assets; recalibrate `SCALE`
   and re-record.

**Deployment note:** `web` and `api` are separate Railway services that deploy
independently on one push. Every new field must be nullable on both sides so
either arrival order degrades to an omitted column rather than an `undefined`
render.

## Out of scope

- Any global or cross-league scale. Permanently — it is not what this app is for.
- Per-season Growth history.
- The owner hero's "best finish" cell rendering "—" for an owner with three
  recorded finishes of 9th, 10th and 11th. Separate bug, file separately.
- `engine/gm_signals.outlook_signals` is dead code with no production caller
  (`rating_signals.py` builds the same dict inline) while
  `tests/test_gm_signals.py` still exercises it. Delete it during step 1 or it
  becomes invisible drift.
