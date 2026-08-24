> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Remove Login / Hardwire League Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the username-lookup entry flow with a server-side redirect from `/` to one configured league's dashboard (`/league/$LEAGUE_ID`), and delete the now-dead lookup code (frontend + API).

**Architecture:** `/` becomes a `force-dynamic` server component that reads `process.env.LEAGUE_ID` at request time and redirects into the existing `/league/[id]` dashboard (unchanged). The decision is a pure helper for testability. `UsernameSearch`, `/u/[username]`, and `POST /api/lookup` (+ `LookupResp`) are removed; `LeagueSummary` and the engine `get_user_id`/`get_leagues` (CLI) are kept.

**Tech Stack:** Next.js 14 App Router / TS (web), FastAPI (api). Web typecheck: `cd web && npx tsc --noEmit`. Web unit: `cd web && npx vitest run --config tests/vitest.config.ts`. API: `cd api && ../.venv/bin/python -m pytest -q`.

**Configured value:** `LEAGUE_ID=9000000000000000001` (2026 entry of the "Example League" chain).

---

## File Structure

- `web/lib/league-config.ts` — **new.** `leagueRedirectTarget(env)` pure helper.
- `web/tests/league-config.test.ts` — **new.** Unit test.
- `web/app/page.tsx` — rewritten as the redirect server component.
- `web/components/UsernameSearch.tsx` — **delete.**
- `web/app/u/[username]/page.tsx` (+ `web/app/u/` dir) — **delete.**
- `web/lib/api.ts` — remove `lookup()` + the `LookupResp` import token.
- `web/lib/types.ts` — remove the `LookupResp` interface (keep `LeagueSummary`).
- `api/app/routes/lookup.py` — **delete.**
- `api/app/main.py` — remove the two lookup-router lines.
- `api/app/models/league.py` — remove the `LookupResp` class (keep `LeagueSummary`).
- `api/tests/test_lookup.py` — **delete.**
- `README.md` — document `LEAGUE_ID`.

---

## Task 1: `leagueRedirectTarget` helper

**Files:**
- Create: `web/lib/league-config.ts`, `web/tests/league-config.test.ts`

- [ ] **Step 1: Write the failing test** — create `web/tests/league-config.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { leagueRedirectTarget } from "@/lib/league-config";

describe("leagueRedirectTarget", () => {
  it("returns the dashboard path when a league id is set", () => {
    expect(leagueRedirectTarget("9000000000000000001")).toBe("/league/9000000000000000001");
  });
  it("trims surrounding whitespace", () => {
    expect(leagueRedirectTarget("  123 ")).toBe("/league/123");
  });
  it("returns null when unset or blank", () => {
    expect(leagueRedirectTarget(undefined)).toBeNull();
    expect(leagueRedirectTarget("")).toBeNull();
    expect(leagueRedirectTarget("   ")).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx vitest run --config tests/vitest.config.ts tests/league-config.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement** — create `web/lib/league-config.ts`:

```ts
/** Resolve the redirect target for the single-league landing page.
 *  Returns "/league/<id>" when LEAGUE_ID is configured, else null. */
export function leagueRedirectTarget(leagueId: string | undefined): string | null {
  const id = (leagueId ?? "").trim();
  return id ? `/league/${id}` : null;
}
```

- [ ] **Step 4: Run** → PASS (3 tests). **Step 5: Commit**
```bash
git add web/lib/league-config.ts web/tests/league-config.test.ts
git commit -m "feat(web): leagueRedirectTarget helper for single-league landing"
```

---

## Task 2: Redirect `/` to the dashboard

**Files:**
- Modify: `web/app/page.tsx`

The current `page.tsx` imports `Shell`, `TopBar`, `UsernameSearch` and renders a
landing section. Replace its entire contents.

- [ ] **Step 1: Rewrite `web/app/page.tsx`**

```tsx
import { redirect } from "next/navigation";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { leagueRedirectTarget } from "@/lib/league-config";

// Read LEAGUE_ID at request time (not baked at build) so changing the league
// is a runtime env-var update with no rebuild.
export const dynamic = "force-dynamic";

