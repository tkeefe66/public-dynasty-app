# League Capabilities — honest degradation for non-dynasty leagues

**Date:** 2026-08-11
**Branch:** `feat/league-capabilities`
**Status:** design approved; scope narrowed to Sleeper redraft

## Scope narrowed 2026-08-11

**Building now: Sleeper redraft only.** Other platforms are dropped from the near-term
plan; the platform research survives in the appendix for whenever it is picked back up.

Two consequences of narrowing, decided rather than asked:

- **The capability model is still built in full.** It cannot be avoided — deriving
  `format` from `League.league_type` means handling all three values regardless. The
  narrowing removes the adapter work, not the capability seam.
- **Keeper leagues come along for the ride, scored as dynasty.** Unfiltering
  `me.py:68` admits type 1 as well as type 0, and building a "dynasty + redraft but
  not keeper" filter would be more work than letting keeper in. Keeper leagues have
  future picks and roster continuity, so `results_led` is a defensible fit for them.
  The `keeper_led` tree (dropping `youth` from Outlook) becomes a small follow-on
  refinement, not part of this build.

If keeper should instead stay hidden until it has its own tree, say so — it is a
one-line change to the discovery filter.

## Goal

Let people whose league is not a Sleeper dynasty league use the product — without
the product lying to them.

Today `api/app/routes/me.py:68` filters league discovery to `league_type == 2`.
Everything behind that line already ingests a keeper or redraft league fine. What
it does not do is *mean* anything: a redraft league has no future draft picks, so
the Outlook pillar (`roster_value` + `youth` + `draft_capital`) is noise fed
straight into the headline Franchise letter.

This spec introduces a capability model that says what a league supports, reweights
Franchise Rating over the supported pillars only, and removes rather than fakes the
UI that has nothing to say.

## Principle: leagues are self-contained

**A league never interacts with another league.** Every number the product shows is
derived from one league chain and is meaningful only inside it. Nothing is pooled,
compared, ranked, or averaged across leagues. (One cross-league surface is intended
eventually — see *Deferred* below — but nothing in this spec builds toward it beyond
two free hooks.)

This is already true today and this spec must not break it. Confirmed: Franchise
Rating z-scores each signal *within* the league (`engine/gm_rating.py`); the
leaderboard is `/api/league/{league_id}/leaderboard` over a single
`ChainCacheEntry`; `ChainCache` and the KTC / standings / rating snapshot stores are
all keyed by `league_id`; side bets are league-gated. The only code that iterates
leagues is `refresh_service.py`, which is operational (keeping caches warm), not
analytical.

Making leagues honest about their format raises the stakes on this. A redraft
league scored under `redraft_led` and a dynasty league scored under `results_led`
are not on a common scale, so pooling them would be actively wrong rather than
merely noisy. Concretely, for this feature:

- Capabilities are derived per chain and stored on that chain's cache entry.
- Weight-tree selection is per league.
- A user in both a dynasty and a redraft league sees two independent ratings. The
  "My Leagues" home lists them; it never compares them.
- No shared frontend state may carry a format or capability across league routes.

### Deferred: a cross-league owner grade

Longer term the intent is to aggregate a user's leagues into a larger owner grade,
**bucketed by league format** — dynasty leagues pooled with dynasty leagues, redraft
with redraft. That is explicitly not this spec, and not soon. It is recorded here
because two properties of this design are what make it possible later, and both are
free now and expensive to retrofit:

1. **`capabilities` is persisted per league.** It is the bucketing key. Without it,
   a future aggregator would have to re-derive each league's format from scratch,
   including the evidence-based booleans it cannot recover after the fact.
2. **The rating carries the name of the weight tree that produced it.** Store
   `model` (`"results_led"` / `"keeper_led"` / `"redraft_led"`) on the rating output
   alongside the number. A number pooled without knowing which tree produced it is
   uninterpretable, and stamping it later means recomputing history.

One property already works in a future aggregator's favor: ratings are league-z-scored
and 1500-centered, so they are *relative to league* by construction. Two owners in
different leagues of the same format are more comparable than their raw stats would
be. That is the seam a cross-league grade would build on.

Nothing else is built for it. No cross-league storage, query, or surface exists in
this spec.

## Scope

**In:** capability derivation, persistence, rating reweighting, redraft trade
values, UI gating, discovery.

**Out:** other platforms. The capability model is deliberately shaped so an MFL or
Fleaflicker league can be described by the same vocabulary, but no adapter work
happens here. That is a separate spec, written once this seam exists and has proven
it can describe a league it did not hardcode.

## Why this ordering

Two facts from the codebase made "capability model first" the cheap path:

- `engine/gm_rating.py:89` — `compute_gm_ratings` already accepts `pillar_weights`
  and `signal_weights` as parameters. Reweighting is a second weight tree, not
  engine surgery.
