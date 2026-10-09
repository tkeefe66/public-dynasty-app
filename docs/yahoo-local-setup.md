# Yahoo local import

Yahoo Fantasy Sports Read was approved and verified with a live PKCE exchange
on September 27, 2026. The approved application is a Public Client; it does not
need an invented client secret. The local OAuth helper uses state, S256 PKCE,
and a registered callback. Tokens stay in a private temporary file.

The adapter now reads football league settings, current and weekly rosters,
league-scored player totals, standings, playoffs, transactions, and draft picks.
It uses the existing keeper/redraft engine and canonical Sleeper player IDs.

Configurable cumulative weekly scoring bonuses are supported for verified
offense, kicking, and team-defense categories. See [Yahoo scoring](yahoo-scoring.md)
for the complete mapping table, source evidence, unsupported categories, and
the admin recovery action for a data refresh stopped before this support shipped.

## Run an import

Install the repository's Python and API dependencies first. Set the public
client ID and exact registered callback in your local environment, then run:

```sh
python3 scripts/yahoo_dev_token.py
```

Complete Yahoo consent and paste the full callback into the hidden prompt.
Use the token-file path and league key printed by that helper:

```sh
export YAHOO_DEV_TOKEN_FILE=/path/printed/by/the/helper.json
export YAHOO_DEV_LEAGUE_KEY=your-numeric-game-key.l.your-league-id
python3 scripts/yahoo_import.py
```

The importer defaults to the current season. `--seasons 2` includes the previous
season; `--all-history` follows all renewal links. Output is written to a new
private temporary directory and read back for verification. AI prose is disabled.
This command does not write to production, send messages, or change Yahoo rosters.

Access tokens expire after about one hour. Re-run the OAuth helper when prompted;
the development tools intentionally do not retain refresh tokens.

## Validation and coverage

A real, user-selected ten-team keeper league was imported for 2025 and 2026:

- All 187 current rostered players mapped to canonical IDs.
- Both completed 2026 weeks reconciled to Yahoo's scoreboard with zero difference.
- The 2026 draft contained 180 picks and 50 successful roster transactions.
- The two-season run contained 360 picks, one historical trade, and lineup metrics
  for all 20 team-season records. No player IDs were left unresolved.
- The completed season produced ten `v2_keeper` ratings. Current-season teams are
  unrated until completed-season evidence can be linked to their owners.
- The saved 2025 records show one champion, one runner-up, four playoff teams,
  and three title-path round wins. All 217 unique historical drop dates survived
  normalization; third-place games are excluded from title-path production.

Yahoo masks manager GUIDs with a shared placeholder. The adapter keeps those
teams distinct by season; it does **not** assume matching team numbers or names
prove the same owner across years. The resulting warning stays on the imported
cache. Cross-season owner linking needs a separately verified mapping.

The DynastyProcess ID map lags newer players. A fallback accepts only a unique
normalized name and eligible position in Sleeper's public player universe;
ambiguous names require matching NFL team evidence. Unknown starters stop grading,
and a trade with an unmapped asset is excluded in full with a coverage warning.
Missing roster resources also stop grading. Multi-week championships are explicitly
unsupported until their aggregate-round semantics have been validated.

Recorded tests preserve Yahoo's real numeric wrappers and fragmented objects.
Their league keys, team names, and manager identities are synthetic. Raw captures
and credentials are excluded from version control.

## Production status

The application now implements account-scoped Yahoo connection, encrypted
refresh-token storage, league discovery and Add/Open actions on Add a league.
Google remains the app login; Yahoo is linked to that signed-in account. Manual
and scheduled refresh resolve credentials from verified league members. A
server-wide developer token cannot authorize another user's request.

Before deploying, configure Railway **API** with `TRADE_GRADER_YAHOO_CLIENT_ID`,
`TRADE_GRADER_YAHOO_REDIRECT_URI` (the exact registered HTTPS Web callback at
`/api/auth/callback/yahoo`), and `TRADE_GRADER_YAHOO_TOKEN_KEY` (URL-safe base64 of
32 cryptographically random bytes). Public Clients need no secret; confidential
registrations may also set `TRADE_GRADER_YAHOO_CLIENT_SECRET`. **Web** requires
its existing `AUTH_URL` or `CANONICAL_HOST` to define the trusted redirect origin.
No Yahoo credentials are placed in `NEXT_PUBLIC_*` variables.

Migration `0008_yahoo_connections` adds separate connection, pending OAuth state,
and verified league-grant tables. Existing user/membership records are preserved.
Ciphertext envelopes carry their AAD version and are bound to account and purpose.
Keep the encryption key separately from database backups; replacing it requires
reconnecting all Yahoo accounts. Backup/restore includes these tables.

OAuth uses single-use 10-minute state, a browser-bound HttpOnly cookie, and S256
PKCE. Token rotations are persisted before subsequent API work; PostgreSQL user
row locks serialize refresh and disconnect across replicas. Private league access
is revalidated at least every five minutes; revoked or removed membership fails
closed. Yahoo private pages are not exposed through anonymous social cards or the
Sleeper admin/allowlist bridge. Explicit recap sharing remains a member action.

Reconnect clears verified grants, then discovery revalidates access under the new
connection. Disconnect removes stored credentials and grants while retaining saved
league memberships and analysis. It stops future access through that connection;
an already-running import may finish. Reconnect from Add a league to open retained
leagues again. For Yahoo-side permission removal use Yahoo's connected-app controls.

Local browser verification uses synthetic account/league data. A live hosted OAuth
and import check is still required after the paired API/Web release.

Provider references: [Yahoo sign-in and PKCE](https://developer.yahoo.com/sign-in-with-yahoo/)
and [Yahoo Fantasy Sports API](https://sports.yahoo.com/developer/docs/).
