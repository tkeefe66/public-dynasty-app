import { describe, it, expect } from "vitest";
import { LETTER_BANDS as UI_BANDS } from "@/components/methodology/MethodologyContent";
import bands from "../.generated/letter-bands.json";

/* ---------------------------------------------------------------------------
 * web/.generated/letter-bands.json is produced by scripts/gen_letter_bands.py
 * from the engine's gm_rating.LETTER_BANDS, not hand-copied -- hand-copying
 * this table into TypeScript with no import and no test is exactly how the
 * methodology page went stale for the v2 rating rebuild.
 *
 * This test does NOT detect engine drift. `LETTER_BANDS` in
 * MethodologyContent.tsx is a straight re-export of this same JSON file, so
 * this assertion compares the file to itself -- it is structurally
 * guaranteed to pass as long as the import resolves at all. What it actually
 * guards is narrower: it is a TRIPWIRE against someone later deleting that
 * re-export and pasting a hand-typed array back in here, which would silently
 * restore the exact defect this file exists to prevent.
 *
 * The real cross-language drift check -- the one that fails when
 * gm_rating.py's bands change and nobody regenerates this JSON -- is
 * tests/test_letter_bands_export.py (pytest), which compares the checked-in
 * JSON against the LIVE engine array. That test, not this one, is what stops
 * the page from quietly disagreeing with gm_rating.py.
 * ------------------------------------------------------------------------ */
describe("methodology letter bands", () => {
  it("MethodologyContent re-exports the generated JSON verbatim (tripwire against a hand-typed array)", () => {
    expect(UI_BANDS).toEqual(bands);
  });
});
