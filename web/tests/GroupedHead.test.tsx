import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { GroupedHead } from "@/components/furniture/GroupedHead";

/**
 * `GroupedHead` is the two-tier ledger head. Its whole contract is arithmetic:
 * the spans must cover the tracks, or every cap after the short one sits over
 * the wrong columns. That failure looks like a styling bug, so it is guarded
 * here rather than left to a visual review.
 */

const COLS = "66px 84px minmax(140px,420px) 60px 72px 66px 72px 74px 56px 60px";

const GROUPS = [
  { span: 3 },
  { span: 2, label: "Baseline" },
  { span: 1, label: "Verdict" },
  { span: 3, label: "Points" },
  { span: 1, label: "Now" },
];

function labels() {
  return Array.from({ length: 10 }, (_, i) => <span key={i}>{`c${i}`}</span>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GroupedHead", () => {
  it("emits one spanning columnheader per group, capless groups included", () => {
    render(
      <div role="table">
        <GroupedHead cols={COLS} groups={GROUPS}>
          {labels()}
        </GroupedHead>
      </div>,
    );

    // The naming tier is the first of the two header rows.
    const rows = screen.getAllByRole("row");
    const namingTier = rows[0];
    const caps = within(namingTier).getAllByRole("columnheader");

    expect(caps).toHaveLength(GROUPS.length);
    expect(caps.map((c) => c.getAttribute("aria-colspan"))).toEqual([
      "3",
      "2",
      "1",
      "3",
      "1",
    ]);
    // The capless group is present and empty — it is what keeps every later
    // cap over its own columns.
    expect(caps[0]).toHaveTextContent("");
    expect(caps.map((c) => c.textContent)).toEqual([
      "",
      "Baseline",
      "Verdict",
      "Points",
      "Now",
    ]);
  });

  it("draws the cap rule only under a labelled group", () => {
    render(
      <div role="table">
        <GroupedHead cols={COLS} groups={GROUPS}>
          {labels()}
        </GroupedHead>
      </div>,
    );
    const caps = within(screen.getAllByRole("row")[0]).getAllByRole(
      "columnheader",
    );
    expect(caps[0].className).not.toMatch(/border-rule-strong/);
    expect(caps[1].className).toMatch(/border-b border-rule-strong/);
  });

  it("repeats cols verbatim on both tiers", () => {
    render(
      <div role="table">
        <GroupedHead cols={COLS} groups={GROUPS}>
          {labels()}
        </GroupedHead>
      </div>,
    );
    const [namingTier, labelTier] = screen.getAllByRole("row");
    expect(namingTier.style.gridTemplateColumns).toBe(COLS);
    expect(labelTier.style.gridTemplateColumns).toBe(COLS);
  });

  it("keeps the label tier at the 44px SortButton target", () => {
    render(
      <div role="table">
        <GroupedHead cols={COLS} groups={GROUPS}>
          {labels()}
        </GroupedHead>
      </div>,
    );
    // min-h-tap is the 44px utility; losing it is what would silently shrink a
    // sort control's tap target below the floor.
    expect(screen.getAllByRole("row")[1].className).toMatch(/\bmin-h-tap\b/);
  });

  it("wraps both tiers in a rowgroup so the rows keep their parentage", () => {
    render(
      <div role="table">
        <GroupedHead cols={COLS} groups={GROUPS}>
          {labels()}
        </GroupedHead>
      </div>,
    );
    expect(screen.getByRole("rowgroup")).toBeTruthy();
  });

  it("warns when the spans do not cover the tracks", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(
      <div role="table">
        {/* 9, not 10 — the classic short sum */}
        <GroupedHead cols={COLS} groups={[{ span: 3 }, { span: 6 }]}>
          {labels()}
        </GroupedHead>
      </div>,
    );
    expect(warn).toHaveBeenCalledOnce();
    expect(warn.mock.calls[0][0]).toMatch(/spans sum to 9 but cols declares 10/);
  });

  it("stays quiet when the arithmetic holds", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(
      <div role="table">
        <GroupedHead cols={COLS} groups={GROUPS}>
          {labels()}
        </GroupedHead>
      </div>,
    );
    expect(warn).not.toHaveBeenCalled();
  });

  it("counts a track written with spaces inside its function as one", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    // `minmax(0, 1fr)` is two tokens if you split on whitespace naively, and
    // the resulting warning would be a false alarm on correct code.
    render(
      <div role="table">
        <GroupedHead
          cols="60px minmax(0, 1fr) 60px"
          groups={[{ span: 1 }, { span: 2, label: "Points" }]}
        >
          <span>a</span>
          <span>b</span>
          <span>c</span>
        </GroupedHead>
      </div>,
    );
    expect(warn).not.toHaveBeenCalled();
  });
});
