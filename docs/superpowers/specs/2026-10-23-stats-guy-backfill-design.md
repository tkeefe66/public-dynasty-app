# Stats Guy historical backfill

User requested implementation after the live 2025 audit, delegated valuation policy,
and requires validation before publication. Implement a reusable offline-first CLI
for completed Sleeper dynasty seasons; do not infer Yahoo support or backfill other
seasons automatically. No paid model calls. No changes to current career ratings.

## Policy (implementation decisions)

Use Stats Guy Fantasy historical non-SF/SF dynasty values with standard TE scoring
only, rejecting unsupported league scoring. One source per snapshot, dated strictly
before the cutoff, maximum seven-day lag. Generic year/round pick prices avoid using
future draft outcomes or speculative early/late assignments.

Keep every roster asset in evidence. QB/RB/WR/TE eligibility determines asset inclusion
(so dual-position players such as Travis Hunter are included). K and DEF are explicitly
excluded from asset value and youth ratios; their historical points remain in Results.
Other unsupported positions block the run.

Unranked eligible players receive a declared zero replacement-value floor, never a
claim that the source priced them at zero. Require a complete dated board and at
least 98% player coverage league-wide, 90% per team, and at most two unranked players
per team. Sensitivity tests enumerate all combinations of each unranked player's
zero floor and the lowest positive value at their eligible position on the same board. Publication is
blocked if any team's overall rank or grade changes. Retain excluded/unranked IDs,
coverage, policy version, source dates and raw-response hashes in the manifest.

## Reconstruction

Collect immutable JSON receipts into a separate work directory. Cache GET/POST
responses keyed by method, URL and body, replay offline, never silently overwrite.
Surface timeout, authentication, rate-limit and malformed response failures.

Use known league chain IDs from ChainCache. Fetch complete historical league metadata,
all matchup weeks, rosters, brackets, transactions (weeks 0–18), and current player
birthdates/eligibility. Compute final played week from real two-team matchups and
cross-check provider last_scored_leg. Verify cutoff against completed NFL schedule.
Require all owners and consistent provider-to-canonical identity across the chain;
fail for membership changes rather than guessing. Reconcile full final-week roster
ownership with the old roster endpoint by reversing all post-cutoff completed moves.
Reconstruct future picks from original ownership plus all completed chain transfers
through cutoff; validate every previous owner and compare with dated-season endpoint.
Missing or ambiguous evidence blocks a preview.

Rebuild bounded results through the existing season-rating builder from raw supporting
data. Match selected-season records/points to provider records and all older W/L/T.
Disclose older aggregate point differences without changing weekly scores. Reject
incomplete brackets/results and reconcile brackets with played pairings/scores.
Preview uses the existing live_ratings and leaderboard/dashboard
resolvers, preserving rating weights and historical eligibility.

## Release boundary

CLI prepare writes an evidence-backed manifest and a private ranked preview only.
Validation must pass before the existing explicit manifest import is used. Import
continues to reject replacement manifests. Versioned policy is schema-validated on
read and its source/policy notice is exposed in the selected-year UI. A manifest
digest binds the preview's asset/policy inputs; a Results-input digest prevents
later refreshes from substituting different outcomes without revalidation.
Provider-dated estimates are accepted with attribution and an explicit limitation:
independent absence-of-hindsight provenance has not been established.

Initially validate the audited 2025 season. Produce owner rankings, values, grades,
coverage, sensitivity results and provenance for review. Deployment/import is a
separate final action after validation; do not publish an unstable preview.
