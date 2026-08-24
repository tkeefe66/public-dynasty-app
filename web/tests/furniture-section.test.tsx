import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Section } from "@/components/furniture/Section";

/**
 * Mutation this catches: deleting `...rest` from Section's signature.
 *
 * That mutation type-checks, compiles and builds — the attribute is simply
 * dropped at runtime. Phase 5 lost a debugging round to exactly that, because
 * the panel rendered correctly and only the test query failed.
 */
describe("Section", () => {
  it("forwards arbitrary props, as every sibling primitive does", () => {
    render(<Section data-testid="probe" aria-label="Going in">x</Section>);
    const el = screen.getByTestId("probe");
    expect(el.tagName).toBe("SECTION");
    expect(el.getAttribute("aria-label")).toBe("Going in");
  });

  it("still applies its own className alongside forwarded props", () => {
    render(<Section data-testid="probe" className="extra">x</Section>);
    expect(screen.getByTestId("probe").className).toMatch(/\bmb-6\b.*\bextra\b/);
  });
});
