import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import path from "path";
import { extractFontUrl, geistMonoUrl, REGISTERED_FONTS } from "@/lib/og-font";

describe("extractFontUrl", () => {
  it("pulls the ttf src out of a Google Fonts CSS block (display 800)", () => {
    const css = `@font-face{font-family:'Bricolage Grotesque';font-style:normal;font-weight:800;` +
      `font-stretch:normal;` +
      `src:url(https://fonts.gstatic.com/s/bricolagegrotesque/v9/abc.ttf) format('truetype');}`;
    expect(extractFontUrl(css)).toBe(
      "https://fonts.gstatic.com/s/bricolagegrotesque/v9/abc.ttf",
    );
  });
  it("returns null when no ttf url is present", () => {
    expect(extractFontUrl("@font-face{src:url(x.woff2) format('woff2');}")).toBeNull();
  });
});

describe("geistMonoUrl", () => {
  it("points at the jsdelivr npm mirror for the installed geist version", () => {
    expect(geistMonoUrl("Regular")).toBe(
      "https://cdn.jsdelivr.net/npm/geist@1.3.1/dist/fonts/geist-mono/GeistMono-Regular.ttf",
    );
    expect(geistMonoUrl("Bold")).toBe(
      "https://cdn.jsdelivr.net/npm/geist@1.3.1/dist/fonts/geist-mono/GeistMono-Bold.ttf",
    );
  });

  /**
   * THE DRIFT THIS FILE COULD NOT SEE. The literal above guards `GEIST_VERSION`
   * against being edited, but not against the package moving underneath it:
   * `package.json` pins geist with a **caret**, so an ordinary `npm install`
   * can bring 1.4.x while the constant — and therefore the card's TTF — stays
   * on 1.3.1. Nothing failed. The app's own faces come from the installed
   * package (`geist/font` in `app/layout.tsx`) and update automatically, so
   * only the card's copy is hand-pinned, and the symptom is a card set in a
   * different cut of the same family from the app. That is not something a
   * green suite or a code review notices.
   *
   * Reading the INSTALLED version is what closes it: this goes red the moment
   * the two diverge, whichever one moved.
   */
  it("stays pinned to the geist version actually installed", () => {
    const installed = JSON.parse(
      readFileSync(path.join(process.cwd(), "node_modules/geist/package.json"), "utf8"),
    ).version as string;
    expect(geistMonoUrl("Regular")).toContain(`geist@${installed}/`);
  });
});


describe("registered fonts cover what the cards ask for", () => {
  /* Satori does not error on an unregistered family/weight — it substitutes
   * another face and renders a card that looks subtly wrong, which no test and
   * no build catches. The display face's 700 was missing for exactly that
   * reason once: three call sites asked for it and silently got the heavier cut.
   * This scans the renderer for every pair it sets and requires each one to be
   * registered — which is also what catches a family RENAME (Archivo →
   * Bricolage Grotesque) that lands in og-font.ts but not in og-card.tsx. */
  it("has a registered face for every fontFamily+fontWeight pair in og-card.tsx", () => {
    const src = readFileSync(
      path.resolve(__dirname, "../lib/og-card.tsx"),
      "utf8",
    );
    // Only lines carrying BOTH a family and a weight are unambiguous; a bare
    // `fontWeight` inherits its family from an ancestor.
    const pairs = new Set<string>();
    for (const line of src.split("\n")) {
      const fam = line.match(/fontFamily:\s*"([^"]+)"/);
      const wgt = line.match(/fontWeight:\s*(\d+)/);
      if (fam && wgt) pairs.add(`${fam[1]}@${wgt[1]}`);
    }
    expect(pairs.size).toBeGreaterThan(0); // the scan must actually find pairs
    const registered = new Set(REGISTERED_FONTS.map((f) => `${f.name}@${f.weight}`));
    const missing = [...pairs].filter((p) => !registered.has(p));
    expect(
      missing,
      "og-card.tsx renders these with no registered face, so Satori will " +
        `substitute silently: ${missing.join(", ")}`,
    ).toEqual([]);
  });
});
