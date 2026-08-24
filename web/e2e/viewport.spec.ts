import { test, expect, type Locator, type Page } from "@playwright/test";
import path from "path";

/**
 * Viewport QA for the data-heavy screens (followup C12).
 *
 * The C6 forged session gets past auth, but the densest surfaces — the standings
 * ledger, the trade page, the franchise tabs — need a warm league behind them,
 * so this suite is gated on `E2E_LEAGUE_ID` pointing at one the test user can
 * read (set `TRADE_GRADER_ALLOWLISTED_LEAGUE_ID` on the backend to grant that
 * without a membership row).
 *
 * It is a **test**, not just a screenshot run. The bug class this exists to
 * catch is mobile horizontal overflow — a table that outgrows a 390px viewport —
 * and that is asserted directly: after the Agate port nothing but the year line
 * may scroll sideways, so the document must never be wider than the window.
 * Screenshots are written alongside as evidence for the eye.
 *
 * ```bash
 * E2E_LEAGUE_ID=... [E2E_OWNER_ID=...] [E2E_TRADE_ID=...] [E2E_DRAFT_SEASON=...] \
 *   npx playwright test --config e2e/playwright.config.ts --project=chromium-authed \
 *   --grep viewport
 * ```
 *
 * `E2E_DRAFT_SEASON` should name a season the league actually drafted — the
 * board 404s otherwise, and its detail lists the seasons that do exist.
 */

import { LEAGUE_ID, OWNER_ID, TRADE_ID, DRAFT_SEASON, requireLeague, announceCoverage } from "./gate";

const SHOTS = path.join(__dirname, "screenshots");

/** The one element the design system allows to scroll horizontally. */
const YEAR_LINE_ALLOWANCE = 1; // px, for sub-pixel rounding

const WIDTHS = [390, 768, 1180] as const;

