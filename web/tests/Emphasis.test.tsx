import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Emphasis, EMPHASIS_KINDS, isEmphasisKind } from "../components/furniture/Emphasis";

/** The four treatments are the whole design, so each is asserted by the token
 *  it must resolve to rather than by "it rendered something". A fifth colour
 *  creeping in, or `--pos` slipping in where `--pos-strong` belongs, is the
 *  regression this file exists to catch. */
describe("Emphasis — four marks, four treatments", () => {
  it("sets a figure in mono, tabular, ink, with the hairline under it", () => {
    render(<Emphasis kind="num">73%</Emphasis>);
    const el = screen.getByText("73%");
    const cls = el.className;
    expect(cls).toContain("font-mono");
    expect(cls).toContain("tabular");
    expect(cls).toContain("text-ink");
    expect(cls).toContain("font-semibold");
    // The second mark: a hairline, not a quieter tone.
    expect(cls).toContain("border-b-[1.5px]");
    expect(cls).toContain("border-rule");
  });

  it("sets a person in the prose face at weight, with no border", () => {
    render(<Emphasis kind="who">Jahmyr Gibbs</Emphasis>);
    const cls = screen.getByText("Jahmyr Gibbs").className;
    expect(cls).toContain("font-sans");
    expect(cls).toContain("font-semibold");
    expect(cls).toContain("text-ink");
    expect(cls).not.toContain("border-b");
    expect(cls).not.toContain("font-mono");
  });

  it("takes the -strong half of the valence pair, never the base tone", () => {
    render(
      <>
        <Emphasis kind="good">contention now</Emphasis>
        <Emphasis kind="risk">QB depth</Emphasis>
      </>,
    );
    const good = screen.getByText("contention now").className;
    const risk = screen.getByText("QB depth").className;
    expect(good).toContain("text-pos-strong");
    expect(risk).toContain("text-neg-strong");
    // The base pair fails AA as text on every light ground this app uses.
    expect(good).not.toMatch(/text-pos(?![-\w])/);
    expect(risk).not.toMatch(/text-neg(?![-\w])/);
  });

  it("carries no colour on the two non-valence marks", () => {
    render(
      <>
        <Emphasis kind="num">25</Emphasis>
        <Emphasis kind="who">Puka Nacua</Emphasis>
      </>,
    );
    for (const t of ["25", "Puka Nacua"]) {
      expect(screen.getByText(t).className).not.toMatch(/text-(pos|neg|stamp)/);
    }
  });

  it("names exactly four kinds — a fifth is a design decision, not a prop value", () => {
    expect([...EMPHASIS_KINDS]).toEqual(["num", "who", "good", "risk"]);
    expect(isEmphasisKind("num")).toBe(true);
    expect(isEmphasisKind("stamp")).toBe(false);
    expect(isEmphasisKind(null)).toBe(false);
    expect(isEmphasisKind(undefined)).toBe(false);
  });
});
