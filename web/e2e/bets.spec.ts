import { expect, test } from "@playwright/test";

import { LEAGUE_ID, requireLeague } from "./gate";

const WRITE = process.env.E2E_WRITE === "1";

test.describe("side bets ledger", () => {
  // A missing league fails rather than skips — see `gate.ts`. The WRITE gate
  // below stays a skip: it guards a path that MUTATES a real league's ledger,
  // so opting in has to be deliberate.
  requireLeague();

  test("renders the bets tab", async ({ page }) => {
    await page.goto(`/league/${LEAGUE_ID}?tab=bets`);
    await expect(
      page.getByRole("button", { name: /record a bet/i }),
    ).toBeVisible();
  });

  test("record → settle → void round-trip", async ({ page }) => {
    test.skip(
      !WRITE,
      "Set E2E_WRITE=1 to exercise the write path (creates, settles, then voids a bet).",
    );
    const marker = `e2e smoke bet ${Date.now()}`;
    await page.goto(`/league/${LEAGUE_ID}?tab=bets`);
    await page.getByRole("button", { name: /record a bet/i }).click();

    await page.getByLabel("Side A").selectOption({ index: 1 });
    await page.getByLabel("Side B").selectOption({ index: 2 });
    await page.getByLabel("Amount ($)").fill("1");
    await page.getByLabel("The bet").fill(marker);
    await page.getByRole("button", { name: /save bet/i }).click();

    // Each bet is a `<div className="border-t ...">` row inside the single
    // Ledger `<section>` (see BetLedger.tsx), not its own <section> — scope
    // on that row div rather than "section" so the actions below only ever
    // touch the bet we just created.
    const row = page.locator("div.border-t", { hasText: marker }).last();
    await expect(row.getByText(marker)).toBeVisible();

    // Settle for side A, then void to leave no live money in the ledger.
    await row.getByRole("button", { name: /won$/ }).first().click();
    await expect(row.getByText(/won/).first()).toBeVisible();
    await row.getByRole("button", { name: "Reopen" }).click();
    await row.getByRole("button", { name: "Void" }).click();
    await expect(row.getByText("Void")).toBeVisible();
  });
});
