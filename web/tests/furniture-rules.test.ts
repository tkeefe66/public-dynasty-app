/**
 * Furniture drift guard — replaces web/tests/agate-rules.test.ts
 * ---------------------------------------------------------------------------
 * Generated from the Fantasy Analyzer design system. Edit the design system,
 * not this file — but DO edit it in the same commit as a design change, or the
 * new rule is not enforced anywhere.
 *
 * WHY THIS IS SCOPED
 * Hard-failing every directory on day one means CI is red from the first commit
 * of the port until the last screen lands, and a permanently red pipeline ends
 * with someone deleting the guard. So the guard runs at FULL STRENGTH, but only
 * over directories that have been converted. Add a directory to SCOPED_DIRS the
 * moment it is ported; the port is finished when SCOPED_DIRS covers everything
 * and UNSCOPED is empty.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname, resolve } from "node:path";

/**
 * Paths in SCOPED_DIRS are repo-relative (`web/...`), but vitest runs with CWD
 * = `web/`, so resolving them against CWD looks for `web/web/...`, finds
 * nothing, and every rule below passes over an EMPTY file list. That is a
 * guard that is green because it read no files — the exact failure this suite
 * exists to prevent. Anchor to the repo root instead, and keep the returned
 * paths repo-relative so the `except` entries still match by `endsWith`.
 */
const REPO_ROOT = resolve(__dirname, "..", "..");

/** Converted to Furniture. Widen as each directory lands. */
const SCOPED_DIRS: string[] = [
  // Pure logic, no styling — scoped so the guard covers them by default and a
  // future component dropped in here cannot slip through unguarded.
  "web/lib",
  "web/components/furniture",
  "web/components/methodology",
  "web/components/ownerdeepdive",
];

/**
 * Individually converted files that cannot be scoped by directory.
 *
 * `web/components` is FLAT and holds both ported and unported files, so it
 * cannot enter SCOPED_DIRS until the last one lands — which would leave the
 * app's most-seen screens unguarded for the whole migration. List a file here
 * the moment it is converted; it is enforced exactly as a scoped directory is.
 */
