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
