# Product Telemetry — Design Spec

**Date:** 2026-06-28
**Status:** Approved (design), pending implementation plan
**Branch:** `product-telemetry`

## Goal

Give the app owner first-party product telemetry to answer two questions:

1. **Who's active, and how much** — per-user and per-league engagement (active users over time, which leagues are alive vs dormant).
2. **Where people go** — which sections/routes users visit, surfaced per user and per league.

Explicitly **out of scope** (deferred / not built): conversion funnels, session replay, and a global "top pages" leaderboard. The event data captured will *support* adding a top-pages view later, but it is not part of this work.

## Decisions (from brainstorming)

- **Build, not buy.** Self-hosted in the existing Postgres identity DB + the existing admin UI. Keeps user activity first-party (no third-party data processor for login-gated PII), and per-league is a native column. Trade-off accepted: we build the dashboards.
- **Capture via a client route-change beacon.** The app is Next.js App Router with mostly client-side navigation, so server/middleware logging would miss transitions. A small client component beacons each route change.
- **Three admin views:** Active users (DAU/WAU/MAU), Per-league activity, Per-user drill-down. (No global top-pages view.)

## Dependency

Builds on the **active-days** change (branch `active-days-metric`, committed, not yet merged): activity is recorded server-side in `get_current_user` via `users.touch_activity`. The telemetry `POST /api/events` endpoint authenticates through `get_current_user`, so **a pageview also marks the user active that day** — no duplicate activity logic. **This branch should be cut from / rebased onto main after `active-days-metric` is merged**, so the columns are `active_days` / `last_active_at` and the `touch_activity` helper exists. The spec assumes that post-merge state.

## Architecture

### 1. Data model — `page_events` (Postgres)

New table, new migration (`0006_page_events`):

| column | type | notes |
|---|---|---|
| `id` | String(36) PK (uuid) | matches existing model convention |
| `user_id` | String(36) FK → `users.id` (ondelete CASCADE), indexed | always set (app is login-gated) |
| `league_id` | String, nullable, indexed | extracted from the route when the page is league-scoped; null for non-league pages (`/`, `/admin`, `/login`) |
| `route` | String, indexed | normalized route **template**, e.g. `/league/[id]/owner/[uid]` — low cardinality, for aggregation |
| `path` | String | raw pathname (e.g. `/league/123/owner/abc`) — for the per-user drill-down's readable history |
| `created_at` | DateTime(timezone=True), indexed, server_default now() | event time |

Indexes: `created_at`; composite `(user_id, created_at)`; composite `(league_id, created_at)`. Query strings are **never stored** (dropped before insert).

**Retention:** none initially. Volume is low (login-gated dynasty users, low thousands of events/day worst case). A daily-rollup table or a prune of rows older than ~12 months is a **documented future step**, to be added only if table size warrants it. This limitation is stated, not silently assumed.

### 2. Route normalization — pure function

`api/app/services/route_normalize.py::normalize_route(path: str) -> tuple[str, str | None]`

- Input: raw pathname (no query string).
- Output: `(route_template, league_id | None)`.
- Pure, deterministic, fully unit-tested. Maps known App-Router shapes to templates and extracts the league id segment. Examples:
  - `/` → (`/`, None)
  - `/admin` → (`/admin`, None)
  - `/league/123` → (`/league/[id]`, `123`)
  - `/league/123/owner/abc` → (`/league/[id]/owner/[uid]`, `123`)
  - `/owner/abc` → (`/owner/[uid]`, None)
  - `/gm` → (`/gm`, None)
  - unknown shape → (the path with numeric/id-looking segments masked to `[seg]`, None) so unexpected routes still aggregate without exploding cardinality.
- The exact route table is derived from the actual `web/app` directory structure at implementation time.

### 3. Capture — client beacon → existing proxy

- New client component `web/components/Telemetry.tsx`, mounted once in the root layout (`web/app/layout.tsx`).
- On mount and on every `usePathname()` change, it sends the **raw pathname only** (no query string) to `POST /api/events` via `navigator.sendBeacon` (with a `fetch(..., { keepalive: true })` fallback when `sendBeacon` is unavailable). Payload: `{ "path": "<pathname>" }`.
- The beacon is same-origin, so it flows through the existing Next proxy (`web/app/api/[...path]/route.ts`), which attaches the backend token from the session cookie. **No new auth plumbing.** Anonymous beacons (e.g. on `/login`) get a 401 from the proxy and are harmlessly dropped.
- The component renders nothing.

