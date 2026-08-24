import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SegmentControl } from "../components/SegmentControl";

const OPTIONS = [
  { key: "all", label: "All" },
  { key: "2024", label: "'24" },
  { key: "2023", label: "'23" },
];

describe("SegmentControl", () => {
  it("renders a labelled group with one button per option", () => {
    render(
      <SegmentControl aria-label="Filter by year" options={OPTIONS} value="all" onChange={() => {}} />,
    );
    expect(screen.getByRole("group", { name: "Filter by year" })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });

  it("marks only the active option aria-pressed", () => {
    render(
      <SegmentControl aria-label="Filter by year" options={OPTIONS} value="2024" onChange={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "'24" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "'23" })).toHaveAttribute("aria-pressed", "false");
  });

  it("reports the clicked option's key", () => {
    const onChange = vi.fn();
    render(
      <SegmentControl aria-label="Filter by year" options={OPTIONS} value="all" onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "'23" }));
    expect(onChange).toHaveBeenCalledWith("2023");
  });

  it("supports numeric keys", () => {
    const onChange = vi.fn();
    render(
      <SegmentControl<number>
        aria-label="Pick a season"
        options={[{ key: 2024, label: "2024" }, { key: 2023, label: "2023" }]}
        value={2024}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "2023" }));
    expect(onChange).toHaveBeenCalledWith(2023);
  });

  /* INVERTED TWICE, and the intent — "this control wears the house shape" —
   * is what survived both times. Agate: a hard-cornered box with hairlines
   * between items, zero radius, in a system that had no radius at all.
   * Furniture's first draft: a pill in a sunk well. Now: an underline run,
   * because the well and pill cost 50px per control and controls arrive in
   * pairs (the production chart spent 120px on two of them).
   *
   * The stamp is still here, still one of the five sanctioned slots — it moved
   * from a FILL behind the active label to a 2px rule under it. */
  it("draws an underline run — no well, active option inked and stamp-underlined", () => {
    const { container } = render(
      <SegmentControl aria-label="Filter by year" options={OPTIONS} value="2024" onChange={() => {}} />,
    );
    const group = screen.getByRole("group", { name: "Filter by year" });
    expect(group.className, "the well is gone").not.toMatch(/bg-surface-sunk/);
    expect(group.className, "the run wraps rather than scrolling").toMatch(/flex-wrap/);

    const active = screen.getByRole("button", { name: "'24" });
    expect(active.className, "the active option takes the stamp underline").toMatch(/after:bg-stamp/);
    expect(active.className, "…and full ink, so the cue is not colour alone").toMatch(/text-ink/);

    const inactive = screen.getByRole("button", { name: "All" });
    expect(inactive.className, "an inactive option carries no stamp").not.toMatch(/after:bg-stamp/);
    expect(inactive.className, "inactive is dim, not merely unbolded").toMatch(/text-dim/);
  });

  /* The trap this control is most likely to fall into: shrinking the TARGET
   * along with the paint. The run is ~24px of ink; the hit area is a
   * transparent box at -11px/-8px, which clears the system's 44px floor. */
  it("keeps a 44px tap target behind the 24px run", () => {
    const { container } = render(
      <SegmentControl aria-label="Filter by year" options={OPTIONS} value="all" onChange={() => {}} />,
    );
    for (const btn of container.querySelectorAll("button")) {
      expect(btn.className, "every option carries the invisible tap box")
        .toMatch(/before:-inset-y-\[11px\]/);
    }
  });
});
