# Historical keeper evidence

Reconstruct each season independently. Normalize provider team IDs to historical
owner identities and player IDs to a stable cross-season identity before using
`app.services.keeper_evidence.detect_keepers`.

- Explicit keeper markers and affirmative season settings establish format.
- A member's confirmed format can establish a season's format; preserve that
  confirmation in the evidence rather than inventing provider metadata.
- Returning players are candidates, not confirmed keepers. Owners may redraft
  players; false or absent keeper flags do not establish redraft.
- Observed keeper counts do not establish the maximum allowed. Persist the
  configured allowance only when the season's settings establish it.
- Dynasty remains dynasty when it also has retained-player markers.
- Conflicting affirmative evidence leaves format unresolved.

Save reviewed records with `SeasonFormatStore.save(season_league_id, season,
evidence)`. Evidence requires a format, provenance basis, and SHA-256 digest of
the source report. The store is immutable and keyed by historical league ID and
year, so rollover does not move evidence into another season.

Historical refresh applies these records before selecting the rating formula.
Once a snapshot requires reviewed format evidence, losing that record leaves the
rating unavailable. Results coverage requirements survive malformed format
records. Current-season inputs are not changed by this historical store.

Format verification alone never publishes a keeper rating. The selected year
still needs its complete owner population, verified Results, final roster,
dated prices, cutoff, and explicit future-pick policy. Player-only keepers must
not be interpreted as retained future draft picks. The existing keeper formula
values the season-end roster; it does not predict next year's keeper selections.

Older DynastyProcess prices use a separate `dynasty-process-v1` policy and
source attribution. They retain the same freshness, offensive coverage,
unranked-floor disclosure, manifest digest, and rank/grade sensitivity checks.
Do not mix valuation providers within a season or substitute today's prices.

Before publication, replay the evidence offline and compare manifests and
ratings. Back up affected caches, coordinate with refresh operations, and verify
both dashboard and leaderboard against the preview. Preserve unresolved seasons,
historical owner membership, and current-season snapshots.
