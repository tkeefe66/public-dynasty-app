# Remove Login / Hardwire League — Design

**Date:** 2026-05-31
**Status:** Approved, ready for implementation plan
**Scope:** Single-user personalization. Remove the username-lookup entry flow and
land users directly on one configured league's dashboard.

## Problem

The app has a username-lookup entry flow (not real auth):

1. `/` (`web/app/page.tsx`) — a `UsernameSearch` box.
2. `/u/[username]` — lists the user's leagues across seasons via
   `POST /api/lookup`; user picks one.
3. `/league/[id]` — the actual dashboard (cold-starts via SSE refresh).

This app is only ever used for one league ("Example League"), so steps 1–2 are
pure friction. We hardwire the league and go straight to the dashboard.

## Decisions (locked during brainstorming)

1. **Pin the league via a runtime env var** `LEAGUE_ID`. `/` server-redirects to
   `/league/$LEAGUE_ID`. Configured value: **`9000000000000000001`** (the 2026,
   current-season head of the chain). Sleeper mints a new league ID each season,
   so at rollover this env var is updated once — no code change, no rebuild.
2. **Full clean removal** of the now-dead lookup machinery (frontend + API
   endpoint), not just hiding it.

## The key mechanic

A **server-side** redirect reads `process.env.LEAGUE_ID` at *request* time
(unlike `API_URL`, which is baked at build). So changing the league is a pure
variable update — no rebuild. The page is marked `force-dynamic` so Next.js
evaluates it per request rather than statically prerendering at build.

## Architecture

`/` collapses to a redirect into the existing `/league/[id]` dashboard. Nothing
about the dashboard, owner, or trade pages — or the cold-start/refresh (409 →
SSE) flow — changes. The lookup route and its frontend are deleted.

## Components

### 1. Redirect `/` — *`web/app/page.tsx`*

`page.tsx` becomes a server component:

```tsx
import { redirect } from "next/navigation";
import { leagueRedirectTarget } from "@/lib/league-config";

export const dynamic = "force-dynamic";

export default function HomePage() {
  const target = leagueRedirectTarget(process.env.LEAGUE_ID);
  if (target) redirect(target);
  return <NotConfiguredNotice />;   // minimal inline message
}
```

The decision is extracted into a pure, testable helper:

```ts
// web/lib/league-config.ts
export function leagueRedirectTarget(leagueId: string | undefined): string | null {
  const id = (leagueId ?? "").trim();
  return id ? `/league/${id}` : null;
}
```

- **Unset guard:** if `LEAGUE_ID` is missing/blank, render a minimal "league not
  configured — set LEAGUE_ID" notice instead of redirecting to `/league/`
  (broken). Avoids a confusing blank/404.

### 2. Delete the frontend lookup

- `web/components/UsernameSearch.tsx`
- `web/app/u/[username]/page.tsx` (and the now-empty `web/app/u/` dir)
- `lookup()` function in `web/lib/api.ts`, and the `LookupResp` import there
- `LookupResp` interface in `web/lib/types.ts`

### 3. Delete the API lookup

- `api/app/routes/lookup.py`
- The two registration lines in `api/app/main.py`
  (`from app.routes import lookup` / `app.include_router(lookup.router)`)
- `LookupResp` model in `api/app/models/league.py`.
  **Keep `LeagueSummary`** — it's used by the dashboard payload
  (`aggregations.py:262`, `models/league.py:82`).
- `api/tests/test_lookup.py`

### 4. Config

- New **runtime** env var on the **web** Railway service:
  `LEAGUE_ID=9000000000000000001`. Set via
  `railway variables --set LEAGUE_ID=9000000000000000001 --service web` (or
  dashboard). No build arg, no rebuild needed to change it later.
- Local dev: `web/.env.local` (gitignored) with `LEAGUE_ID` + `API_URL`.
- Document the var in `README.md` (and `web` env notes).

## Out of scope / unchanged

- The `/league/[id]` dashboard, owner (`/league/[id]/owner/[uid]`), and trade
  (`/league/[id]/trade/[tid]`) pages; the cold-start 409 → SSE refresh flow.
- Engine `SleeperClient.get_user_id` / `get_leagues` — **kept** (the CLI uses
  them to resolve a username; only the *API* `/api/lookup` route is removed).
- `LeagueSummary` model — kept (dashboard payload).
- No real authentication is added; this is a single-user convenience.

## Edge cases

- **`LEAGUE_ID` unset/blank** → "not configured" notice (no broken redirect).
- **Direct visit to `/league/<other-id>`** still works (routes are unchanged) —
  the redirect only governs `/`. Acceptable for a personal app; not locking the
  dashboard to one id.
- **Season rollover** → update the `LEAGUE_ID` variable to the new season's id;
  the chain walk back to origin is automatic.

## Testing

- Unit-test `leagueRedirectTarget`: a value → `/league/<id>` (trimmed); undefined
  / `""` / whitespace → `null`. (web, vitest)
- Remove `api/tests/test_lookup.py`; confirm the API app still imports/boots
  without the lookup router (existing route tests + `/api/health` cover this).
- Confirm no dangling imports after deletions (`LookupResp`, `lookup`,
  `UsernameSearch`) — type-check (`tsc --noEmit`) + the api suite catch these.
- Manual: hitting `/` lands on the dashboard for `9000000000000000001`.

## Notes

- `API_URL` stays a build arg (existing deploy constraint); only `LEAGUE_ID` is a
  runtime var. They coexist on the web service.
- This is a frontend-+-thin-API change; no engine logic changes.