### 4. Backend — capture endpoint + repository

- **Route:** `POST /api/events` in a new `api/app/routes/events.py` (registered un-guarded like `me.router`; self-authenticates via `get_current_user`). Rate-limited via the existing `limiter` with a generous per-user limit (pageviews are frequent but bounded). Body: `{ path: str }`. Behaviour: strip query string → `normalize_route` → insert `PageEvent` → return `204`. Authenticating through `get_current_user` also stamps `active_days` for the day (the dependency above).
- **Repository:** `api/app/repositories/events.py`
  - `record_event(db, *, user_id, path) -> None` — normalize + insert.
  - `daily_active_users(db, days: int) -> list[(date, count)]` — distinct users per UTC day over the window.
  - `active_user_counts(db) -> {"d1": int, "d7": int, "d30": int}` — distinct users active in the last 1/7/30 days.
  - `league_activity(db) -> dict[league_id, {events, active_users, last_activity}]` — per-league rollup.
  - `user_activity(db, user_id, *, recent_limit: int, days: int) -> {recent: list[event], daily: list[(date,count)]}` — drill-down.

### 5. Admin API

In `api/app/routes/admin.py` (all `require_admin`):

- `GET /api/admin/telemetry/active-users` → `{ daily: [{date, count}], d1, d7, d30 }`.
- Extend `GET /api/admin/leagues` response (`AdminLeague`) with `active_users: int` and `last_activity: str | None` from `league_activity` (single rollup, joined in).
- `GET /api/admin/users/{user_id}/activity` → `{ recent: [{path, route, league_id, league_name, created_at}], daily: [{date, count}] }`. League names resolved with the same cache+stored-name fallback already used in `users_list`.

### 6. Admin UI

- **Active users** (`web/app/admin/page.tsx`): a new "Usage" section — a compact DAU mini bar chart (last ~30 days) plus headline "active in last 1 / 7 / 30 days" stat cards. Reuses existing card styling.
- **Per-league activity:** add *Active users* and *Last activity* columns to the existing Leagues table.
- **Per-user drill-down:** each Users-table row links to a new route `web/app/admin/user/[id]/page.tsx` showing the user's recent pages (readable `path` + relative time) and a small per-day activity chart. Admin-gated like the rest of `/admin`.

### 7. API client

`web/lib/api.ts`: a `recordEvent(path)` helper is **not** added (the beacon posts directly). Add typed fetchers + interfaces for the new admin telemetry endpoints (`adminActiveUsers()`, `adminUserActivity(id)`), and extend `AdminLeague` with the two new fields.

## Privacy

First-party, admin-only viewing, login-gated app. Storing `user_id` + path is acceptable for internal product analytics; **no consent banner.** Query strings are stripped at capture so nothing sensitive is persisted. No data leaves the system.

## Testing

- **`normalize_route`** — unit tests across the route table (known routes, league extraction, owner pages, unknown-shape masking, trailing slash, query string already stripped).
- **`events` repository** — `record_event` insert; `daily_active_users` / `active_user_counts` windowing; `league_activity` rollup; `user_activity` drill-down. Seeded with fixed timestamps.
- **`POST /api/events`** — 204 on valid body; 401 without auth; rate-limit enforced; query string stripped before storage.
- **Admin telemetry endpoints** — response shapes + `require_admin` (403 for non-admins).
- **Frontend** — vitest for `Telemetry.tsx`: fires the beacon on initial mount and on pathname change, with `sendBeacon` mocked; no fire when pathname is unchanged.

## Components & boundaries (summary)

| Unit | Responsibility | Depends on |
|---|---|---|
| `route_normalize.py` | path → (template, league_id), pure | — |
| `db/models.py::PageEvent` | table definition | Base |
| `repositories/events.py` | insert + aggregations | PageEvent |
| `routes/events.py` | capture endpoint | get_current_user, events repo, route_normalize |
| `routes/admin.py` (additions) | telemetry read endpoints | events repo, ChainCache (league names) |
| `components/Telemetry.tsx` | client beacon | proxy + /api/events |
| `app/admin/*` (additions) | dashboards + drill-down page | admin telemetry endpoints |

## Out of scope / future

- Global "top pages" leaderboard (data supports it; view not built).
- Retention/rollup/pruning (add when volume warrants; flagged above).
- Funnels, session replay, referrer/navigation-path chains.
