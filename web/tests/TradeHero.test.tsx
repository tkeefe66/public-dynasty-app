import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeHero } from "@/components/TradeHero";
import type { LensMargins, LensWinners, TradeSideView, TradeStory } from "@/lib/types";

// ---------- helpers ----------

function makeSide(
  overrides: Partial<TradeSideView> & { user_id: string; owner_name: string },
): TradeSideView {
  return {
    team_name: undefined,
    avatar_url: undefined,
    received: [],
    given: [],
    snapshot_ktc_swing: 0,
    received_ktc: 5000,
    production_total: 500,
    production_regular: 400,
    production_playoff: 100,
    production_toilet: 0,
    breakdown: [],
    production_started: 400,
    start_pct: 0.8,
    at_trade_ktc_swing: null,
    aged_ktc_swing: null,
    at_trade_approx: false,
    at_trade_snapshot_date: null,
    at_trade_standing: null,
    ...overrides,
  };
}

const sideA = makeSide({ user_id: "u1", owner_name: "Mikey" });
const sideB = makeSide({ user_id: "u2", owner_name: "Tom" });

const story: TradeStory = {
  verdict: "Mikey robbed Tom.",
  lede: "Tom flipped Bijan Robinson for Nick Chubb.",
  beats: ["Bijan became a workhorse RB1.", "Tom benched most of his haul."],
  body: "Tom flipped Bijan Robinson for Nick Chubb.\n\nMikey dominated.",
};

const NO_WINNERS: LensWinners = { value: null, total: null, regular: null, playoff: null, toilet: null };
const NO_MARGINS: LensMargins = { value: null, total: null, regular: null, playoff: null, toilet: null };

function unanimous(winner: string): { winnersByLens: LensWinners; marginsByLens: LensMargins } {
  return {
    winnersByLens: { value: winner, total: winner, regular: winner, playoff: winner, toilet: null },
    marginsByLens: { value: 8998, total: 304, regular: 248, playoff: 40, toilet: null },
  };
}

// ---------- tests ----------

describe("TradeHero — a one-lens result is not a sweep", () => {
  /** Before anyone plays, all four production lenses are 0 for BOTH sides, so
   *  `_lens_verdict` marks them unscored and only Trade Value is decided. That
   *  still yields `call: "unanimous"` — every decided lens went to one side —
   *  and the stamp used to render full-sweep language ("won it by …", badge
   *  "Edge"/"Lopsided") for a trade nobody had played a snap in. */
  const valueOnly = {
    winnersByLens: { value: "u1", total: null, regular: null, playoff: null, toilet: null } as LensWinners,
    marginsByLens: { value: 633, total: null, regular: null, playoff: null, toilet: null } as LensMargins,
  };

  const renderValueOnly = () =>
    render(
      <TradeHero
        date="2026-08-07"
        sides={[sideA, sideB]}
        story={null}
        lopsidedness={0.9}
        {...valueOnly}
        call="unanimous"
        lensTally="1-0"
      />,
    );

  it("says 'ahead by', never 'won it by'", () => {
    const { container } = renderValueOnly();
    expect(container.textContent).toContain("ahead by");
    expect(container.textContent).not.toContain("won it by");
  });

  it("badges the lens rather than Edge/Lopsided, even at high lopsidedness", () => {
    const { container } = renderValueOnly();
    expect(container.textContent).toContain("value only");
    // lopsidedness 0.9 would have produced "Lopsided" on the sweep branch.
    expect(container.textContent).not.toContain("Lopsided");
    expect(container.textContent).not.toContain("Edge");
  });

  it("still names who is ahead, and by how much", () => {
    const { container } = renderValueOnly();
    expect(container.textContent).toContain("Mikey");
    expect(container.textContent).toContain("633");
  });

  it("keeps full sweep language when the lenses really were swept", () => {
    const { container } = render(
      <TradeHero
        date="2025-09-24" sides={[sideA, sideB]} story={null} lopsidedness={0.8}
        {...unanimous("u1")} call="unanimous" lensTally="4-0"
      />,
    );
    expect(container.textContent).toContain("won it by");
    expect(container.textContent).not.toContain("value only");
  });
});