- `ChainCacheEntry.league_phase` (`api/app/services/chain_cache.py:94`) is an exact
  precedent for a new value-layer field: `field(default_factory=dict)`, empty on
  pre-feature caches, always recomputed at refresh, no `SCHEMA_VERSION` bump.

## Architecture

### New engine module: `engine/capabilities.py`

Pure, no I/O, fully unit-testable — same contract as `engine/playoff_phase.py`.

```python
@dataclass(frozen=True)
class LeagueCapabilities:
    format: str              # "dynasty" | "keeper" | "redraft"
    future_picks: bool       # future draft picks are tradeable assets
    roster_continuity: bool  # rosters carry season to season
    multiyear_history: bool  # league chain length > 1
```

Derived by:

```python
def derive_capabilities(
    league: League,
    chain_length: int,
    observed_pick_assets: bool,
) -> LeagueCapabilities: ...
```

**Derivation is evidence-based, not type-declared.** `League.league_type` seeds
`format`, but the three booleans come from observation:

- `future_picks` — did any graded trade actually carry a draft-pick asset? A
  keeper league with pick trading disabled has none, whatever its type says.
- `multiyear_history` — is the walked chain longer than one season? A brand-new
  dynasty league has no multiyear history either, and should not be scored as
  though it does.
- `roster_continuity` — from `format`; dynasty true, keeper true, redraft false.

Evidence-basing is what makes this portable. The same function will describe an
MFL league later without knowing what MFL is, because it asks about the data, not
the platform.

### Persistence

`ChainCacheEntry.capabilities: dict = field(default_factory=dict)`.

Value layer, not a frozen rollup — always recomputed at refresh, never copied from
the prior entry. Stamped in `grader.py` alongside `league_phase`. Empty dict on
pre-feature caches; every consumer falls back to full-dynasty capabilities so
existing leagues are unaffected until their next refresh.

Run the `chain-cache-field` skill before landing to confirm the no-bump call
against its rubric.

### Rating reweighting

`REDESIGN_PILLAR_WEIGHTS` (`engine/gm_rating.py:44`) gains two trees.
`api/app/services/franchise_redesign.py::live_ratings` selects by capability.

| Tree | Results | Skill | Outlook |
|---|---|---|---|
| `results_led` (dynasty, unchanged) | 0.50 | 0.30 | 0.20 |
| `redraft_led` | 0.625 | 0.375 | — |
| `keeper_led` *(deferred)* | 0.50 | 0.30 | 0.20 |

**This build ships `redraft_led` only.** Keeper leagues score under `results_led`
per the scope note above.

`keeper_led` is deliberately identical to `results_led` at the pillar level — when
it lands it will differ **inside** the Outlook pillar, dropping `youth` (irrelevant
when you carry two or three players) and renormalizing the remaining Outlook signals
to 1.0. Recorded so the follow-on does not have to re-derive it.
- **redraft_led** drops Outlook entirely and renormalizes the two surviving
  pillars, preserving their 0.50 : 0.30 ratio.

Signal-level renormalization within a pillar is the fiddly part and carries its own
tests: dropping a signal must renormalize the survivors, never leave a pillar
summing to less than 1.0 (which would silently depress every owner in the league).

The rating output records **which tree produced it** — `model: "results_led" |
"keeper_led" | "redraft_led"` alongside the number, rank, and breakdown. This is
already half-present as a concept (`"results_led"` is a named key today); the change
is stamping the selected name onto the result rather than leaving it implicit. Cheap
now, and the prerequisite for the deferred cross-league grade above.

**Constraint:** Franchise Rating is league-local today
(`/api/league/{league_id}/leaderboard`, `build_leaderboard` over a single
`ChainCacheEntry`). Ratings computed under different weight trees are not on a
common scale, so nothing in this spec may pool them. The deferred cross-league grade
pools *within* a format bucket, which is why the `model` stamp above is a hard
requirement rather than a nicety.

### Trade values for redraft

KTC is dynasty-valued, so its numbers are wrong for a redraft league. When
`format == "redraft"`, source values from FantasyCalc's redraft set instead.

**Verified 2026-08-11.** `api/fantasycalc.py:42` already passes `isDynasty` as a
request parameter, hardcoded to `"true"`. Flipping it to `"false"` returns
redraft-shaped values on the same endpoint, same response schema, all rows carrying
`sleeperId`. So this is a parameter change behind the existing value map — no new
join, no new parser, no new dependency. Smaller than originally sized.

