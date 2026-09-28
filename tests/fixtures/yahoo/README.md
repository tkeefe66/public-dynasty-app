# Yahoo response fixtures

Reduced from authorized, read-only Yahoo football API captures on 2026-09-27.
Current-season settings, standings, rosters, draft, and transactions preserve
their real envelope and list structure. A completed prior season supplies a
real trade and playoff/consolation flags.

Private league keys are replaced with synthetic `100000001` / `100000002`
identifiers. Team/manager names use `Example N`; usable GUIDs use synthetic
owner IDs. Yahoo's shared masked-GUID sentinel is retained to reproduce the
identity collision. Private URLs, images, emails, login data, and unused fields
are removed. NFL player IDs and numeric sports data remain public source data.

`roster_points_wk1.json` records the provider's surprising behavior: appending
`/players/stats` beneath the all-team roster collection returns rosters but
silently omits player points. The adapter instead fetches league player stats
in batches of 25, captured as `player_points_wk1_batch*.json`.

`test_yahoo_adapter.py` verifies that starter totals from those separate stat
responses match all ten scoreboard totals. No tokens or original captures belong
in this directory.

`draftresults_missing_player.json` was captured on 2026-09-28 from a completed
2020 draft. Two selections (153 and 154) have round, pick, and team information
but no player key. The full 160-selection collection is retained, with its
league key replaced by synthetic `399.l.100000003`. Missing player information
must not prevent the other 158 selections or the league history from importing.

## Account discovery

`discovery.json` preserves a captured user → numeric games → numeric leagues
envelope. It contains only discovery fields; all league keys and names are
synthetic, and account GUIDs and URLs were removed.
