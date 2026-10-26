# Historical dynasty backfill

The backfill prepares private, reproducible previews. It makes free public API
requests to Sleeper, ESPN, and [Stats Guy Fantasy](https://statsguyfantasy.com/developers/docs).
It never calls an AI model, changes league settings, writes the live chain cache,
or publishes automatically. Keep private league evidence in the gitignored
`.historical-backfill/` directory or another private location.

## Supported inputs

Results validation supports completed Sleeper seasons with one-week rounds,
two-week finals, or two-week rounds throughout the playoffs. Every leg must have
reciprocal opponents and finite scores; advancement is checked against the sum
of all legs, including low-score advancement in the toilet bowl. League-median
games add a win, loss, or tie to each regular-season record without duplicating
points for or against. Every weekly population must be complete.

Owner mappings are checked against each season's canonical identities, allowing
verified ownership changes between seasons. The ten-team, four-playoff-team
toilet format may leave its middle two seeds idle: the top four and bottom four
must be the bracket participants, and all postseason weeks must explicitly show
no matchup for each idle team. Other missing participants and unsupported bracket
shapes remain blocked.

Automatic asset preparation still requires a dynasty target, standard TE
valuation, and supported offensive-player valuation. The programmatic
`collect(..., results_only=True)` mode verifies results for keeper/redraft targets
without claiming their assets are verified or emitting an asset manifest.
Keeper draft rounds cannot be valued using dynasty rookie-pick prices. Keeper
assets require separately verified retention rules, pick inventory, compatible
prices, and supported player positions. Individual defensive players and TE
premiums still fail explicitly. Yahoo reconstruction remains a separate workflow.

Use an exported canonical `ChainCacheEntry` as `--chain`; it establishes owner
identities and the expected chain. Actual standings, scores, brackets, roster
ownership, and pick transfers are fetched and reconciled against provider data.
Results include seasons through the selected year, matching the site's franchise
rating model. Current owner display names are labels, not historical evidence.

## Valuation policy: stats-guy-v1

- Values come from one Stats Guy Fantasy board for 1QB or superflex, strictly
  before the cutoff and no more than seven days old. Metadata birthdates establish
  age at cutoff; current provider age is never used.
- QB/RB/WR/TE eligibility includes offensive dual-position players. K/DEF remain
  in evidence and game results but are excluded from asset value and youth.
- An absent offensive player receives a disclosed **zero replacement floor**, not
  a claimed provider price. Require 98% league coverage and 90% per-team coverage,
  no more than two missing players per team and eight leaguewide.
- Before publication, test every combination of missing values at zero and the
  lowest positive board price for that position. All ranks and letter grades
  must stay unchanged. This is a bounded policy sensitivity test, not proof of
  a missing player's true value or stability beyond those bounds.
- Every future pick for the next three years uses the same source/date's generic
  year/round price. No hindsight about final pick slots and no mixed source scales.
- These are provider-dated historical estimates, not independently proven
  contemporaneous snapshots. Attribution and coverage appear beside ratings;
  differences from current-source rankings are not pure franchise progress.

The 90% team threshold allows two unranked players on a 22-player offensive
roster; the initially proposed 95% threshold did not. The leaguewide threshold
and exhaustive rank/grade stability gate remain mandatory.

## Prepare and replay

Set `CHAIN_EXPORT`, `SEASON`, and `BACKFILL_DIR` to the private export, season, and
output root for the requested league. Identifiers belong in operator config,
never committed scripts.

```sh
PYTHONPATH=api:src .venv/bin/python -m app.services.historical_backfill_run \
  --chain "$CHAIN_EXPORT" --season "$SEASON" \
  --evidence-dir "$BACKFILL_DIR/receipts" --output "$BACKFILL_DIR/validated"

PYTHONPATH=api:src .venv/bin/python -m app.services.historical_backfill_run \
  --chain "$CHAIN_EXPORT" --season "$SEASON" \
  --evidence-dir "$BACKFILL_DIR/receipts" --output "$BACKFILL_DIR/replay" --offline
```

Receipts bind method, URL, request body, and response hash. Existing receipts are
reused; corrupted evidence, HTTP errors, rate limits, and timeouts fail explicitly.
Resume after a reported cooldown to reuse successful requests. To intentionally
refresh provider evidence, use a new receipt directory. Retain the original.

`preview.json` includes all owner ratings/pillars, source coverage, exclusions,
unranked bounds, every sensitivity scenario, source receipt hashes, and any older
season aggregate-points discrepancies. The selected season must reconcile weekly
scores to provider W/L/T and points exactly (within one cent); older W/L/T must
also agree. Older aggregate point discrepancies remain disclosed: weekly scores
drive all-play, and provider records drive W/L. No game is silently adjusted.
Both playoff brackets must cover their full populations, establish complete
placement/title paths, and match the actual played pairings and score direction
(including low-score advancement in a toilet bowl).

Only a passing run emits `manifest.json`. Existing different manifests cannot be
overwritten; a blocked preview cannot replace a validated output. The manifest
binds the asset/policy inputs to the successful sensitivity run. A separate
Results-input digest prevents refresh from substituting different outcomes
without revalidation. Replaying on a later calendar date changes `verified_at`;
use a new output directory for that new verification.

## Review and publish separately

Review the full private preview and its limitations. Deploy the code before
importing its schema. Validate the exact manifest with the existing import CLI:

```sh
PYTHONPATH=api:src .venv/bin/python -m app.services.historical_rating_assets \
  --input "$BACKFILL_DIR/validated/manifest.json" \
  --cache-dir "$CACHE_DIR" --league-id "$CHAIN_LEAGUE_ID"
```

The command is dry-run by default. Adding `--apply` persists the reviewed manifest;
it refuses a different existing snapshot. A normal free league refresh then
independently checks the season-end NFL cutoff, owner identity version, season,
final week, format, and validated Results digest before making the rating ready.
Verify dashboard, leaderboard, and owner views against the private preview.
An import alone does not prove that a refresh successfully published the ratings.
