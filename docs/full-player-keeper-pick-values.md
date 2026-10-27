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
