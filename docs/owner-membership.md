# League owner membership

Membership means holding a team in the latest known league season, independent
of app access, login activity, and trading frequency. It is resolved in
`api/app/services/owner_membership.py` from the existing provider-neutral chain
and roster snapshots, with confirmed owner aliases applied first.

The shared `OwnerRef` and trade sides expose `membership_status`
(`current`, `former`, `unverified`) and `last_active_season`. The latest roster
must match the expected team count, have distinct known owners, and refer to one
unambiguous latest-season league before absence can establish departure. Missing,
partial, or ambiguous evidence stays unverified. No provider requests are made
while constructing references. Refreshing league data refreshes the evidence.

The Owners tab defaults to current owners, with unverified owners explicitly
separated and former owners behind an expandable section. Current/career ledgers
and rating lists default to excluding former owners, with an All owners option.
Historical season views retain their participants. Current lists reassign ranks
within the visible population and suppress incomparable all-owner trend changes.
Ratings themselves retain the existing historical calculation and inputs.

Former owner records are not deleted or reassigned: profiles, trades, titles,
drafts, head-to-head records, and bets remain accessible with shared status labels.
Historical selectors still allow former owners, with status in the option label.
Profile career ranking is explicitly all-owner; current highlights exclude known
former owners. This is a read-time projection, requiring no migration, cache
schema bump, paid generation, or historical rebuild.

An old API response without the new fields remains readable during staged
deployments; the new backend explicitly returns unverified when evidence is
missing. Status describes the latest cached league, not independently verified
live provider state or exact departure dates.

## Selected-season participation

Year-specific rankings fail closed. `season_membership` admits owners only with
positive evidence from that year: a roster assignment, a trade, or a played
season record. Confirmed aliases are resolved before comparing identities.
An empty or zero-game placeholder record does not establish participation.

When roster evidence is incomplete, owners without positive evidence appear in
`unverified_season_owners`, separately from standings and rating rows. The UI
labels this group "YEAR participation unverified" and links to their profiles,
without ranks or grades. A complete roster excludes absent owners unless other
positive season evidence establishes participation. The all-time history remains
available regardless of selected-season uncertainty.

Season eligibility is applied before computing relative ratings, trade grades,
and current/season highlights. Snapshot roster ranks are rebased over eligible
owners. Missing membership cannot inflate a rank denominator or change another
owner's grade. This does not alter the owner's current/former league status.

## Trades, scoring, drafts, and bets audit

- Trade history retains every participant. Cards, side panels, the detail
  headline context, and desktop/mobile winner summaries identify former owners.
- Scoring franchises come from that league's provider roster snapshot, not the
  historical owner directory. Former owners do not create extra franchises;
  unclaimed teams remain unclaimed. Player points remain full-season totals.
- Draft boards retain the owners who made that season's picks, with membership
  labels on owner and pick views. Departure never removes a pick or its results.
- Bets retain both sides, settled results, and outstanding money, with labels
  on the ledger, summary, and recording selectors. Bets have their own season
  filter; navigating from an older dashboard year must not narrow the available
  owner directory. The Owners tab likewise always loads the career directory.
  Confirmed aliases merge money totals under one owner; individual bets retain
  their original participant IDs so winner display and settlement still agree.
- Empty/zero-game season records do not establish a last-played year or departure.

Regression coverage exercises dynasty, keeper, and redraft projections, plus
desktop/mobile draft and trade presentations. These are read-time changes;
historical cache data and recorded bets are not rewritten.
