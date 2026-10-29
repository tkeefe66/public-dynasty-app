# Sleeper result authority

Sleeper's public REST matchup feed can recalculate `points` from current
player stats while its matchup screen retains an earlier settled result.
The screen uses GraphQL `matchup_legs.points` (or `custom_points`), which
requires authentication. A changed REST total alone does not prove a changed
official winner. Never silently recompute a settled winner from starter sums.

The application client reconciles all completed regular-season weeks against
Sleeper's official roster points for, points against, wins, losses, and ties.
It uses exact decimals, including differences smaller than one point. Median
extra games are included when configured. Verified observations are retained
under `sleeper-results/<league>.json` on the existing persistent cache volume.

When the fresh REST ledger reconciles, it replaces the saved result ledger.
When it disagrees, previously observed totals may be retained only if their
lineup, pairing, and commissioner override are unchanged and the resulting
whole-season ledger reconciles. Current player statistics are preserved;
retained totals carry `score_authority` metadata. This is not a score override
or a season-total residual calculation. A genuine official correction that
reconciles is adopted automatically, including on the next weekly refresh.

Without a reconciling ledger, ingestion explicitly fails with
`score_source_conflict`. Recap collection records a failed source observation;
it must not buy a correction from inconsistent result evidence. Existing
historical complete-season and postseason ingestion contracts are unchanged.
This check does not authenticate to Sleeper's private GraphQL API and does not
claim that season reconciliation can distinguish every possible offsetting
historical change. An ambiguous discrepancy remains withheld.

For incident recovery, seed only previously stored source rows corroborated
by the actual matchup screen, and validate the full ledger against current
official roster records before writing. Preserve the original artifact and
record its identity in the seed metadata. Never change player stats to make
them sum to the settled result. Source repair does not authorize AI calls,
alter spending policies, or approve previously rejected prose.
