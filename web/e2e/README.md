# e2e suite

```bash
cd web && npm run test:e2e
```

Two projects run:

| Project | Session | Specs |
|---|---|---|
| `chromium` | none | `landing.spec.ts` — the login-gate redirect, which only means something anonymously |
| `chromium-authed` | forged session from the `setup` project | everything else |

## The auth fixture, and the one rule about it

Every page is login-gated by `web/middleware.ts` (NextAuth + Google), so the
suite used to be able to test exactly one thing: that an anonymous visit
redirects to `/login`.

Instead of adding a test bypass to the app, the suite **forges the session
cookie the app already trusts**. NextAuth v5 sessions here are JWT-strategy
cookies encrypted (JWE) with `AUTH_SECRET`; anyone holding that secret can mint
one, which is already the trust model. `e2e/fixtures/session.ts` does exactly
that, `e2e/auth.setup.ts` writes it to `e2e/.auth/storageState.json`, and the
authed project loads it. The web→api proxy then mints its backend HS256 token
from that session server-side exactly as it does in production, so the backend
needs nothing new (`get_current_user` upserts the user row on first request).

**No app code implements any of this.** Nothing outside `e2e/` participates:

```bash
rg -n "e2e|E2E" --glob '!e2e/**' web/app web/components web/lib web/middleware.ts web/auth.ts
```

should return nothing. That is the point — a bypass that exists only in the test
directory cannot be reached in production, and there is no env var that, set
wrong, opens one.

### ⚠️ Use a throwaway `AUTH_SECRET`

The test environment's `AUTH_SECRET` **must never be the production value**.
Holding it is equivalent to being able to sign in as anyone, and the fixture
demonstrates precisely that. Generate a local one:

```bash
openssl rand -base64 32   # put it in web/.env.local, or the CI environment
```

Authed specs **skip** when `AUTH_SECRET` is unset, so a missing secret reads as
"authed coverage didn't run" instead of a pile of redirect failures. Note that
the whole suite needs one anyway: the app can't boot without `AUTH_SECRET`
(NextAuth refuses), so with it unset the anonymous specs fail too — verified.
The skip is about a clear diagnosis, not about running without a secret.

`e2e/.auth/` holds the generated state and is gitignored — it contains a valid
session for whatever secret was used.

## Data behind the auth wall

Getting past auth doesn't warm a cache: an authed dashboard still `409`s until
the league is built. Specs that need real league data (`viewport.spec.ts`,
`owner.spec.ts`, `bets.spec.ts`) go through **`e2e/gate.ts`**.

**A missing league is a FAILURE, not a skip.** Those specs used to open with
`test.skip(!process.env.E2E_LEAGUE_ID, …)`. Nobody set `E2E_LEAGUE_ID`, so they
skipped every case on every run and Playwright exited `0` — the viewport matrix
in particular reported green for 31 mobile-overflow cases that had never once
executed. `gate.ts` fixes both halves:

- it resolves **`E2E_LEAGUE_ID` → `LEAGUE_ID`**, and `LEAGUE_ID` is already in
  `.env.local` (`playwright.config.ts` calls `loadEnvConfig`), so the specs run
  by default instead of waiting on a variable nobody sets;
- if no league resolves, `requireLeague()` **throws in `beforeAll`**, failing
  the block. `test.skip()` cannot express "this should have run".

`E2E_SKIP_GATED=1` is the deliberate opt-out. The other ids stay optional
because they *add* screens rather than enable the suite — `announceCoverage()`
prints which are unset, so a narrowed matrix says it is narrowed:

```
[e2e] league 1312… — screens omitted, unset: E2E_OWNER_ID, E2E_DRAFT_SEASON
```

Do not read an exit code through a pipe. `npx playwright test … | tail` reports
**tail's** status, so a 37-failure run looks like a pass; redirect to a file and
check `$?` directly.

Making this hermetic — smoke-testing the cold-start flow itself, or seeding a
prebuilt `ChainCacheEntry` into `TRADE_GRADER_CACHE_DIR` with
`ALLOWLISTED_LEAGUE_ID` — is still open; see
`docs/superpowers/specs/2026-08-05-e2e-auth-fixture-design.md` § "Second
problem".

### One more way to get a fake green

`next dev` and `npm run build` share `.next`. Running a production build while
the dev server is up wipes the dev vendor chunks, and every page then 500s with
`Cannot find module './vendor-chunks/…'` — which surfaces as *every* spec
failing on its `ready` locator, looking exactly like a layout regression. That
cost a whole 17-minute matrix run. Don't build while the suite is running; if
pages start 500ing, delete `.next` and restart dev before believing a failure.

## What this unlocks

Automated viewport QA. A 390px screenshot matrix across both themes can now
reach the dashboard, trade, and franchise pages — the class of bug (mobile
overflow) that was previously only ever hand-checked.
