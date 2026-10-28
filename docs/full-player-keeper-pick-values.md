# Full-player keeper pick estimates

Current keeper ratings that carry future draft picks use an estimated full-player
round curve, not the rookie-only market table. The full Results/Assets formula
is unchanged. Player-only keeper leagues continue to carry no future pick assets.

## Inputs and method

- Require one complete current-season full-player snake or linear draft with
  every numbered slot exactly once, unique players, known rounds/team count,
  and explicit provider keeper flags (Sleeper uses null for ordinary picks).
- Exclude selections marked as keepers. Price every remaining offensive player
  on the same current public-value scale used by roster assets: KeepTradeCut,
  with the existing FantasyCalc fallback. Preserve the per-player source/value.
- Kicker and team-defense selections contribute explicit zero under the existing
  offensive-assets policy. Unknown positions, IDP, missing offensive prices,
  unobserved rounds, or wholly non-offensive rounds leave the model unavailable.
- Compute each round's mean non-keeper selection value. Apply a weighted
  decreasing isotonic fit (pool adjacent violators, weighted by selection count)
  so sample noise cannot make a later generic pick more valuable than an earlier
  one. Preserve raw means and fitted values in the receipt.
- Apply the curve unchanged to the existing next-three-drafts horizon. Use actual
  current traded-pick ownership, with the ordinary starting entitlements. Do not
  apply rookie early/mid/late tiers, guess draft order, elect future keepers, or
  subtract hypothetical future keeper costs. These are gross unused entitlements.

The estimate is conditional on the latest observed draft structure/pool remaining
representative. It is not a quoted keeper-pick market price or verified future
keeper selection. Current and All ratings using it are always **provisional**,
with the calibration season, price date, exclusions, and projection disclosed.

## Boundaries

An isolated rating support bundle prevents changing existing trade grades.
Historical snapshots cannot use today's prices. Missing Results history still
requires a separately verified exclusion receipt; missing current assets remain
unavailable. Partial owner coverage preserves every roster in league asset
denominators while publishing only identified owners.

The current verification receipt records draft digest, priced selections, round
samples, keeper count, and method version. A binding covers that receipt, current
asset signals, league/season, identity version, and owner mapping. Stale evidence
fails closed; normal refresh rebuilds the model and binding.

## Validation and release plan

1. Exercise missing/duplicate slots, missing prices, keeper exclusions, provider
   null flags, round smoothing, source binding, and provisional scope tests.
2. Replay public target-league drafts and retain input/curve audits outside git.
3. Run API/engine/web suites, lint, TypeScript check, and independent review.
4. Deploy API and Web at the exact tested commit; run free data refreshes.
5. Reconcile Results, exclude unresolved history, publish source-bound coverage,
   and prove current/All ratings live. Compare old historical snapshots and owner
   history against the backup, leaving unresolved historical ratings unavailable.
# Dated historical estimates

Historical keeper imports can carry a replayable `pick_valuation` receipt. It
contains the completed season draft, keeper flags, player positions, and a
single provider-dated player board. The board must precede the independently
verified season cutoff by one to seven days. Roster values and pick calibration
must use that same board and scale. Missing offensive draft prices block the
estimate; they are not silently assigned a replacement floor.

The existing observed-round model excludes keeper selections, pools adjacent
round averages to remove increasing round values, and projects generic round
entitlements across three drafts. Historical offense-only policies may explicitly
exclude individual defenders as well as kickers and team defenses. Dual-eligible
players use their verified offensive eligibility. No future keeper elections are
assumed. Pick ownership must independently reconcile from the complete transfer
ledger at the season cutoff.

The manifest binds the replayed estimate, dated roster values, complete pick
inventory, identity mapping, and Results digest. Existing roster replacement-floor
limits and exhaustive rank/grade sensitivity checks still apply. A modeled asset
snapshot is **provisional**, including when all Results seasons are verified.
Results exclusions remain explicit and independent of missing asset years.
Refreshing must reload the dated manifest and reviewed format evidence; losing or
altering either makes that year unavailable. Current/All inputs remain separate.

The `dynasty-process-offense-v2` policy uses dated DynastyProcess values with the
same explicit defensive exclusions as `stats-guy-offense-v2`. Its source credit
and date are returned with the historical rating scope. Legacy manifests omit
the optional model field when absent so their validation digests remain stable.

### Reviewed historical keeper placeholders

Some older full-player drafts use another player as a keeper-cost placeholder
without setting Sleeper's `is_keeper` flag. Missing prices and retired status are
not evidence of a placeholder. Historical pick receipts can now carry an optional
`reconstruction` proof; receipts without it keep their original shape and digest.

The proof preserves original provider picks and records the reviewed cost rule,
season lineage, both drafts, owner identities, the prior final scored week's
rosters, opening rosters, transactions, and explicit placeholder/keeper mappings.
Replay requires an undrafted carryover with the same owner, no acquisition or
removal before the draft ends, a unique standalone drop within two hours, and a
cost matching the prior round minus one (minimum round one). This is a reviewed
policy for matching evidence, not an inferred universal keeper rule. All undrafted
carryovers must be accounted for, including placeholders that already have prices.
Adjacent proof years must agree on their shared original draft; a prior
reconstructed cost is usable only after that year's proof passes validation.

Normalization changes only a copied valuation input. Original picks and proof
remain in the manifest and participate in its digest and replay. Missing or
contradictory evidence fails closed. Publication must compare proof source records
with public provider responses, revalidate the full asset manifest, back up the
existing snapshot, and verify current/All and unrelated seasons are preserved.
The rating remains provisional and discloses reconstructed keeper exclusions.
