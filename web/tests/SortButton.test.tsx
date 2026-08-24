import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SortButton } from "@/components/furniture/SortButton";

describe("SortButton", () => {
  // `aria-sort` is only valid on columnheader/rowheader/gridcell — on
  // role="button" the accessibility layer drops it, which is exactly how
  // the draft board shipped with no sort state announced at all. It now
  // lives on the WRAPPING columnheader cell (`DraftBoard.tsx`'s
  // `DefinedHeader`/inline identity cells), never on this button — this is
  // the regression guard for that split staying put.
  it("never puts aria-sort on the button itself, in any state", () => {
    render(<SortButton sort="descending">Total</SortButton>);
    expect(screen.getByRole("button").hasAttribute("aria-sort")).toBe(false);
  });

  it("builds an accessible name naming the column and the current direction", () => {
    render(<SortButton sort="descending">Total</SortButton>);
    expect(screen.getByRole("button").getAttribute("aria-label")).toBe(
      "Sort by Total, currently descending",
    );
  });

  it("omits the direction clause from the accessible name while unsorted", () => {
    render(<SortButton>Total</SortButton>);
    expect(screen.getByRole("button").getAttribute("aria-label")).toBe("Sort by Total");
  });

  it("repeats uppercase on the button itself", () => {
    // Tailwind preflight sets text-transform:none on <button>, so inheriting
    // the head row's `uppercase` is NOT enough — this is the bug that split
    // the standings header in two.
    render(<SortButton>Total</SortButton>);
    expect(screen.getByRole("button").className).toMatch(/\buppercase\b/);
  });

  it("keeps the 44px target on the button, not the row", () => {
    render(<SortButton>Total</SortButton>);
    expect(screen.getByRole("button").className).toMatch(/\bmin-h-tap\b/);
  });

  it("fires onClick", async () => {
    const onClick = vi.fn();
    const { default: userEvent } = await import("@testing-library/user-event");
    render(<SortButton onClick={onClick}>Total</SortButton>);
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("right-aligns a numeric column across the full cell", () => {
    render(<SortButton align="right">Total</SortButton>);
    const cn = screen.getByRole("button").className;
    expect(cn).toMatch(/\bjustify-end\b/);
    expect(cn).toMatch(/\bw-full\b/);
  });
});
