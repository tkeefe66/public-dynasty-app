# Historical franchise ratings

The year selector evaluates career results through that fantasy season and
assets at its cutoff. All retains the current career calculation. Current
season inputs are rebuilt during the normal free refresh. Historical redraft
ratings use Results only. Dynasty and keeper require verified historical asset
evidence; missing evidence displays **Historical data unavailable**.

No historical prose is generated. Current weekly rank changes are not applied
to historical ratings. Roster rank, competitive window, and draft capital use
the same dated inputs as the rating. Owner profile pages remain current career
profiles; the ratings leaderboard contains the selected year's signal receipt.

## Verified asset imports

The application does not automatically trust third-party archives or treat a
past league's current roster endpoint as its season-end roster. An operator
must verify a complete season-end manifest against original evidence before
importing it. This path makes no network or paid-provider calls.

Run from `api/`, using environment/config for the chain ID and paths:

```sh
python -m app.services.historical_rating_assets --input "$RATING_MANIFEST" --cache-dir "$RATING_CACHE_DIR" --league-id "$RATING_CHAIN_ID"
```

This validates without writing. Add `--apply` to persist the verified manifest,
then run a free league data refresh. A different existing manifest is never
silently overwritten: archive and review the prior evidence before correction.

The JSON schema is `HistoricalRatingAssets` in
`api/app/services/historical_rating_assets.py`. Required evidence:

- `version: 1`, fantasy `season`, `season_league_id`, `format`, exact canonical
  `owners`, and `identity_version` matching the chain's reviewed owner mapping.
- `as_of` at the end of the league's final played week and `through_week`
  matching the provider's final played matchup week. Refresh independently
  fetches and caches completed NFL schedule evidence for existing imports.
  The cutoff is normalized to 00:00 UTC the day after the final game's UTC
  kickoff date. The manifest must match it exactly. January remains part of
  the preceding fantasy season. Provider timeout, rate-limit, malformed, or
  incomplete schedule evidence leaves the historical rating unavailable.
- `prices_as_of` no later than that cutoff, within seven days. Use one
  consistent format and price source across players and picks.
- `verified_by`, `verified_at`, and nonempty `roster_source`, `picks_source`,
  and `prices_source` identifying the reviewed evidence. These are operator
  attestations, not an automated claim that external sources were verified.
- Complete `players`: `player_id`, canonical `owner_id`, dated `value`, and
  `birth_date`. Include reserves/taxi; explicit zero values require evidence,
  and an omitted player is not an implicit zero. Ages are computed at cutoff.
- Complete `picks`: future `season`, `round`, `original_owner_id`, actual
  `owner_id` at cutoff, and dated `value`. The inventory must contain exactly
  one pick per original owner, round, and year in the attested `draft_rounds`
  and `pick_horizon` (up to three years). Zero rounds explicitly attests that
  the league had no future draft assets; it is not a fetch-failure fallback.

Imports are stored separately under `historical-rating-assets/`, keyed by a
hash of the historical season league ID, so a chain rollover retains them.
Their original facts and provenance are retained in
the computed season snapshot. Changed identity mappings or mismatched season,
format, membership, or final week make an import unavailable until reviewed.

## Keeper evidence

The dated `stats-guy-v1` valuation policy accepts reviewed keeper manifests as
well as dynasty manifests, with the same coverage, sensitivity, and digest
checks. It values the complete roster at the season cutoff; it does not infer
which players will be selected as next year's keepers. Prices are dated dynasty
market estimates, consistent with the app's roster asset signal.

For Yahoo, fetch the explicit final-week roster resource for **every** team.
Played-matchup rows alone can omit eliminated teams. Reconcile played rosters
and completed transaction ownership, including bench and IR, before attesting
the snapshot. Keeper player markers do not prove future-pick ownership.
Yahoo's empty adapter pick list is not evidence that the league has no picks:
zero draft rounds requires an explicit league-rule attestation. Retain that
attestation with the private source evidence. The automatic Sleeper collector
still does not collect Yahoo keeper evidence.

## Cache compatibility

The final-week cutoff accepts completed NFL games and provider-confirmed
`STATUS_CANCELED` games in the terminal `post` state. A canceled game's scheduled
kickoff still bounds the week; it does not supply a fantasy score or outcome.
Postponed, suspended, ongoing, and otherwise unverified games continue to block
the cutoff. The original schedule response is retained for replay.

`season_rating_inputs` is additive and versioned. An older cache continues to
serve All and season records, but selected-year ratings are unavailable until
refresh builds verified inputs. No schema-wide invalidation is needed because
missing inputs are never interpreted as zeros or substituted with current
ratings. Every refresh rebuilds these inputs, including incremental refreshes,
so a newly imported manifest takes effect without a paid generation request.
