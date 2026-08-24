import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OverviewTab } from "../../components/ownerdeepdive/OverviewTab";
import { OwnerDetailResp } from "../../lib/types";
import { pillar } from "../helpers";

const BASE_DETAIL: Omit<OwnerDetailResp, "franchise_rating"> = {
  league_id: "L",
  user_id: "u_a",
  owner: { user_id: "u_a", owner_name: "Alice" },
  totals_by_lens: { ktc: 0, production: 0, regular: 0, playoff: 0, toilet: 0 },
  career_arc: [],
  trades: [],
  best_trade_id: null,
  worst_trade_id: null,
};

describe("OverviewTab — Why this grade total row (Figures Reconcile)", () => {
  it("computes the total from the SAME contribution figures the pillar rows render, not a hardcoded or re-derived value", () => {
    // pillar() defaults to no signals, so exactly two signed pillar-level
    // figures render (v2: results/assets) — no signal rows to confuse the
    // sum with.
    const detail: OwnerDetailResp = {
      ...BASE_DETAIL,
      franchise_rating: {
        letter: "B+",
        rating: 1590,
        rank: 2,
        of: 12,
        trend: 1,
        pillars: { results: pillar(50), assets: pillar(40) },
      },
    };
    const { container } = render(<OverviewTab detail={detail} />);

    // Read every signed pillar figure directly off the rendered DOM — this is
    // the assertion the rule requires: the total must equal what the rows
    // ABOVE IT actually render, not a value trusted from the test fixture.
    const signedFigures = Array.from(container.querySelectorAll("span"))
      .map((el) => el.textContent?.trim() ?? "")
      .filter((t) => /^[+-]\d+$/.test(t));
    expect(signedFigures).toEqual(["+50", "+40"]);
    const renderedSum = signedFigures.reduce((acc, t) => acc + parseInt(t, 10), 0);
    const expectedTotal = 1500 + renderedSum;

    expect(screen.getByText(/Base 1,500 \+ two pillars/)).toBeInTheDocument();
    expect(container.textContent).toContain(expectedTotal.toLocaleString());
    // Exact match here (1500 + 50 + 40 = 1590 = fr.rating) — no rounding
    // gap, so no reconciliation note should render.
    expect(expectedTotal).toBe(1590);
    expect(container.textContent).not.toContain("rounds to");
  });

  it("shows the rows' own sum — and names the gap — when gm_rating.py's independent per-pillar rounding leaves the sum a point off the headline rating", () => {
    const detail: OwnerDetailResp = {
      ...BASE_DETAIL,
      franchise_rating: {
        letter: "A+",
        rating: 1917, // one off 1500 + 295 + 121 = 1916 by rounding
        rank: 1,
        of: 12,
        trend: 0,
        pillars: { results: pillar(295), assets: pillar(121) },
      },
    };
    const { container } = render(<OverviewTab detail={detail} />);

    // The total row must show what the rows actually sum to (1,916) — never
    // silently substitute the headline rating (1,917) — and must say the two
    // disagree rather than paper over it.
    expect(container.textContent).toContain("1,916");
    expect(container.textContent).toContain("rating shown above rounds to 1,917");
  });
});