**Coverage caveat.** The redraft set is thinner than the dynasty set: 200 players vs
474 (12-team, 1QB, PPR). That covers a standard 12-team redraft league (~192 roster
spots), but deep or IDP redraft leagues will have unmatched players. Those resolve to
zero value, matching today's behavior for any unmatched player. Do **not** fall back
to dynasty values for the gap — that reintroduces exactly the wrong numbers this
change exists to remove. Surface the coverage limit rather than papering over it.

Keeper leagues keep dynasty values — a keeper league's carried players genuinely
hold multi-year value.

### UI

`DashboardResp.capabilities` carries the `LeagueCapabilities` fields to the
frontend.

Gating is **absence, not empty state** — the Agate rule. Unsupported sections are
not rendered at all:

- `future_picks == false` → no draft-capital signal rows, no future-pick sections
  in the Outlook tab.
- `format == "redraft"` → no Outlook tab on the owner page; Overview shows two
  pillars.
**One deliberate exception to that list:** `multiyear_history == false` does *not*
remove lineage or became-grade. An in-season flip is a real signal worth showing,
and a single-season chain renders single-hop journeys the engine already handles
correctly. What gates on `multiyear_history` is the *cross-season framing* around
them (season labels, multi-year arcs), not the feature itself.

Discovery (`me.py:68`) stops filtering to type 2 and labels each discovered league
with a format chip so the user knows what they are adding.

### What does not change

The engine's ingestion path, `SleeperClient`, the five metrics, the trade stat
table, standings, side bets, stories. A redraft league ingests through exactly the
code a dynasty league does. This spec only changes what the product *claims* about
what it ingested.

## Testing

- **`derive_capabilities`** — table-driven over `league_type` × chain length ×
  pick-evidence, including the contradictions (a type-2 league with no pick trades;
  a type-1 league with them).
- **Weight trees** — each tree's pillar weights sum to 1.0; each pillar's signal
  weights sum to 1.0 after a signal is dropped.
- **No grade compression** — the failure mode of a renormalization bug is precise:
  if a tree's weights sum to 0.8 instead of 1.0, every composite z is scaled by 0.8
  and the whole league compresses toward 1500, i.e. everyone drifts to C. Ratings
  are z-scored and 1500-centered, so the mean stays put and would not reveal it.
  **Test the spread:** given identical signal z-score inputs, the standard deviation
  of ratings under `redraft_led` must be comparable to that under `results_led`. A
  mean-based assertion would pass while the bug shipped.
- **Cache fallback** — an entry with `capabilities == {}` reads as full dynasty.
- **UI** — a redraft dashboard renders no Outlook tab; `tests/agate-rules.test.ts`
  still passes.

## Open items

None blocking. FantasyCalc redraft sourcing is verified (above), which was the only
unverified assumption on the redraft path.

Deferred follow-ons, in rough order of value: the `keeper_led` weight tree; the
cross-league owner grade bucketed by format; the MFL adapter.

## Appendix: platform research (for the follow-on spec)

Ranked for this product, not by raw audience size:

| # | Platform | Dynasty fit | API |
|---|---|---|---|
| 1 | MFL | full future-pick trading, 20-year histories | official documented JSON, free dev key |
| 2 | Fleaflicker | dynasty + future picks | public documented JSON, no auth for public leagues |
| 3 | Fantrax | large in deep/superflex/IDP dynasty | no open public dev API; partner-gated |
| 4 | Yahoo | keeper, not true dynasty | official OAuth2 |
| 5 | ESPN | **cannot trade future picks** — current-season, pre-draft only | undocumented; expiring `espn_s2`+`SWID` cookies the user must paste |

ESPN is the trap: the largest audience and the least for this product to say.

**Key de-risker.** `engine/injury_data.py:24` already downloads DynastyProcess's
`db_playerids.csv`, whose columns include `mfl_id`, `sleeper_id`, `espn_id`,
`yahoo_id`, `fleaflicker_id`, and `ktc_id`. The cross-platform player crosswalk is
already a dependency of this repo. A future adapter maps foreign IDs to
`sleeper_id` and keeps Sleeper ID as the internal canonical key, leaving KTC,
FantasyCalc, nflverse, the cache, and lineage untouched.

**Adapter boundary, when it comes.** `models/league.py` is already
platform-neutral. The raw-Sleeper-dict leaks that would need normalizing:

- `engine/trade_history.py` — raw transaction dicts (`adds`, `drops`,
  `draft_picks`, `waiver_budget`, `roster_ids`, `leg`)
- `engine/playoff_phase.py::classify_playoff_phases` — raw `winners_bracket` /
  `losers_bracket`
- `engine/draft_signals.py` and `trade_history.py` — raw draft rows (`draft_slot`,
  `draft_order`, `roster_id`)
- `api/app/services/refresh_delta.py` — keyed on Sleeper `transaction_id`
- `SleeperClient.walk_league_history` — assumes `previous_league_id` chaining
