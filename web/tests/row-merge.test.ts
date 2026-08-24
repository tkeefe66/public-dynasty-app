import { describe, it, expect } from "vitest";
import { mergeClasses } from "@/components/furniture/Row";

/**
 * `Row` supplies its own layout utilities, and callers routinely need to
 * override one of them. Two Tailwind utilities of the same family have equal
 * specificity, so the winner is decided by their order in the GENERATED
 * stylesheet — not by className order. `gap-4` happens to beat `gap-2.5` only
 * because 4 sorts after 2.5 in the spacing scale; change either value and the
 * result silently flips. mergeClasses removes the ambiguity by dropping the
 * base class instead of racing it.
 */
describe("mergeClasses", () => {
  it("drops the base class from a family the caller overrides", () => {
    const out = mergeClasses("grid gap-2.5 px-3.5 text-figure", "gap-4");
    expect(out).not.toMatch(/\bgap-2\.5\b/);
    expect(out).toMatch(/\bgap-4\b/);
    // untouched families survive
    expect(out).toMatch(/\bpx-3\.5\b/);
    expect(out).toMatch(/\btext-figure\b/);
  });

  it("keeps base classes the caller says nothing about", () => {
    expect(mergeClasses("grid gap-2.5 px-3.5", "items-start")).toMatch(/gap-2\.5/);
  });

  it("does not treat grid-cols-* as an override of grid", () => {
    // The word boundary in a naive \bgrid\b matches at the hyphen, which would
    // strip `grid` itself and collapse the row to a block.
    const out = mergeClasses("grid items-center", "grid-cols-[20px_1fr]");
    expect(out).toMatch(/(^|\s)grid(\s|$)/);
    expect(out).toMatch(/grid-cols-\[20px_1fr\]/);
  });

  it("lets a RESPONSIVE override coexist with the unconditional base", () => {
    // `min-[701px]:px-2` applies only above the breakpoint; dropping the base
    // `px-3.5` would leave the row with no padding on a phone.
    const out = mergeClasses("px-3.5 gap-2.5", "min-[701px]:px-2");
    expect(out).toMatch(/\bpx-3\.5\b/);
    expect(out).toMatch(/min-\[701px\]:px-2/);
  });

  it("handles an empty override", () => {
    expect(mergeClasses("grid px-3.5", "")).toBe("grid px-3.5");
  });

  it("puts overrides last so equal-family duplicates still read left-to-right", () => {
    expect(mergeClasses("text-dim", "text-ink").trim().endsWith("text-ink")).toBe(true);
  });
});
