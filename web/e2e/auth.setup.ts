/**
 * Playwright setup project: write the authed `storageState.json` the
 * `chromium-authed` project loads (followup C6).
 *
 * A setup project rather than `globalSetup` so it appears in the report as a
 * real step, and so a missing `AUTH_SECRET` reads as one skipped setup rather
 * than every authed spec failing with a mysterious redirect to /login.
 */
import { test as setup, expect } from "@playwright/test";
import path from "path";
import { forgeSessionCookie } from "./fixtures/session";

export const STORAGE_STATE = path.join(__dirname, ".auth", "storageState.json");

setup("forge an authenticated session", async ({ page, context, baseURL }) => {
  setup.skip(
    !process.env.AUTH_SECRET,
    "AUTH_SECRET is not set — authed specs are skipped. Set a throwaway value " +
      "(see e2e/README.md) to run them.",
  );

  await context.addCookies([await forgeSessionCookie({ baseURL: baseURL! })]);

  // Prove the forged cookie satisfies the REAL middleware before any spec
  // depends on it. If the cookie name, salt, or secret were wrong, this fails
  // here with an obvious message instead of surfacing as a confusing redirect
  // inside an unrelated spec.
  await page.goto("/");
  await expect(page, "forged session was rejected by middleware").not.toHaveURL(/\/login/);

  await context.storageState({ path: STORAGE_STATE });
});
