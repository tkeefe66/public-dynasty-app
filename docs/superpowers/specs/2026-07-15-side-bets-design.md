# Side Bets — Design

**Date:** 2026-07-15
**Status:** Approved (brainstorm → spec)

## What

A league-scoped ledger for manually recorded side bets between owners (e.g. "Tom
finishes the regular season above Mike for $500"), with full betting history and
per-owner won/lost rollups.

## Requirements (settled in brainstorm)

- **Bet shape:** freeform text description + dollar amount + two sides + season.
  No structured bet types; settlement is manual.
- **Parties:** strictly 1-vs-1 — two owners, one amount, winner takes it.
  Multi-party pots are a possible later extension, not in scope.
- **Permissions:** any signed-in league member can record, edit, and settle
  bets. Audit fields record who did what.
- **Settlement outcomes:** `open` → `settled` (winner named), `push` (tie, no
  money moves), or `void` (mistake/cancelled). Pushed and voided bets stay in
  history but count $0.
- **Backfill:** season and made/settled dates are editable at entry so years of
  historical bets can be recorded accurately.
- **Standalone:** bets never feed Franchise Rating, standings, trade grades,
  stories, or blurbs. Social money ledger only.

## Architecture

Manual, must-survive-forever data → **Postgres** (the identity DB), not the
rebuildable `ChainCache`/file cache. Same seam as `LeagueMembership`:
`league_id` is the opaque Sleeper league id (not a FK), and bet parties are
**Sleeper owner user_ids** — the same key the rest of the app uses for owners
(`/owner/{uid}`, standings, trades). Display names resolve at read time from
the chain-cache owner map, exactly like other league views.

Rollups are computed on read. A league accumulates at most a few hundred bets;
no aggregate tables, no caching layer.

## Data model

New table `side_bets` (`api/app/db/models.py`, Alembic migration `0007`):

| Column | Type | Notes |
|---|---|---|
| `id` | String(36) PK | uuid, matches existing convention |
| `league_id` | String, indexed | opaque Sleeper league id (chain entry-point league) |
| `season` | Integer | editable at entry (backfill) |
| `description` | String | freeform bet terms |
| `amount_cents` | Integer | no float money; UI shows dollars |
| `side_a_owner_id` | String | Sleeper owner user_id |
| `side_b_owner_id` | String | Sleeper owner user_id; must differ from side A |
| `status` | String | `open` \| `settled` \| `push` \| `void` |
| `winner_owner_id` | String, nullable | required and must equal one side when `settled`; null otherwise |
| `made_at` | Date | backdatable |
| `settled_at` | Date, nullable | set when status leaves `open`; backdatable |
| `created_by_user_id` | FK → users, indexed | audit |
| `settled_by_user_id` | FK → users, nullable | audit; set on settle/push/void |
| `created_at` / `updated_at` | DateTime(tz) | existing conventions |

Invariants enforced in the service layer (portable across Postgres/SQLite):
sides differ; `winner_owner_id` consistent with `status`; `amount_cents > 0`.

## API

New route module `api/app/routes/bets.py`, league-gated with the same
dependency the dashboard routes use. Business logic in
`api/app/services/bets.py`; Pydantic shapes in `api/app/models/bets.py`;
queries in `api/app/repositories/bets.py` (dialect-portable, like `events.py`).

- `POST /api/league/{id}/bets` — record a bet.
- `GET /api/league/{id}/bets` — full ledger, newest first. Optional
  `?owner_id=` (bets involving that owner) and `?season=` filters. Each row
  carries resolved owner display names.
- `PATCH /api/league/{id}/bets/{bet_id}` — edit fields while `open`; settle
  (name winner), push, or void. Void replaces delete — history is never
  destroyed. Settled/pushed/voided bets can be reverted to `open` by any
  member (trusted-league model; audit fields show who).
- `GET /api/league/{id}/bets/summary` — per-owner rollup: bets won / lost /
  pushed, dollars won, dollars lost, **net**, and open "at stake" exposure.
  All-time plus per-season breakdown.

Ledger math: winner `+amount`, loser `−amount`; `push`/`void` contribute $0;
`open` bets contribute only to at-stake.

## UI

- **League "Bets" tab** on the dashboard:
  - Leaderboard band: per-owner net won/lost, W-L(-P) record, at-stake.
  - Full ledger table: season filter, status chips, inline
    settle / push / void actions.
  - "Record a bet" modal: two owner dropdowns (from existing owners data),
    amount, description, season, backdatable date.
- **Owner franchise page** (`/owner/{uid}`, Track Record tab): compact career
  side-bet record — net, W-L, biggest win / worst loss — linking to the league
  ledger filtered to that owner. Hidden when the owner has no bets.
- Styling follows the existing token system (`web/app/globals.css`), light +
  dark.

## Error handling

- Validation failures (same owner both sides, winner not a side, non-positive
  amount) → 422 with a specific message.
- Bets endpoints require league membership → 401/403 via existing auth deps.
- Owner-name resolution degrades gracefully: if the chain cache is cold, show
  raw owner ids rather than failing the ledger (bets are DB-backed and must not
  depend on the 409 cold-start contract).

## Testing

- **Service/repository unit tests** (SQLite, like existing repo tests): rollup
  math incl. push/void/open, state-transition rules, validation invariants,
  season filtering.
- **Route tests:** auth gating (anonymous 401, non-member 403), CRUD happy
  paths, settle flow.
- **Frontend unit tests** (vitest): leaderboard/net formatting, ledger row
  states, cents→dollars rendering.
- **Playwright smoke:** record a bet → settle it → leaderboard updates.

## Non-goals

- No effect on Franchise Rating, stories, recaps, or standings.
- No multi-party pots.
- No auto-settlement or structured bet types — though the schema doesn't block
  adding an optional structured type tag later.
- No payment tracking (who has actually paid up) — the ledger records outcomes,
  not collections.