export default function HomePage() {
  const target = leagueRedirectTarget(process.env.LEAGUE_ID);
  if (target) redirect(target);

  return (
    <Shell>
      <TopBar />
      <section className="mt-16 max-w-2xl">
        <p className="font-mono text-[10px] uppercase tracking-widest text-dim">
          Sleeper dynasty trade grader
        </p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight">
          League not configured
        </h1>
        <p className="mt-4 text-[14px] text-dim leading-relaxed max-w-lg">
          Set the <code className="font-mono">LEAGUE_ID</code> environment
          variable on the web service to your Sleeper league&apos;s
          current-season id, then reload.
        </p>
      </section>
    </Shell>
  );
}
```

- [ ] **Step 2: Typecheck** — `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit`. Expected: clean. (If it complains about `Shell`/`TopBar` paths, match the import paths the old `page.tsx` used — they were `@/components/Shell` and `@/components/TopBar`.)

- [ ] **Step 3: Commit**
```bash
git add web/app/page.tsx
git commit -m "feat(web): redirect / to /league/\$LEAGUE_ID (or not-configured notice)"
```

---

## Task 3: Delete the frontend lookup

**Files:**
- Delete: `web/components/UsernameSearch.tsx`, `web/app/u/[username]/page.tsx` (+ `web/app/u/` dir)
- Modify: `web/lib/api.ts`, `web/lib/types.ts`

- [ ] **Step 1: Delete the files**
```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git rm web/components/UsernameSearch.tsx
git rm web/app/u/\[username\]/page.tsx
rmdir web/app/u 2>/dev/null || true
```

- [ ] **Step 2: Remove `lookup()` from `web/lib/api.ts`**

Change the import (drop `LookupResp`):
```ts
import {
  DashboardResp, LatestTrade, Lens, OwnerDetailResp,
  TradeDetailResp, Year,
} from "./types";
```

Delete the entire `lookup` function:
```ts
export function lookup(username: string): Promise<LookupResp> {
  return jsonFetch<LookupResp>(`${BASE}/lookup`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username }),
  });
}
```

- [ ] **Step 3: Remove the `LookupResp` interface from `web/lib/types.ts`**

Delete:
```ts
export interface LookupResp {
  user_id: string;
  username: string;
  leagues_by_season: Record<string, LeagueSummary[]>;
}
```

**Keep** the `LeagueSummary` interface — it's used by `DashboardResp`. After
removing `LookupResp`, verify `LeagueSummary` is still referenced (it is, by the
dashboard). If `tsc` reports `LeagueSummary` as unused (it won't for an exported
interface), leave it — it's part of the public types.

- [ ] **Step 4: Typecheck** — `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit` → clean (this catches any dangling `lookup`/`LookupResp`/`UsernameSearch` references). If anything still imports them, remove those references.

- [ ] **Step 5: Web unit tests** — `cd web && npx vitest run --config tests/vitest.config.ts` → all pass (no test referenced the deleted lookup; the api-client test hits other endpoints).

- [ ] **Step 6: Commit**
```bash
git add web/lib/api.ts web/lib/types.ts web/components/UsernameSearch.tsx web/app/u
git commit -m "feat(web): delete username-lookup flow (UsernameSearch, /u, lookup client)"
```

---

## Task 4: Delete the API lookup

**Files:**
- Delete: `api/app/routes/lookup.py`, `api/tests/test_lookup.py`
- Modify: `api/app/main.py`, `api/app/models/league.py`

- [ ] **Step 1: Delete the route + test**
```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git rm api/app/routes/lookup.py api/tests/test_lookup.py
```

- [ ] **Step 2: Unregister the router in `api/app/main.py`** — remove these two lines:
```python
    from app.routes import lookup
    app.include_router(lookup.router)
```
(Leave the health/league/refresh/owner/trade registrations intact.)

- [ ] **Step 3: Remove `LookupResp` from `api/app/models/league.py`** — delete the class (and the extra blank line after it):
```python
class LookupResp(BaseModel):
    user_id: str
    username: str
    leagues_by_season: dict[int, list[LeagueSummary]]
```
**Keep `LeagueSummary`** — used by the dashboard (`aggregations.py:262`,
`models/league.py:82`).

- [ ] **Step 4: Run the api suite** — `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest -q`. Expected: all pass (test_lookup gone; the app boots without the lookup router; a quick grep for stray `LookupResp` imports should turn up nothing: `grep -rn "LookupResp\|routes import lookup\|from app.routes.lookup" api/app`).

- [ ] **Step 5: Commit**
```bash
git add api/app/main.py api/app/models/league.py api/app/routes/lookup.py api/tests/test_lookup.py
git commit -m "feat(api): remove /api/lookup route + LookupResp model"
```

---

## Task 5: Document `LEAGUE_ID`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add `LEAGUE_ID` to the README config/deploy notes.** Find the
  section documenting `API_URL` / frontend env (or the Config/Deployment section)
  and add:

```markdown
- `LEAGUE_ID` (web service) — the Sleeper league id the app serves. `/` redirects
  to `/league/$LEAGUE_ID`. Read at **request time** (no rebuild to change it).
  Current value: `9000000000000000001` (2026 season). Update at season rollover.
  Local dev: put it in `web/.env.local`.
```

- [ ] **Step 2: Commit**
```bash
git add README.md
git commit -m "docs: document LEAGUE_ID env var for the single-league landing"
```

---

## Task 6: Full verification

- [ ] **Step 1: API suite** — `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest -q` → all PASS.
- [ ] **Step 2: Web typecheck + unit** — `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit && npx vitest run --config tests/vitest.config.ts` → clean + all pass.
- [ ] **Step 3: Dangling-reference sweep** — confirm nothing references the removed symbols:
  `grep -rn "UsernameSearch\|LookupResp\|/api/lookup\|app/u/" web/app web/lib web/components api/app` → only expected/none.
- [ ] **Step 4:** commit any stragglers.

---

## Deploy (after merge — not a code task)

- Set the runtime var: `railway variables --set LEAGUE_ID=9000000000000000001 --service web`.
- `railway up --service web` (and `--service api` since the lookup route was removed).
- Verify: hitting `https://web-production-f949.up.railway.app/` lands on the dashboard; `/api/health` still ok.

---

## Notes / out of scope (per spec)

- Dashboard / owner / trade pages and the cold-start 409 → SSE flow: unchanged.
- Engine `get_user_id` / `get_leagues`: kept (CLI). `LeagueSummary`: kept (dashboard).
- No real auth added; single-user convenience. `API_URL` stays a build arg.
