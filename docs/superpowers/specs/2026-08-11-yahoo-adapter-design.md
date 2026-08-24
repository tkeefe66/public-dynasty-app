# Yahoo adapter (redraft / keeper) — design

**Date:** 2026-08-11
**Status:** superseded in part. Ingestion Tasks 1–5 built and merged 2026-08-11
(`767196b`); Tasks 6–9 blocked on Yahoo Fantasy API access. The implementation
plan is `docs/superpowers/plans/2026-08-11-yahoo-ingestion-protocol.md`.
**Supersedes:** the MFL adapter sketched in the redraft spec's appendix.

> **Two claims below are wrong.** They were disproved while building, and the
> plan records the evidence.
>
> 1. **"Yahoo access tokens expire after 6 minutes" is false.** Yahoo's token
>    response advertises `expires_in: 3600` — one hour. Confirmed three
>    independent ways. Nothing should be designed around a 6-minute ceiling.
> 2. **"`derive_capabilities` should describe a Yahoo league unchanged" was
>    optimistic.** It could not: `League.league_type` was a raw Sleeper
>    `settings.type` int on the supposedly platform-neutral model. The spec's
>    own instruction — fix the capability model rather than special-case —
>    was followed; `League.format` replaced it.
>
> A third thing the spec could not have known: **Fantasy Sports is a restricted
> API.** Registering an app is not enough; it needs a separate access
> application at `sports.yahoo.com/developer/access`. That, not the auth
> surface, is what actually blocks the project today.

## Why Yahoo, and why now rather than MFL

The earlier platform survey ranked Yahoo 4th of 5 — but it scored candidates on
*dynasty* fit, and Yahoo has no real future-pick trading. That ranking answered
the wrong question.

Yahoo's strength is redraft and keeper, which is exactly what the capability
work just taught this app to handle honestly (`engine/capabilities.py`,
`redraft_led`, `keeper_led`). Against that target Yahoo is the strongest
candidate available: by far the largest redraft/keeper audience, and an
official, documented, still-maintained OAuth2 API — versus MFL's dynasty-heavy
niche.

## The central problem: auth, not data mapping

**Yahoo access tokens expire after 6 minutes.** Refresh tokens are long-lived
but are invalidated whenever the user revokes access in their Yahoo account
settings.

Everything about this app's ingestion assumes Sleeper's model: a public,
unauthenticated, read-only API that any process can call at any time for any
league. Yahoo breaks that assumption in a way that reaches the scheduler:

- `api/app/services/refresh_service.py` periodically refreshes **every cached
  league** with no user present. For a Yahoo league it would need a valid token
  minted on that user's behalf, minutes old.
- So the app must **store per-user Yahoo refresh tokens** and mint access tokens
  during background work. That is a materially different security posture from
  today, where the only secrets are the app's own.
- When a user revokes access, that league silently stops refreshing. It needs a
  real state — *stale, reconnect required* — surfaced in the UI, not a silent
  failure or a retry loop.

**Design consequence:** the auth work is the project. The data mapping below is
the easy half, and any estimate that leads with "map the endpoints" is wrong.

### Auth requirements

- Refresh tokens encrypted at rest, not stored plaintext in Postgres alongside
  identity rows. New key management the app does not have today.
- A `yahoo_connection` record per user: refresh token, scopes, granted-at,
  last-successful-refresh, revoked flag.
- The scheduler must degrade per-connection: one revoked user must not stall the
  refresh loop for everyone.
- Token minting must be shared by the manual `/refresh` path and the scheduler,
  the same way `refresh_service.refresh_league` is the one refresh path today.

## Data mapping — the easy half

The domain models are already platform-neutral (`models/league.py`:
`League`/`Roster`/`Matchup`/`DraftPick`/`MatchupResult`). The work is normalizing
the places raw Sleeper dicts reach the engine:

| Seam | Sleeper today | Yahoo |
|---|---|---|
| `engine/trade_history.py` | raw tx dicts (`adds`/`drops`/`draft_picks`/`roster_ids`/`leg`) | `transactions;type=trade` collection |
| `engine/playoff_phase.py` | `winners_bracket` / `losers_bracket` | playoff bracket resource |
| `engine/draft_signals.py` | draft rows (`draft_slot`, `draft_order`) | `draftresults` collection |
| `services/refresh_delta.py` | Sleeper `transaction_id` | Yahoo `transaction_key` |
| `SleeperClient.walk_league_history` | `previous_league_id` chaining | `renew`/`past_leagues` on the league resource |

**Player identity is already solved.** `engine/injury_data.py` downloads
DynastyProcess's `db_playerids.csv`, whose columns include `yahoo_id` and
`sleeper_id`. Map Yahoo → `sleeper_id` at the adapter boundary and keep Sleeper
ID as the internal canonical key; KTC, FantasyCalc, nflverse, the chain cache and
lineage all stay untouched.

**Values need no work.** A Yahoo league is redraft or keeper, so it already
routes to FantasyCalc redraft values or the dynasty table via
`is_redraft_chain` / `capabilities`.

## Capability derivation

`derive_capabilities` is deliberately evidence-based rather than
Sleeper-type-based, so it should describe a Yahoo league unchanged: `format`
from the league's keeper settings, `future_picks` from whether any trade carried
a pick, `multiyear_history` from chain length. **If it needs a Yahoo-specific
branch, that is a signal the capability model was drawn wrong** — fix it there,
not with a special case.

## Scope boundary

In: one `YahooAdapter` behind a normalized ingestion protocol, the auth surface
above, ID mapping, and `SleeperClient` refactored to the same protocol so there
are two implementations of one interface rather than one plus a special case.

Out: dynasty support on Yahoo (it cannot trade future picks — see the redraft
spec's platform appendix); writes of any kind; other platforms.

## Honest sizing

Extra-large, and the largest single item on the follow-on list. The adapter
protocol plus five seams is comparable to the entire redraft project. The auth
surface — encrypted token storage, background minting, revocation states, a
reconnect flow — is its own project on top, and touches security-sensitive
ground the app has so far avoided by only ever reading public data.

**Recommend `adversarial-security-audit` before shipping any of the auth half.**
Storing third-party OAuth refresh tokens is the first genuinely
credential-holding thing this app would do.

Sources: [Yahoo OAuth2 guide](https://developer.yahoo.com/oauth2/guide/) ·
[Authorization Code Flow](https://developer.yahoo.com/oauth2/guide/flows_authcode/) ·
[Yahoo Fantasy Sports API](https://developer.yahoo.com/fantasysports/guide/)
