import { test, expect } from "@playwright/test";

/**
 * The acceptance test for the forged-session fixture (followup C6): with the
 * session cookie in `storageState`, real middleware lets us past the login gate
 * and onto a real page. Before this, Playwright could only assert the redirect.
 *
 * Runs in the `chromium-authed` project only — the anonymous project ignores it.
 */

test.skip(
  !process.env.AUTH_SECRET,
  "Set a throwaway AUTH_SECRET to run authed specs (see e2e/README.md).",
);

test("an authed session reaches My Leagues instead of the login gate", async ({ page }) => {
  await page.goto("/");
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("My Leagues");
});

test("the account page renders for the forged user", async ({ page }) => {
  await page.goto("/account");
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Account");
});

test("no app code shipped the bypass — the session is a normal cookie", async ({ context }) => {
  const cookies = await context.cookies("http://localhost:3000");
  const session = cookies.find((c) => c.name.endsWith("authjs.session-token"));
  expect(session, "forged session cookie is present").toBeTruthy();
  // httpOnly, like the real thing — nothing about this session is special.
  expect(session!.httpOnly).toBe(true);
});
