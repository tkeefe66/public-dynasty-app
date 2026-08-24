# Settings — admin-only section gating

**Date:** 2026-06-28
**Branch:** `settings-update`
**Status:** Approved design, pending implementation plan

## Problem

The league **Settings page** (`web/app/league/[id]/settings/page.tsx`) renders three
sections to every logged-in league member:

1. **Data** — `ManualRefresh` (manual "Refresh data" SSE button)
2. **Owner Names** — `OwnerNamesForm` (renames owners league-wide)
3. **LLM Spend** — `LlmCostPanel` (Anthropic spend charts/tables)

The Data and LLM Spend sections are operational/admin tooling. Non-admins should
not see them. Today they always render — LLM Spend merely fails its data fetch
(the endpoint is already `require_admin`-gated) and shows "Failed to load cost
data.", which is leaky and confusing.

## Goal

Hide **Data** and **LLM Spend** from non-admins. Keep **Owner Names** visible to
everyone. Non-admins keep access to the Settings page, with reduced contents.

## Admin model

Reuse the **existing global app-admin** concept — `MeProfile.is_admin`, derived
server-side from `TRADE_GRADER_ADMIN_EMAIL_LIST` (`api/app/auth/deps.py`). No new
per-league creator/commissioner concept is introduced.

## Scope: frontend visibility only

This is a **frontend-only** change. No backend route changes.

Rationale for *not* adding backend gating to the refresh path:

- Cold-start auto-triggers `GET /api/league/{id}/refresh` for **any** user from
  `web/components/DashboardClient.tsx:49` when a league's `ChainCache` is cold
  (dashboard endpoints return `409 cache cold` until the chain is built). Gating
  `/refresh` admin-only would break league loads for non-admin members. The
  endpoint must stay open; we only hide the **manual** refresh button.
- The LLM cost endpoint (`/api/settings/llm-cost`) is **already**
  `require_admin`-gated (`api/app/routes/settings.py`). Real access control for
  spend data already exists server-side. This change just stops showing
  non-admins a panel that silently fails.

So no new server-side authorization is required; the existing controls are
sufficient. This change is purely about not rendering operator UI to members.

## Implementation

`web/app/league/[id]/settings/page.tsx` is an async React Server Component. It
already fetches `getOwnerNames(params.id)` server-side via the registered
server-auth provider (`web/lib/auth-server.ts` mints a short-lived HS256 bearer
from the NextAuth session and wires it into `lib/api` RSC fetches).

1. Fetch the current user's profile server-side: `const me = await getMe()`
   inside a `try/catch`. On any failure (no session → 401, network error),
   default to `isAdmin = false`. **Fail closed.**
2. Conditionally render `<ManualRefresh>` and `<LlmCostPanel>` only when
   `me?.is_admin === true`.
3. `<OwnerNamesForm>`, the page heading, and the "not loaded yet" fallback render
   unconditionally (unchanged).

No client component changes. No new props threaded. Admin-only markup is never
sent to a non-admin's browser (no flash, no leak).

### Sketch

```tsx
export default async function SettingsPage({ params }: { params: { id: string } }) {
  let data: OwnerNamesResp | null = null;
  try { data = await getOwnerNames(params.id); } catch { data = null; }

  let isAdmin = false;
  try { isAdmin = (await getMe()).is_admin; } catch { isAdmin = false; }

  return (
    <Shell>
      <TopBar leagueId={params.id} activeNav="settings" />
      <div className="max-w-md space-y-8">
        <div><h1 className="text-xl font-bold mb-1">League Settings</h1></div>
        {isAdmin && <ManualRefresh leagueId={params.id} />}
        <div>
          {data
            ? <OwnerNamesForm leagueId={params.id} initial={data.owners} />
            : <p className="text-dim text-sm">League not loaded yet. Run a refresh first.</p>}
        </div>
        {isAdmin && <div><LlmCostPanel /></div>}
      </div>
    </Shell>
  );
}
```

## Edge cases

- **No session / unauthenticated render** → `getMe()` 401 → caught → non-admin →
  sections hidden. Correct (fail closed).
- **Cold league, non-admin** → unaffected. The auto-refresh in `DashboardClient`
  is independent of the manual Data button and the `/refresh` endpoint stays open.
- **Owner Names "not loaded yet" fallback** → still shown to non-admins so they
  understand the league needs a refresh, even though they can't trigger one
  manually (cold-start auto-refresh covers the real load path).

## Out of scope

- Per-league creator/commissioner concept (deferred; not needed for this).
- Backend authorization changes (existing controls suffice).
- Hiding the Settings nav link entirely (Owner Names keeps Settings member-facing).

## Testing

- **Manual / e2e:** admin sees all three sections; non-admin sees only Owner
  Names (+ heading). Confirm no "Failed to load cost data." appears for non-admins.
- Prefer a Playwright assertion in `web/` if the e2e harness can mock/inject an
  admin vs non-admin session; otherwise verify manually against a known
  non-admin Google account.