const SCOPED_FILES: string[] = [
  "web/components/RatingBars.tsx",
  "web/components/CareerArc.tsx",
  "web/components/BudgetEditor.tsx",
  "web/components/ProfileEditor.tsx",
  "web/components/LeagueHeader.tsx",
  "web/components/StandingsTable.tsx",
  "web/components/HeadlineMoves.tsx",
  "web/components/TradeHero.tsx",
  "web/components/TradeStatTable.tsx",
  "web/components/TradeCard.tsx",
  "web/components/TradeScoreboard.tsx",
  "web/components/TradeProductionCard.tsx",
  "web/app/league/[id]/trade/[tid]/page.tsx",
  // ---- landed via the parallel port, each reviewed individually ----
  "web/app/page.tsx",
  "web/app/leagues/add/page.tsx",
  "web/app/account/page.tsx",
  "web/components/bets/BetLedger.tsx",
  "web/components/bets/BetLeaderboard.tsx",
  "web/components/bets/BetsTab.tsx",
  "web/components/bets/RecordBetForm.tsx",
  "web/components/Leaderboard.tsx",
  "web/components/DraftBoard.tsx",
  "web/app/league/[id]/draft/[season]/page.tsx",
  // ---- the chrome tail, ported and reviewed ----
  "web/app/league/[id]/owner/[uid]/page.tsx",
  "web/components/OwnerDeepDive.tsx",
  "web/components/OwnersTab.tsx",
  "web/components/OwnerLabel.tsx",
  "web/components/OwnerNamesForm.tsx",
  "web/components/TradesTab.tsx",
  "web/components/TradeSidePanel.tsx",
  "web/components/TradeFindings.tsx",
  "web/components/ProductionTimeline.tsx",
  "web/app/not-found.tsx",
  "web/app/login/page.tsx",
  "web/app/layout.tsx",
  "web/app/league/[id]/layout.tsx",
  "web/components/DashboardClient.tsx",
  "web/components/InfoTooltip.tsx",
  "web/components/ManualRefresh.tsx",
  "web/components/WeekNote.tsx",
  "web/components/LeagueNotes.tsx",
  "web/components/ShareUrlButton.tsx",
  "web/components/ReceiptButton.tsx",
  "web/components/admin/DauBar.tsx",
  "web/components/TopBar.tsx",
  "web/components/LeagueSwitcher.tsx",
  "web/components/YearTabs.tsx",
  "web/components/SegmentControl.tsx",
  "web/components/ThemeToggle.tsx",
  // ---- already clean: no Agate-isms, scoped so they cannot regress ----
  "web/components/TradeReceiptButton.tsx",
  "web/components/ThemeProvider.tsx",
  "web/components/Telemetry.tsx",
  "web/components/Shell.tsx",
  "web/components/AssetRender.tsx",
  "web/app/methodology/page.tsx",
  "web/app/league/[id]/trade/[tid]/opengraph-image.tsx",
  "web/app/league/[id]/settings/page.tsx",
  "web/app/league/[id]/page.tsx",
  "web/app/league/[id]/owner/[uid]/opengraph-image.tsx",
  "web/app/league/[id]/opengraph-image.tsx",
  "web/app/league/[id]/gm/page.tsx",
  "web/app/league/[id]/gm/opengraph-image.tsx",
  "web/app/api/auth/[...nextauth]/route.ts",
  "web/app/api/[...path]/route.ts",
  "web/app/admin/page.tsx",
  "web/app/admin/user/[id]/page.tsx",
  "web/components/LlmCostPanel.tsx",
  "web/components/DashboardSkeleton.tsx",
  "web/app/league/[id]/owner/[uid]/loading.tsx",
  "web/components/ProgressModal.tsx",
  // Added on the outlook-assets-redesign branch, after the port closed —
  // `web/components` is FLAT, so a new component there is unguarded until it
  // is listed here. It was clean against all 17 rules on arrival; this is
  // COVERAGE, not a drift fix.
  "web/components/DraftGoingIn.tsx",
  // NOT here, and each for a checked reason:
  //  - DraftBoard: heading repointed, board still on the striped ground. Its
  //    overflow-x-auto exception is pre-registered above for when it lands.
  //  - app/account/page.tsx: was listed and should not have been. It passes
  //    every class-name rule while still importing the retired ground, which
  //    is exactly the hole the `retired-primitives` rule now closes.
];

/** EMPTY — the port is finished. Every file under web/{app,components,lib} is
 * in SCOPED_DIRS or SCOPED_FILES and the guard runs at full strength over all
 * of them. Kept as a named list rather than deleted so a future migration can
 * reuse the same widen-as-you-go mechanism.
 *
 * Historical note on what this cost to get right:
 *
 * NOTE ON THE SHAPE OF WHAT IS LEFT: `web/components` is FLAT, so a converted
 * file that stays there cannot be scoped — the directory only enters this list
 * when every file in it is converted. That is why `components/furniture/`
 * exists as the new primitive home rather than the primitives being edited in
 * place, and it is why `components/agate/` is not the natural next directory:
 * its `Ruled`/`Rule` are imported by 29 files, so retiring them is not one
 * directory's work but the whole app's. Convert feature directories first
 * (`bets/`, `ownerdeepdive/`), then the flat files, then `agate/` last. */
const UNSCOPED: string[] = [];

const EXTS = new Set([".ts", ".tsx", ".css"]);

function walk(dir: string): string[] {
  let out: string[] = [];
  let entries: string[];
  try { entries = readdirSync(resolve(REPO_ROOT, dir)); } catch { return out; }
  for (const e of entries) {
    const p = join(dir, e);
    if (statSync(resolve(REPO_ROOT, p)).isDirectory()) out = out.concat(walk(p));
    else if (EXTS.has(extname(p))) out.push(p);
  }
  return out;
}