describe("TradeHero", () => {
  it("renders the date-only kicker (no case/record numbering)", () => {
    render(
      <TradeHero
        date="2025-09-24"
        sides={[sideA, sideB]}
        story={story}
        lopsidedness={0.8}
        {...unanimous("u1")}
        call="unanimous"
        lensTally="4-0"
      />,
    );
    expect(screen.getByText("Sep 24, 2025")).toBeTruthy();
  });

  it("renders the two owner names joined with V. as the headline", () => {
    render(
      <TradeHero
        date="2025-09-24"
        sides={[sideA, sideB]}
        story={story}
        lopsidedness={0.8}
        {...unanimous("u1")}
        call="unanimous"
        lensTally="4-0"
      />,
    );
    expect(screen.getByText("Mikey V. Tom")).toBeTruthy();
  });

  it("renders the verdict/lede/beats from the story", () => {
    render(
      <TradeHero
        date="2025-09-24"
        sides={[sideA, sideB]}
        story={story}
        lopsidedness={0.8}
        {...unanimous("u1")}
        call="unanimous"
        lensTally="4-0"
      />,
    );
    expect(screen.getByText("Tom flipped Bijan Robinson for Nick Chubb.")).toBeTruthy();
    expect(screen.getByText("Bijan became a workhorse RB1.")).toBeTruthy();
    expect(screen.getByText("Tom benched most of his haul.")).toBeTruthy();
  });

  it("renders body as paragraphs (fallback) when beats is absent", () => {
    const noBeatsStory: TradeStory = {
      verdict: "Mikey robbed Tom.",
      body: "Tom flipped Bijan for Chubb.\n\nMikey dominated.",
    };
    render(
      <TradeHero
        date="2025-09-24"
        sides={[sideA, sideB]}
        story={noBeatsStory}
        lopsidedness={0.8}
        {...unanimous("u1")}
        call="unanimous"
        lensTally="4-0"
      />,
    );
    expect(screen.getByText("Tom flipped Bijan for Chubb.")).toBeTruthy();
    expect(screen.getByText("Mikey dominated.")).toBeTruthy();
  });

  it("renders the receipt affordance", () => {
    render(
      <TradeHero
        date="2025-09-24"
        sides={[sideA, sideB]}
        story={story}
        lopsidedness={0.8}
        {...unanimous("u1")}
        call="unanimous"
        lensTally="4-0"
        receipt={<button>⧉ copy receipt</button>}
      />,
    );
    expect(screen.getByRole("button", { name: /copy receipt/i })).toBeInTheDocument();
  });

  // ---------- the ruling stamp: three states ----------

  describe("ruling stamp — unanimous", () => {
    it("names the single winner at headline size and the call as a footer", () => {
      const { container } = render(
        <TradeHero
          date="2025-09-24"
          sides={[sideA, sideB]}
          story={story}
          lopsidedness={0.8}
          {...unanimous("u1")}
          call="unanimous"
          lensTally="4-0"
        />,
      );
      expect(screen.getByText("Mikey")).toBeTruthy();
      expect(screen.getByText("Lopsided")).toBeTruthy();
      // states the margins in a plain sentence
      expect(screen.getByText(/won it by/i)).toBeTruthy();
      // the margin figures render in plain stamp-ink prose — no --pos/--neg
      // color inside the ruling card (DESIGN.md: signed color belongs on
      // ledger figures, not inside the stamp)
      expect(container.querySelector(".text-pos")).toBeNull();
      expect(container.querySelector(".text-neg")).toBeNull();
    });

    it("renders 'Edge' when lopsidedness is below 0.6", () => {
      render(
        <TradeHero
          date="2025-09-24"
          sides={[sideA, sideB]}
          story={story}
          lopsidedness={0.4}
          {...unanimous("u1")}
          call="unanimous"
          lensTally="4-0"
        />,
      );
      expect(screen.getByText("Edge")).toBeTruthy();
    });

    it("does not render a 'Lost' or split footer for the other side", () => {
      render(
        <TradeHero
          date="2025-09-24"
          sides={[sideA, sideB]}
          story={story}
          lopsidedness={0.8}
          {...unanimous("u1")}
          call="unanimous"
          lensTally="4-0"
        />,
      );
      expect(screen.queryByText(/Split ·/)).toBeNull();
      expect(screen.queryByText("Nobody")).toBeNull();
    });
  });

  describe("ruling stamp — split", () => {
    it("stacks both names with the lens(es) each won and a Split · N–N footer", () => {
      const winnersByLens: LensWinners = { value: "u2", total: "u1", regular: "u1", playoff: null, toilet: null };
      const marginsByLens: LensMargins = { value: 2240, total: 188, regular: 188, playoff: null, toilet: null };
      const { container } = render(
        <TradeHero
          date="2025-09-24"
          sides={[sideA, sideB]}
          story={story}
          lopsidedness={0.5}
          winnersByLens={winnersByLens}
          marginsByLens={marginsByLens}
          call="split"
          lensTally="2-1"
        />,
      );
      expect(screen.getByText("Mikey")).toBeTruthy();
      expect(screen.getByText("Tom")).toBeTruthy();
      expect(screen.getByText(/Split · 2-1/)).toBeTruthy();
      // no single headline winner — neither name renders at the unanimous 26px size
      expect(screen.queryByText("Lopsided")).toBeNull();
      expect(screen.queryByText("Edge")).toBeNull();
      // per-side margin figures also render in plain stamp-ink, not --pos/--neg
      expect(container.querySelector(".text-pos")).toBeNull();
      expect(container.querySelector(".text-neg")).toBeNull();
    });
  });

  describe("ruling stamp — no call", () => {
    it("renders 'Nobody' and 'Too close' when nothing decided it", () => {
      render(
        <TradeHero
          date="2025-09-24"
          sides={[sideA, sideB]}
          story={story}
          lopsidedness={0.02}
          winnersByLens={NO_WINNERS}
          marginsByLens={NO_MARGINS}
          call="none"
          lensTally="0"
        />,
      );
      expect(screen.getByText("Nobody")).toBeTruthy();
      expect(screen.getByText("Too close")).toBeTruthy();
    });
  });
});
