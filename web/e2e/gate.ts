import { test } from "@playwright/test";

/**
 * The gate the data-backed specs sit behind — and why it is a FAILURE, not a
 * skip.
 *
 * Four specs (viewport, owner, bets, og) need a warmed league to mean anything,
 * so each opened with `test.skip(!process.env.E2E_LEAGUE_ID, "...")`. Nobody
 * sets `E2E_LEAGUE_ID`. The result: every one of them skipped every case on
 * every run and Playwright exited **0**, so the whole set read as passing while
 * testing nothing — for the viewport matrix, 31 cases of mobile-overflow
 * coverage that had never once executed. A suite that silently tests nothing is
 * worse than no suite: it answers "is this covered?" with yes.
 *
 * Two changes fix that, and the first one is the important one:
 *
 * 1. **It resolves an id that actually exists.** `LEAGUE_ID` is already in
 *    `.env.local` (the web app's default league, `.env.example`), and
 *    `playwright.config.ts` calls `loadEnvConfig`, so it is in `process.env`
 *    before any spec loads. `E2E_LEAGUE_ID` still wins when set — pointing the
 *    suite at a different league stays a one-variable override.
 * 2. **Missing configuration is red.** There is no CI here (no
 *    `.github/workflows`), so nothing breaks for anyone else, and a local run
 *    that cannot test what it claims to test should say so in the exit code.
 *    `E2E_SKIP_GATED=1` is the deliberate opt-out for someone who genuinely has
 *    no league to point at — a choice you have to make, not a default you fall
 *    into.
 *
 * The optional ids stay optional: they ADD screens rather than enable the
 * suite, and `announceCoverage` prints which ones are absent so a narrowed
 * matrix says it is narrowed instead of quietly passing a smaller set.
 */

/** The league every data-backed spec runs against. */
export const LEAGUE_ID = process.env.E2E_LEAGUE_ID || process.env.LEAGUE_ID;

/** Optional ids. Each one present adds a screen; absent narrows coverage. */
export const OWNER_ID = process.env.E2E_OWNER_ID;
export const TRADE_ID = process.env.E2E_TRADE_ID;
export const DRAFT_SEASON = process.env.E2E_DRAFT_SEASON;

/** The deliberate opt-out. Skips instead of failing. */
export const OPTED_OUT = process.env.E2E_SKIP_GATED === "1";

const HOW_TO =
  "Set LEAGUE_ID in web/.env.local (or E2E_LEAGUE_ID) to a league the test " +
  "user can read — the backend's TRADE_GRADER_ALLOWLISTED_LEAGUE_ID grants " +
  "that without a membership row. To run without one on purpose, set " +
  "E2E_SKIP_GATED=1.";

/**
 * Call at the top of a `describe` that needs a warmed league.
 *
 * Opted out → skip, loudly labelled. Otherwise a missing league THROWS in
 * `beforeAll`, which fails every test in the block rather than passing over
 * them. `test.skip()` cannot express "this should have run", which is the
 * whole reason this helper exists.
 */
export function requireLeague(): void {
  if (OPTED_OUT) {
    test.skip(true, `E2E_SKIP_GATED=1 — data-backed specs deliberately not run. ${HOW_TO}`);
    return;
  }
  test.beforeAll(() => {
    if (!LEAGUE_ID) throw new Error(`No league configured, so this suite would test nothing. ${HOW_TO}`);
    if (!process.env.AUTH_SECRET) {
      throw new Error(
        "AUTH_SECRET is unset, so the forged session cannot be signed and every " +
          "authed page would land on /login. Set it in web/.env.local.",
      );
    }
  });
}

/**
 * Print what this run does NOT cover. "No silent caps": a matrix that dropped
 * screens because an optional id was absent must say which, or its green reads
 * as coverage it never had.
 */
export function announceCoverage(optional: Record<string, string | undefined>): void {
  const missing = Object.entries(optional)
    .filter(([, v]) => !v)
    .map(([k]) => k);
  if (missing.length) {
    console.log(`[e2e] league ${LEAGUE_ID} — screens omitted, unset: ${missing.join(", ")}`);
  }
}