/**
 * Strip block and line comments, replacing each with a space so nothing on
 * either side accidentally joins up.
 *
 * WHY: most rules here ban a CLASS NAME, and a class name is also the only way
 * to *write about* the pattern that was retired. Three separate comments in the
 * port tripped this guard — a note explaining why the striped ground is gone,
 * and one naming the avatar rounding that went with it — which meant the system
 * could not document its own history in place. Rules scan stripped source by
 * default; a rule that genuinely cares about prose opts back in with `scanRaw`.
 *
 * Deliberately naive: it does not track strings, so a `//` inside a string
 * literal truncates that line. That is acceptable for a drift scan (worst case
 * is a missed hit on one line, never a false failure) and is why `scanRaw`
 * exists rather than this being applied unconditionally.
 */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
}

const files = SCOPED_DIRS.flatMap(walk)
  .concat(SCOPED_FILES)
  .map((path) => {
    const src = readFileSync(resolve(REPO_ROOT, path), "utf8");
    return { path, src, code: stripComments(src) };
  });

type Rule = {
  id: string;
  why: string;
  bad: RegExp;
  allow?: RegExp;
  /** Paths exempt by explicit decision. Keep this list short and justified. */
  except?: string[];
  /**
   * Scan the file verbatim, comments included. Only for rules about what
   * reaches a human — `ktc` is the case: the banned term is banned in prose
   * too, so a comment mentioning it is still a finding.
   */
  scanRaw?: boolean;
};

