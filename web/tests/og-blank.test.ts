import { describe, it, expect } from "vitest";
import { BLANK_CARD_PNG_B64, BLANK_CARD_SIZE } from "@/lib/og-blank";

/**
 * The last-resort card, checked as bytes.
 *
 * `ogImage` serves this when `loadFonts()` throws — Satori needs a registered
 * face for every text node, so in that branch there is nothing else the route
 * can produce. Which makes it the one branch that must not itself be broken,
 * and the one branch nothing would otherwise exercise: it only runs during an
 * outage, so a truncated or mistyped base64 literal would surface for the first
 * time at the worst possible moment, as a second failure stacked on the first.
 *
 * So: decode it and read its own header. A PNG states its dimensions in the
 * IHDR chunk — bytes 16-23, big-endian — which is independent of anything this
 * repo wrote down about it.
 */
describe("blank OG card", () => {
  const bytes = Buffer.from(BLANK_CARD_PNG_B64, "base64");

  it("decodes to a real PNG", () => {
    expect(bytes.subarray(0, 8)).toEqual(
      Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    );
    expect(bytes.subarray(12, 16).toString("ascii")).toBe("IHDR");
    // A well-formed PNG ends with the IEND chunk — this is what catches a
    // literal that was truncated on paste rather than merely wrong.
    expect(bytes.subarray(bytes.length - 8, bytes.length - 4).toString("ascii")).toBe("IEND");
  });

  it("is the card canvas, not some other image", () => {
    expect(bytes.readUInt32BE(16)).toBe(BLANK_CARD_SIZE.width);
    expect(bytes.readUInt32BE(20)).toBe(BLANK_CARD_SIZE.height);
    // 1200x630 is the OG canvas every crawler expects; a mismatch here means a
    // link unfurls letterboxed or cropped.
    expect(BLANK_CARD_SIZE).toEqual({ width: 1200, height: 630 });
  });

  it("stays small enough to be a cheap failure path", () => {
    // It is a solid fill, so it compresses to a few KB. If this ever balloons,
    // someone has replaced it with a real image — which reintroduces the font
    // dependency this branch exists to escape.
    expect(bytes.length).toBeLessThan(20_000);
  });
});