test.describe("viewport", () => {
  /* A missing league FAILS here, it does not skip — this matrix skipped all 31
   * cases and exited 0 on every run it had ever had. See `gate.ts`. */
  requireLeague();
  announceCoverage({ E2E_OWNER_ID: OWNER_ID, E2E_TRADE_ID: TRADE_ID, E2E_DRAFT_SEASON: DRAFT_SEASON });

  /** Cold caches 409 and the app runs a refresh; give the first paint room. */
  test.beforeEach(async ({ page }) => {
    page.setDefaultTimeout(60_000);
  });

  async function assertNoHorizontalOverflow(page: Page, label: string) {
    const overflow = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth,
      win: window.innerWidth,
      // Name the *narrowest* elements that still exceed the viewport — the
      // innermost offenders, which is where the fix goes. `html`/`body` are
      // excluded: they always span scrollWidth and would mask the real cause.
      offenders: Array.from(document.querySelectorAll("*"))
        .filter((el) => !["HTML", "BODY"].includes(el.tagName))
        .map((el) => {
          const r = (el as HTMLElement).getBoundingClientRect();
          return {
            tag: el.tagName.toLowerCase(),
            cls: (el as HTMLElement).className?.toString().slice(0, 90) ?? "",
            right: Math.round(r.right),
            width: Math.round(r.width),
          };
        })
        .filter((o) => o.right > window.innerWidth + 1)
        .sort((a, b) => a.width - b.width)
        .slice(0, 3),
    }));
    expect(
      overflow.doc,
      `${label}: document is ${overflow.doc}px in a ${overflow.win}px viewport.\n` +
        `Innermost offenders:\n` +
        overflow.offenders
          .map((o) => `  <${o.tag} class="${o.cls}"> width ${o.width}, right edge ${o.right}`)
          .join("\n"),
    ).toBeLessThanOrEqual(overflow.win + YEAR_LINE_ALLOWANCE);
  }

  /**
   * The vertical counterpart. `.ruled > *` pins every rule to a hard
   * `--rule-pitch` (26px), so any child whose content needs more than that
   * escapes its box and collides with the neighbouring entry — the reader sees
   * two rows printed on top of each other. It cost a shipped mobile regression
   * on the trade ledger: a wrapping party list inside one rule.
   *
   * Horizontal overflow was already asserted here and caught nothing, because
   * this failure never widens the document. Height is its own bug class.
   */
  async function assertNoRuleOverflow(page: Page, label: string) {
    const spills = await page.evaluate(() => {
      const TOLERANCE = 1; // sub-pixel rounding
      // NOT scrollHeight: these rules are `overflow: visible`, so a child
      // painting outside the box does not grow scrollHeight at all — measured
      // and confirmed. The overflow is only visible in the geometry, so take
      // the union of descendant rects and compare it to the rule's own box.
      return Array.from(document.querySelectorAll(".ruled > *"))
        .map((el) => {
          const e = el as HTMLElement;
          const box = e.getBoundingClientRect();
          let top = box.top;
          let bottom = box.bottom;
          for (const d of Array.from(e.querySelectorAll("*"))) {
            const r = d.getBoundingClientRect();
            if (r.height === 0) continue; // hidden breakpoint variant
            top = Math.min(top, r.top);
            bottom = Math.max(bottom, r.bottom);
          }
          return {
            cls: e.className?.toString().slice(0, 90) ?? "",
            text: (e.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 60),
            box: Math.round(box.height),
            content: Math.round(bottom - top),
            spill: Math.round(bottom - top - box.height),
          };
        })
        .filter((r) => r.box > 0 && r.spill > TOLERANCE)
        .sort((a, b) => b.spill - a.spill)
        .slice(0, 5);
    });
    expect(
      spills,
      `${label}: ${spills.length} rule(s) overflow the 26px clamp and will ` +
        `overlap their neighbours:\n` +
        spills
          .map(
            (s) =>
              `  +${s.spill}px over (content ${s.content}px in a ${s.box}px rule) — ` +
              `"${s.text}" [${s.cls}]`,
          )
          .join("\n"),
    ).toEqual([]);
  }

  async function shoot(page: Page, name: string, width: number, theme: string) {
    await page.screenshot({
      path: path.join(SHOTS, `${name}-${width}-${theme}.png`),
      fullPage: true,
    });
  }

  /* A readiness marker must prove WARM DATA at EVERY width, which rules out two
   * tempting shortcuts: text that also appears in the TopBar nav ("Franchises"
   * matches the nav link, so it goes green while the cold-start modal is still
   * spinning), and text that only exists at one breakpoint (the owners
   * deep-dive pane is `hidden lg:block`). Where no such text exists, the marker
   * is structural. */
  type Screen = { name: string; url: string; ready: (p: Page) => Locator };
  const text = (s: string) => (p: Page) => p.getByText(s).first();

  const screens = (): Screen[] => {
    const s: Screen[] = [
      {
        name: "dashboard",
        url: `/league/${LEAGUE_ID}`,
        // The section heading, NOT its scope note. This was `text("Career-wide")`
        // and went red at 390 in both themes the moment the note became
        // desktop-only — the note is real content, but it is not present at
        // every width, and a readiness signal that disappears on a phone cannot
        // tell you a phone rendered. The heading is the section itself.
        ready: (p) => p.getByRole("button", { name: /^Franchises$/i }),
      },
      { name: "trades-tab", url: `/league/${LEAGUE_ID}?tab=trades`, ready: text("Trade history") },
      {
        name: "franchises-tab",
        url: `/league/${LEAGUE_ID}?tab=owners`,
        // The rail's owner links are the only thing present at every width.
        ready: (p) => p.locator('a[href*="/owner/"]').first(),
      },
      { name: "bets-tab", url: `/league/${LEAGUE_ID}?tab=bets`, ready: text("Side bets") },
      { name: "gm", url: `/league/${LEAGUE_ID}/gm`, ready: text("Franchise Ratings") },
    ];
    if (OWNER_ID) {
      s.push({
        name: "owner",
        url: `/league/${LEAGUE_ID}/owner/${OWNER_ID}`,
        ready: (p) => p.getByRole("tablist", { name: /franchise sections/i }),
      });
      // The Draft tab is the densest per-pick table on the owner page and the
      // one that gains/loses whole columns by league format, so it is the most
      // likely to outgrow a phone. Deep-linked via ?tab= rather than clicked,
      // matching how the other screens navigate.
      s.push({
        name: "owner-draft-tab",
        url: `/league/${LEAGUE_ID}/owner/${OWNER_ID}?tab=draft`,
        ready: (p) => p.getByRole("tablist", { name: /franchise sections/i }),
      });
    }
    if (DRAFT_SEASON) {
      // The board is the widest ledger in the app — pick, owner, player,
      // position, ADP, ADP delta, projected, and Total Points once graded.
      // Both defects this suite exists to catch shipped on this screen: a
      // fixed-px grid that overflowed, then columns hidden with no mobile
      // fallback. jsdom sees neither, which is exactly why they got here.
      s.push({
        name: "draft-board",
        url: `/league/${LEAGUE_ID}/draft/${DRAFT_SEASON}`,
        // The page-level heading, NOT a column header: the picks ledger
        // renders as two width-gated trees, so every header inside it is
        // invisible at one breakpoint or the other. The h1 also only exists on
        // the success branch, so it cannot go green on a 404 empty state.
        ready: (p) => p.getByRole("heading", { name: /draft board/i }),
      });
    }
    if (TRADE_ID) {
      s.push({
        name: "trade", url: `/league/${LEAGUE_ID}/trade/${TRADE_ID}`, ready: text("Scoreboard"),
      });
    }
    return s;
  };

  // Warm the league once. A cold chain cache 409s and the app kicks off a
  // refresh (SSE) that can take minutes on a long history, so this gets its own
  // generous budget instead of inflating every case below.
  test("warm the league cache", async ({ page }) => {
    test.setTimeout(15 * 60_000);
    await page.goto(`/league/${LEAGUE_ID}`);
    // Same signal the dashboard case uses, for the same reason: the heading
    // exists at every width, its scope note does not.
    await expect(page.getByRole("button", { name: /^Franchises$/i }).first())
      .toBeVisible({ timeout: 14 * 60_000 });
  });

  for (const width of WIDTHS) {
    for (const theme of ["light", "dark"] as const) {
      for (const screen of screens()) {
        test(`${screen.name} @ ${width} ${theme}`, async ({ page }) => {
          await page.setViewportSize({ width, height: 900 });
          await page.goto(screen.url);
          await expect(screen.ready(page)).toBeVisible();
          if (theme === "dark") {
            // Click the real toggle rather than seeding localStorage — see C13.
            await page.getByRole("button", { name: /dark theme/i }).click();
          }
          await assertNoHorizontalOverflow(page, `${screen.name} @ ${width}`);
          await assertNoRuleOverflow(page, `${screen.name} @ ${width} ${theme}`);
          await shoot(page, screen.name, width, theme);
        });
      }
    }
  }
});
