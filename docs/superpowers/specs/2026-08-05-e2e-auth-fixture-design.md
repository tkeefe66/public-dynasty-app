# E2E auth fixture design (followup C6) — PROPOSAL, not yet implemented

**Problem.** `web/middleware.ts` gates every page behind NextAuth Google OAuth, so
Playwright can only test the landing→login redirect. The smoke suite can't reach the
dashboard, trade pages, or owner pages, and automated viewport QA (the 390px overflow
class of bug) is impossible.

**Constraint.** Security-relevant: no test bypass may be reachable in prod config. This
rules out the two obvious approaches — an env-gated Credentials provider and a
secret-header middleware bypass — both ship a bypass code path to prod and rely on an env
var never being set wrong.

## Recommended design: forge the session, ship zero code

NextAuth v5 sessions here are JWT-strategy cookies encrypted (JWE) with `AUTH_SECRET`.
Anyone holding `AUTH_SECRET` can mint a valid session cookie — that's already the trust
model. So the fixture is:

1. **A test-only setup script** (`web/e2e/fixtures/session.ts`, dev-dependency only):
   calls `@auth/core/jwt` `encode()` with the same salt/cookie-name NextAuth uses and the
   test environment's `AUTH_SECRET`, producing a session cookie for a synthetic test user
   (fixed email like `e2e@test.local`).
2. **Playwright `storageState`**: a global-setup project writes the cookie into
   `storageState.json`; authed specs opt in via `use: { storageState }`. The
   redirect-to-login spec keeps an empty state.
3. **No app-code change.** Prod is untouched: forging requires `AUTH_SECRET`, which is
   exactly the secret prod already guards. CI/test must use a distinct throwaway
   `AUTH_SECRET` (never the prod value) — document in the e2e README.

The web→api proxy then mints its backend token from that session server-side, exactly as
prod does, so backend auth needs nothing new. `get_current_user` upserts the user row on
first request (verify — if it doesn't, seed one row in test setup).

## Second problem (separate, can be deferred): data behind the auth wall

An authed dashboard still 409s on a cold cache. Options, in order of preference:
- **Smoke-test the cold-start flow itself** (409 → refresh SSE → dashboard) against a
  test league id — slow, network-dependent, but honest.
- Seed a prebuilt `ChainCacheEntry` fixture into `TRADE_GRADER_CACHE_DIR` in CI and set
  `ALLOWLISTED_LEAGUE_ID` to its league — fast, hermetic, needs a fixture-refresh story
  when `SCHEMA_VERSION` bumps.
- Mock the backend entirely — rejected: the suite exists to catch integration drift.

## Acceptance

- Playwright reaches an authed page locally and in CI with real middleware active.
- `rg`-provable: no new runtime code path in `web/` outside `e2e/`/test config.
- Prod deploy unaffected; e2e README documents the distinct-`AUTH_SECRET` rule.
- Viewport QA (390px screenshot matrix) becomes possible → closes the B1 verification gap.
