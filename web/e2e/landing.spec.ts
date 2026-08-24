import { test, expect } from "@playwright/test";
import { PRODUCT_NAME } from "../lib/brand";

// The app is login-gated (web/middleware.ts) — there is no public marketing
// landing page anymore. An anonymous visit to any route (including "/")
// redirects to /login. These specs assert on that real behavior and on the
// actual copy in web/app/login/page.tsx, not retired marketing copy.

test("anonymous visit redirects to the login page", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  // Read the name from `lib/brand`, do not restate it. This line asserted the
  // literal "dynasty.report" and had been red since the product was renamed —
  // in a file whose own header says it asserts real behaviour "not retired
  // marketing copy". Importing the constant is what stops the next rename
  // leaving a stale literal behind here again.
  await expect(page.getByRole("heading", { level: 1 })).toContainText(PRODUCT_NAME);
});

test("login page shows the Google sign-in affordance", async ({ page }) => {
  await page.goto("/login");
  await expect(
    page.getByText("Sign in to view your leagues and analyze your performance."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /continue with google/i })).toBeVisible();
});
