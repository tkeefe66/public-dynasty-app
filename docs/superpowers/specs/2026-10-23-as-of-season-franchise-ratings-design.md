# Franchise ratings as of the selected season

Status: approved behavior; unavailable until verified selected by the user.

## Requested behavior

Selecting a season evaluates the franchise as it stood then, including its
roster and future draft assets. All retains the existing current career rating.
The behavior must be consistent across league formats and rating surfaces.

## Proposed time boundary

Completed seasons use the end of the league's final played week, including its
postseason. An ongoing season uses the latest refresh. These are implementation
assumptions, not separately requested product choices. The response and UI must
expose the effective date. January games belong to their fantasy season, not the
calendar year in which they occurred.

Results include career results through that boundary, with recency decay
anchored to the latest eligible played season at that boundary. Later seasons
must never affect historical results, eligibility, the comparison population,
or grades. Preserve the existing format-specific weighting trees.

## Existing behavior and evidence

- `aggregations.build_dashboard` always calls `_all_time_ratings`.
- `franchise_redesign.live_ratings` accepts but ignores `year`.
- `leaderboard.compute_season_ratings` deliberately returns an empty mapping.
- `rating_signals.compute_rating_signals` combines historical results into one
  outcome dictionary and prices only current holdings.
- `KtcSnapshotStore` captures forward-only dated prices. The inspected local
  archive contains 2026 dates only; production archive coverage has not yet
  been checked. Existing repository documentation records no pre-2026 backfill.
- `roster_asof` and the draft-needs reconstruction explicitly warn that a past
  Sleeper league's roster endpoint can include offseason changes. Final played
  matchup rosters are the existing historical seed.
- Yahoo may expose season-specific team identities. Career continuity still
  requires verified mappings; names are not identity keys.

## Shared implementation

Introduce a versioned, per-season input snapshot during free refresh. Each
snapshot carries the cutoff, provenance, completeness status/reasons, eligible
owners, results signals through the cutoff, historical assets signals, roster
ranks, and historical draft capital. Persist source facts as well as computed
signals so results can be reproduced after a model change.

Use one rating resolver for both dashboard and leaderboard. All delegates to
the unchanged current model. A selected year resolves only its dated inputs.
Do not fall back to today's signals. Scope roster rank, competitive window, and
draft capital to the same snapshot so adjacent columns agree with the rating.
Historical rank trends must not compare against a current weekly snapshot.
Do not reuse current prose as a historical explanation or trigger paid prose
generation as part of this change.

Historical asset reconstruction requires:

1. A complete roster for the selected cutoff, including the provider's reserve
   and taxi semantics where applicable. Missing rosters are not empty teams.
2. Player market values dated on or before that cutoff, using the correct
   valuation format. Unknown players require explicit coverage handling.
3. Age at the cutoff from birth dates, never today's age.
4. Future picks owned at the cutoff, reconstructed from complete dated
   transfers and the applicable season's draft rules. Do not use current
   traded-pick holdings or future rookie outcomes.
5. Pick prices and any strength tiers based on information available then.

Historical data should be loaded through a separate validated import path,
with source/date/checksum metadata. An external archive is not yet validated:
a publicly accessible Community Trade Value sheet advertises historical 1QB
and SF tabs, but complete player, pick, and date coverage remains unverified.
Do not introduce an unverified remote feed into every dashboard request.

Redraft retains its Results-only model. Keeper retains its existing model,
using historical assets only for the signals it actually scores. Historical
identity and league-format evidence must be checked before combining seasons.

## Confirmed missing-data behavior

If verified historical inputs are missing, show Historical data unavailable
with the missing coverage reason. No estimates, today's values, or zero-valued
missing assets. Historical backfill remains unavailable until its provenance
and completeness are verified.

## Validation and release requirements

- Temporal isolation: mutate all later results, rosters, prices, ages, picks,
  and owners; historical ratings remain identical.
- Historical sensitivity: change a verified cutoff roster or pick transfer;
  the appropriate historical asset signals and rating change.
- Boundary coverage: January postseason, current incomplete season, first
  season, departing/new owners, and verified cross-season identity mappings.
- Format coverage: dynasty, keeper, redraft; no model substitution for gaps.
- Missing-data cases: absent/partial/stale/future-dated prices, incomplete
  ownership history, missing rosters, and pre-feature cache entries.
- Cache round-trip, refresh wiring, version invalidation, and read fallback.
- Dashboard, leaderboard, and displayed rating breakdown agree for each scope;
  switching back to All preserves the existing career result.
- Test and lint affected Python and TypeScript code; typecheck/build web;
  inspect the year-switching UI against real cached league data.
- Confirm production archive coverage before claiming historical backfill.
  Deployment is separate and must verify both API and Web at the exact commit.
