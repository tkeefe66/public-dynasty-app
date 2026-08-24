import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * `lib/og-card.tsx` inlines colour LITERALS because Satori cannot read CSS
 * custom properties. That means the share cards are the one surface in the app
 * where the design tokens are copied rather than referenced — and a copy drifts.
 *
 * It drifted for the entire Furniture port: the card kept Agate's palette
 * (`#f7f6f1` ground, `#141312` ink) while every screen moved to `#f4f3ef` /
 * `#14151a`, so a shared link rendered Furniture type on an Agate ground. The
 * file's own comment said "nothing enforces the match". This is that
 * enforcement.
 *
 * It reads the generated token file rather than restating values, so a
 * `.design/` sync that changes a colour fails HERE rather than silently
 * shipping a stale card.
 */
const ROOT = path.resolve(__dirname, "..", "..");
const tokens = readFileSync(path.join(ROOT, ".design/tokens/colors.css"), "utf8");
const card = readFileSync(path.join(ROOT, "web/lib/og-card.tsx"), "utf8");

/** The LIGHT value of a token — the first `:root` block, before any dark override. */
function lightToken(name: string): string {
  const light = tokens.slice(0, tokens.indexOf('[data-theme="dark"]'));
  const m = light.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!m) throw new Error(`token --${name} not found in .design/tokens/colors.css`);
  return m[1].toLowerCase();
}

function cardColor(key: string): string {
  const m = card.match(new RegExp(`\\b${key}:\\s*"(#[0-9a-fA-F]{6})"`));
  if (!m) throw new Error(`key ${key} not found in og-card.tsx's C object`);
  return m[1].toLowerCase();
}

/** card key → design token. `ruleLit` is `--surface`: under Agate a row sat on
 *  the lit stripe of a striped ground; under Furniture it sits on a solid panel. */
const PAIRS: [string, string][] = [
  ["bg", "bg"],
  ["ruleLit", "surface"],
  ["rule", "rule"],
  ["dim", "dim"],
  ["body", "body"],
  ["ink", "ink"],
  ["pos", "pos"],
  ["neg", "neg"],
];

describe("og-card palette tracks the design tokens", () => {
  for (const [key, token] of PAIRS) {
    it(`C.${key} === --${token}`, () => {
      expect(
        cardColor(key),
        `og-card.tsx's C.${key} has drifted from --${token}. Satori cannot read ` +
          `CSS variables, so this copy is deliberate — but it must be re-synced ` +
          `by hand whenever .design/tokens/colors.css changes.`
      ).toBe(lightToken(token));
    });
  }

  it("carries no retired Agate colour", () => {
    // The exact values the card shipped with through the whole port.
    const retired = ["#f7f6f1", "#fdfcf8", "#ddddd6", "#62615c", "#3d3c38", "#141312", "#15803d", "#b91c1c"];
    const found = retired.filter((hex) => card.toLowerCase().includes(hex));
    expect(found, `retired Agate colours still present: ${found.join(", ")}`).toEqual([]);
  });
});
