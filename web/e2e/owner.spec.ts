import { test, expect } from "@playwright/test";

// Requires a warmed/cached league reachable in the dev environment. The league
// comes from the shared gate (which resolves `.env.local`'s LEAGUE_ID, so this
// no longer needs an env var nobody sets); the OWNER id is genuinely optional
// data with no default, so it stays a skip.
import { LEAGUE_ID, OWNER_ID, requireLeague } from "./gate";

test.describe("owner command center", () => {
  requireLeague();
  test.skip(!OWNER_ID, "Set E2E_OWNER_ID to an owner in that league to run this smoke test.");

  test("renders the tabbed cockpit and switches tabs", async ({ page }) => {
    await page.goto(`/league/${LEAGUE_ID}/owner/${OWNER_ID}`);
    await expect(
      page.getByRole("tablist", { name: /franchise sections/i }),
    ).toBeVisible();
    await page.getByRole("tab", { name: /trades/i }).click();
    await expect(page.getByText("Every trade")).toBeVisible();
  });
});