const RULES: Rule[] = [
  /* ---- CHANGED UNDER FURNITURE ---- */
  {
    id: "radius",
    why:
      "Exactly one sanctioned radius. Was: zero radius anywhere. Now: 16px on " +
      "panels and bands (rounded-panel), pill on controls, zero on rules and " +
      "figures. A stray rounded-lg or rounded-[10px] is still a defect.",
    bad: /\brounded-(?!none\b|panel\b|pill\b|sm\b)[\w[\]./-]+/g,
  },
  {
    id: "adhoc-size",
    why:
      "Type sizes come off the seven-step scale — text-{nameplate,lead,section," +
      "name,prose,figure,label}. A literal `text-[13px]` is a size someone " +
      "eyeballed, and the scale exists so two elements doing the same job are " +
      "the same size.\n\n" +
      "This rule was MISSING while the whole port ran, and 52 off-scale sizes " +
      "survived in 16 files with the guard fully green — the port was declared " +
      "finished on that green. A `text-[length:var(--nameplate-2-sm)]` is fine " +
      "and deliberately not matched: that reads a token rather than inventing " +
      "a number.",
    bad: /\btext-\[[0-9.]+px\]/g,
  },
  {
    id: "elevation",
    why:
      "One elevation, used only to lift a panel off the ground. Was: zero " +
      "shadow. A second level, or a hover lift on a row, is a defect.",
    bad: /\bshadow-(?!panel\b|none\b)[\w[\]./-]+/g,
  },
  {
    id: "tone-contrast",
    why:
      "Signed figures take the -strong pair: text-pos-strong / text-neg-strong.\n\n" +
      "The base pair FAILS WCAG AA as text on every light ground this app " +
      "uses. Measured: --pos #00a63e is 2.90:1 on --bg, 3.22:1 on --surface, " +
      "3.06:1 on --surface-sunk, against a 4.5:1 bar — and on --bg it misses " +
      "even the 3:1 large-text floor. --neg #e12d39 clears 4.5:1 on pure white " +
      "only (4.53), and fails on the other two. The -strong pair passes " +
      "everywhere: 4.94/5.48/5.21 and 7.09/7.87/7.48. Dark theme passes either " +
      "way, but the class picks the token for BOTH themes, so light decides.\n\n" +
      "`colors.css` says -strong is for 'large tone-ramped glyphs ONLY' and " +
      "that the base pair is 'sized for 10-13px mono figures'. Rendered " +
      "side by side at 11px in Geist Mono, -strong is plainly green and red " +
      "and nothing like ink — that caution is overstated, and it was pointing " +
      "the app at a tone that fails AA. Report upstream; do not re-invert.\n\n" +
      "NOT banned: -bar (a bar is a graphical object at a 3:1 bar, and the bar " +
      "ramp is tuned so equal lengths read equally loud) and -wash (a ground).",
    bad: /\btext-(pos|neg)(?![-\w])/g,
    // Prose ABOUT the tokens, not a class on an element. `signColor` in
    // MethodologyContent quotes the old value while explaining the rule.
    except: ["web/components/methodology/MethodologyContent.tsx"],
  },
  {
    id: "row-rules",
    why:
      "INVERTED. A solid panel has no stripe, and the stripe WAS the divider, " +
      "so every table now REQUIRES explicit row borders. divide-y is no longer " +
      "banned — what is banned is the retired striped ground.",
    bad: /\bclassName=(?:"|'|`)[^"'`]*\bruled\b/g,
  },
  {
    id: "retired-primitives",
    why:
      "Importing a retired primitive is being on the old system, whatever the " +
      "call site looks like. The class-name rules above cannot see this: the " +
      "banned string lives inside Ruled.tsx, so a consumer that imports it " +
      "passes every other rule while rendering the striped ground. That is how " +
      "app/account/page.tsx got marked converted when it was not.\n\n" +
      "components/agate/ is now DELETED, so this rule is a tripwire against it " +
      "coming back — by a revert, a stale branch, or a copy-paste from git " +
      "history. Ruled/Rule are Panel/Row; Icon is Mark; Button, StateMessage " +
      "and IndeterminateBar all have furniture/ equivalents.",
    bad: /from\s+["'][^"']*agate\/\w+["']/g,
  },

  /* ---- SURVIVE FROM AGATE ---- */
  {
    id: "retired-well",
    why:
      "The pill-in-a-well is RETIRED AS A CONTROL. SegmentControl was a sunk " +
      "`--surface-sunk` track with a stamp-filled pill riding in it: 44px of " +
      "pill plus 3px of well each side, usually behind a whisper label. " +
      "Controls arrive in pairs — the production chart spent 120px on two of " +
      "them before drawing a data point — so it is an underline run now, and " +
      "the stamp moved from a fill behind the active label to a 2px rule " +
      "under it.\n\n" +
      "THE RULE IS KEYED ON INTERACTIVITY, NOT ON A FILE LIST, and that is " +
      "the whole design. `furniture/StageLadder.tsx` still draws the well " +
      "— deliberately (it replaced WindowSection.tsx's StageRail, which was " +
      "deleted with the retired window model). It is a READOUT (five ordered " +
      "stages, current one " +
      "marked, plain <span>s with no onClick/role/tabIndex), and now that no " +
      "filter looks like this, the well is what tells a reader this is a " +
      "state rather than something to tap. An underline there would invite a " +
      "click that does nothing. `.design/components/data/WindowCell.jsx` is " +
      "the authoritative drawing for that fact.\n\n" +
      "So the well is permitted by WHAT IT IS, not by what file it is in: put " +
      "a <button> or a <Link> inside one and this fires. An `except` entry " +
      "would have exempted the file forever, including a future control " +
      "someone adds to it.",
    bad: /(?:rounded-pill[^>]*bg-surface-sunk|bg-surface-sunk[^>]*rounded-pill)[\s\S]{0,400}?<(?:button|Link)\b/g,
  },
  {
    id: "sticky",
    why:
      "Nothing is fixed or sticky. Confirmed 13 Aug: no pinned mobile nav.\n\n" +
      "One sanctioned exception: a hover/focus-toggled floating popover that must " +
      "stay on-screen near a viewport edge, never a persistently pinned nav or " +
      "header. `InfoTooltip.tsx` and `DraftGoingIn.tsx`'s mobile `.going-in-tooltip` " +
      "variant both position with a bare `fixed` class and the offsets in an inline " +
      "`style` prop instead of a directional utility class — which is real " +
      "`position: fixed`, verified live in a mobile pass, but reads clean here " +
      "because this rule's regex only catches the PINNED-NAV IDIOM'S SPELLING " +
      "(fixed/sticky directly adjacent to a directional utility class), not the " +
      "property itself: `fixed inset-x-0 bottom-0` on an always-visible nav bar " +
      "would also read clean and would also be exactly what this rule exists to " +
      "stop. Don't read a green run here as proof nothing on the page is pinned — " +
      "and don't 'fix' InfoTooltip/DraftGoingIn's popovers by reverting them to " +
      "directional-utility classes; that swaps a real exception for one this " +
      "rule can no longer see.",
    bad: /\b(sticky|fixed)\s+(top|bottom|left|right)-/g,
  },
  {
    id: "lucide",
    why:
      "The 19 marks are drawn, not imported. All 19 exist redrawn and rounded " +
      "in the design system's icons set, same names, stroked, 16px grid.",
    bad: /from\s+["']lucide-react["']/g,
  },
  {
    id: "animate-pulse",
    why: "Loading is one indeterminate bar per view, never a skeleton shimmer.",
    bad: /\banimate-pulse\b/g,
  },
  {
    id: "backdrop-blur",
    why: "No blur, no translucency. Nothing in Furniture needs it.",
    bad: /\bbackdrop-blur\b/g,
  },
  {
    id: "overflow-x-auto",
    why:
      "Data is never hidden behind a sideways scroll. On a phone an entry " +
      "becomes a CARD; every column survives. There are NO exceptions left: " +
      "the three that existed were all the year line, and the year line is a " +
      "wrapping pill-in-a-well SegmentControl now, so the reason expired.",
    bad: /\boverflow-x-auto\b/g,
  },
  {
    id: "ktc",
    why: 'Never render "KTC" in the interface. It is "Trade Value", always.',
    bad: /\bKTC\b/g,
    // Code only, and the reasoning was corrected here: this rule exists to stop
    // the term REACHING THE UI, and only a string literal can do that — a
    // comment cannot render. Scanning prose too was over-reach, and it fired on
    // `lib/receipts.ts`, whose comment states the rule ("the string never
    // appears — it is Trade Value"). A file must be able to document the rule
    // it obeys.
    except: ["web/lib/ktc.ts", "web/lib/providers/ktc-client.ts"],
  },

  /* ---- NEW: TOKEN MISUSE THAT SHIPPED REAL CONTRAST FAILURES ---- */
  {
    id: "reversed-alpha",
    why:
      "A second line reversed out of a saturated ground needs --stamp-ink-dim. " +
      "rgba(255,255,255,.72) measures 3.97:1 at 9px, and small reversed type " +
      "gets no large-text exemption. Never an alpha of a reversed ink.",
    // Two spellings of the same mistake. The second was found in the real
    // masthead: `text-stamp-ink/70` is a Tailwind opacity modifier, so it never
    // produces the literal rgba() the first pattern looks for, and the defect
    // shipped under a rule written to prevent exactly it.
    bad: /rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.[0-8]|\bstamp-ink\/\d{1,2}\b/g,
  },
  {
    id: "ink-on-wash",
    why:
      "--stamp-ink is the ink for the SOLID cobalt fill, i.e. white. On " +
      "--stamp-wash it measures 1.13:1. Text on any wash takes the -strong " +
      "half of the pair: {stamp,pos,neg,warn}-strong.",
    bad: /--stamp-wash[^;]*;[^}]*--stamp-ink\b(?!-dim)/g,
  },
  {
    id: "raw-hex",
    why:
      "Colour values live in the design system's tokens, which ship into this " +
      "repo as generated files. A literal hex in a component is drift by " +
      "definition — it cannot be changed from the one place that owns it.",
    bad: /#[0-9a-fA-F]{6}\b/g,
    except: ["web/app/globals.css", "web/lib/og-card.tsx", "web/lib/og-font.ts"],
  },
  {
    id: "identity-as-stroke",
    why:
      "A fill ramp is not a stroke ramp. --id-1..6 are fills (chips, avatars, " +
      "edges); as a 1-3px line on white only two of six clear the 3:1 that " +
      "WCAG 1.4.11 asks of a graphical object. Any polyline, axis stub, " +
      "scatter mark or connector takes --id-N-line.",
    bad: /stroke=\{?["'`]?var\(--id-[1-6]\)/g,
  },
];

describe("Furniture drift guard", () => {
  it("has something to check", () => {
    if (SCOPED_DIRS.length === 0 && SCOPED_FILES.length === 0) {
      console.warn(
        "[furniture-guard] SCOPED_DIRS is empty — the guard is inert. Add each " +
          "directory as it is converted."
      );
      return;
    }
    // A non-empty SCOPED_DIRS that yields no files is the silent-failure mode:
    // every rule below would pass over an empty list and report green. This
    // caught exactly that — the walk resolved against vitest's CWD (`web/`)
    // instead of the repo root, so `web/components/...` found nothing.
    expect(
      files.length,
      `SCOPED_DIRS/SCOPED_FILES list ${SCOPED_DIRS.length} director${
        SCOPED_DIRS.length === 1 ? "y" : "ies"
      } and ${SCOPED_FILES.length} file(s) but the walk found nothing. The ` +
        `guard is reporting green without reading anything. ` +
        `reading anything. Check the paths are repo-relative and that walk() ` +
        `resolves them against the repo root, not the CWD.`
    ).toBeGreaterThan(0);
  });

  for (const rule of RULES) {
    it(rule.id, () => {
      const hits: string[] = [];
      for (const f of files) {
        if (rule.except?.some((e) => f.path.endsWith(e))) continue;
        const m = (rule.scanRaw ? f.src : f.code).match(rule.bad);
        if (m) hits.push(`${f.path}: ${[...new Set(m)].join(", ")}`);
      }
      expect(hits, `\n${rule.why}\n\n${hits.join("\n")}\n`).toEqual([]);
    });
  }

  /**
   * Every rule must still bite. Comment-stripping made the scan cleverer, and a
   * clever scan is one edit away from a scan that matches nothing — which fails
   * open, silently, exactly like the CWD bug did. Each entry is a snippet that
   * MUST be caught; if a regex is loosened or the stripper eats too much, this
   * goes red instead of the guard quietly passing everything.
   */
  const MUST_CATCH: Record<string, string> = {
    radius: 'className="rounded-lg"',
    "adhoc-size": 'className="text-[13px]"',
    elevation: 'className="shadow-md"',
    "tone-contrast": 'className="text-pos tabular"',
    "row-rules": 'className="ruled block"',
    "retired-well":
      '<div className="rounded-pill bg-surface-sunk p-[3px]"><button type="button">All</button>',
    "retired-primitives": 'import { Icon } from "./agate/Icon";',
    sticky: 'className="sticky top-0"',
    lucide: 'import { Sun } from "lucide-react";',
    "animate-pulse": 'className="animate-pulse"',
    "backdrop-blur": 'className="backdrop-blur-sm"',
    "overflow-x-auto": 'className="overflow-x-auto"',
    ktc: "the KTC value",
    "reversed-alpha": 'className="text-stamp-ink/70"',
    "ink-on-wash": "background: var(--stamp-wash); color: var(--stamp-ink);",
    "raw-hex": "color: #2f42ff;",
    "identity-as-stroke": 'stroke={"var(--id-2)"}',
  };

  for (const rule of RULES) {
    it(`${rule.id} — still catches its own pattern`, () => {
      const sample = MUST_CATCH[rule.id];
      expect(sample, `no MUST_CATCH sample for rule "${rule.id}"`).toBeTruthy();
      const scanned = rule.scanRaw ? sample : stripComments(sample);
      expect(
        scanned.match(rule.bad),
        `Rule "${rule.id}" no longer matches a known violation. It is failing ` +
          `open: every scoped file will pass it regardless of content.`
      ).not.toBeNull();
    });
  }

  it("port is not silently declared finished", () => {
    if (UNSCOPED.length === 0 && SCOPED_DIRS.length === 0 && SCOPED_FILES.length === 0) {
      throw new Error("Both lists are empty — the guard checks nothing.");
    }
    expect(true).toBe(true);
  });
});
