# Admin league access — design

**Date:** 2026-08-12
**Status:** approved

## Problem

The app owner is the only admin and the only person who can reach `/admin`, but has no
way to open a league they are not a member of. Every league route is gated by
`require_league_member`, so diagnosing a user-reported bug, seeing how another league is
configured, or checking how a screen renders against unfamiliar data all require a
membership row that does not exist.

## What this is, stated plainly

A deliberate mechanism for reading **other people's private league data**. The mechanism
is trivial — one branch at an existing chokepoint. The defaults are the actual design
work, and they are chosen to make the smallest capability that covers the need.

## Decisions

| Question | Decision |
|---|---|
| Scope | **Read + refresh only.** GET/HEAD bypass the membership check; writes still 403. |
| Viewpoint | **Your own, with admin access.** No impersonation of a member. |
| Audit | **None.** Accepted tradeoff — see Risks. |
| Entry | Link per row from the `/admin` Leagues table. |
| Indicator | Persistent banner on every league route. |

## Design

### Backend — one branch at one chokepoint

`api/app/auth/deps.py::require_league_member` already contains this exact shape for the
`ALLOWLISTED_LEAGUE_ID` rollout bridge: allow the read, refuse the write. Admin access
becomes its sibling.

```python
if user.is_admin and request.method in {"GET", "HEAD"}:
    return user
```

Every league-gated router in `main.py` depends on this one function, so no existing route
can miss the behaviour and no future route can forget it. That single-chokepoint property
is the reason this belongs here rather than in a new per-router dependency.

Writes fall through to the existing 403. This is what keeps a debugging session from
mutating a stranger's league: there is no undo on owner-name overrides, profile edits, or
bet mutations.

`GET /api/league/{id}/refresh` is a GET, so warming a cold cache to reproduce a bug is
still available — which is usually what debugging actually needs.

### Frontend — entry point

The `/admin` Leagues table already lists every imported league. Each row gains a link to
`/league/{id}`.

### Frontend — the banner

There is no shared layout under `app/league/[id]/` today: `LeagueHeader` renders only on
the dashboard, and `Shell` is a per-page container. This adds
`app/league/[id]/layout.tsx`, which App Router applies to the dashboard, draft board,
owner, trade, gm, and settings routes at once.

The layout fetches `GET /api/me/leagues` (already exists — it backs the My Leagues home)
and renders the banner when the current league is not among them. The inference is sound
because a non-member non-admin never reaches the page: they are refused at the API.

Styling follows the `agate-styling` skill. Note `--stamp` is restricted to four sanctioned
places and a banner is not one of them, so this cannot be a coloured bar.

## Tests

Backend:
- admin GET on a league they are not a member of → 200
- admin PUT/POST on the same league → 403
- non-admin non-member → 403 (unchanged)
- an actual member → unaffected (unchanged)

Frontend:
- banner renders when the league is not in the viewer's leagues
- banner absent when it is

## Risks and accepted tradeoffs

**No audit trail.** With no log there is no record of which leagues were opened or when.
Acceptable at one admin, and deliberately chosen. It is awkward to retrofit once a second
person holds the role — **revisit before granting `is_admin` to anyone else.**

**The banner is inferred, not asserted.** It keys on "this league is not in your list"
rather than on a server-provided flag. If `/api/me/leagues` fails, the banner may show on
your own league. That is the safe direction to fail — over-warning, not under-warning.

**Read access is still read access.** Everything in a league is visible: rosters, trades,
side bets, owner names. The scope decision limits damage, not exposure.

## Out of scope

- Impersonating a specific member (the owner page's "vs You" band degrades to its existing
  no-viewer fallback).
- Audit logging.
- Any write access.
- Granting non-admin users cross-league access.
