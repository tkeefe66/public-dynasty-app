import { test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { TradeProductionCard } from "../components/TradeProductionCard";

test("renders the Production section header, verdict, and a chart", () => {
  render(
    <TradeProductionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{ u1: { total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 10 }], started: [], regular: [], playoff: [], toilet: [] } }}
      verdict={{ started: { label: "Won the production battle.", sentence: "Tom is ahead by 8 started points.", tone: "good", winner_uid: "u1", totals: { u1: 8 } },
                 total: { label: "Won the production battle.", sentence: "Tom is ahead by 10 total points.", tone: "good", winner_uid: "u1", totals: { u1: 10 } } }}
      names={{ u1: "Tom" }}
    />,
  );
  // Old card chrome ("did it pan out?" kicker, panel background/border/radius,
  // colored verdict tint) is gone — this is a collapsible SectionHeader on a
  // plain rule, and it carries the TITLE ALONE. The "Cumulative · <metric>
  // points" note went with every other section's scope note: the metric control
  // naming that same metric sits a few inches away.
  expect(screen.getByText("Production")).toBeInTheDocument();
  expect(screen.queryByText(/Cumulative ·/i)).not.toBeInTheDocument();
  expect(screen.getByText(/Won the production battle/i)).toBeInTheDocument();
});

test("verdict tracks the metric switch", () => {
  render(
    <TradeProductionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{ u1: { total: [{season:2024,week:4,value:0},{season:2024,week:5,value:10}],
                      playoff: [{season:2024,week:4,value:0},{season:2024,week:5,value:3}], started:[], regular:[], toilet:[] } }}
      verdict={{
        started: { label: "Started advantage.", sentence: "Tom is ahead on started.", tone: "good", winner_uid: "u1", totals: { u1: 8 } },
        total: { label: "Won the production battle.", sentence: "Tom won on total.", tone: "good", winner_uid: "u1", totals: { u1: 10 } },
        playoff: { label: "Too early.", sentence: "Too early on playoff.", tone: "neutral" },
      }}
      names={{ u1: "Tom" }}
    />,
  );
  expect(screen.getByText(/Tom is ahead on started/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /playoff/i }));
  expect(screen.getByText(/Too early on playoff/)).toBeInTheDocument();
});

test("renders Injury Impact block for an injured received player", () => {
  render(
    <TradeProductionCard
      axis={[[2024, 15], [2024, 16]]}
      series={{ u1: { total: [{season:2024,week:15,value:0},{season:2024,week:16,value:0}], started:[], regular:[], playoff:[], toilet:[] } }}
      verdict={{ total: { label: "x", sentence: "y", tone: "neutral" } }}
      names={{ u1: "Tom" }}
      injury={{ u1: { p1: { games_missed: { regular: 0, playoff: 1, toilet: 0 }, missed_weeks: [[2024,16,"high"]], currently_out: true, out_detail: "Out (Knee)" } } }}
      playerNames={{ p1: "Bijan" }}
    />,
  );
  expect(screen.getByText(/injury impact/i)).toBeInTheDocument();
  expect(screen.getByText(/Bijan/)).toBeInTheDocument();
  expect(screen.getByText(/1 playoff/i)).toBeInTheDocument();
  expect(screen.getByText(/Out \(Knee\)/)).toBeInTheDocument();
});

test("defaults to the Started metric on first render", () => {
  render(
    <TradeProductionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{ u1: { total: [{season:2024,week:4,value:0},{season:2024,week:5,value:10}], started:[{season:2024,week:4,value:0},{season:2024,week:5,value:8}], regular:[], playoff:[], toilet:[] } }}
      names={{ u1: "Tom" }}
    />,
  );
  const startedBtn = screen.getByRole("button", { name: /^started$/i });
  const totalBtn = screen.getByRole("button", { name: /^total$/i });
  /* INVERTED at the Furniture port, and the old comment here asserted the
   * opposite explicitly: "not an aria-pressed SegmentControl". A metric switch
   * IS a SegmentControl now — `.design/components/controls/SegmentControl.jsx`
   * lists "metric switches" among its own use cases, and the app is meant to
   * have exactly ONE single-select dialect rather than a bespoke run per
   * screen. So the active item is `aria-pressed`, which is what a toggle-button
   * group announces, rather than `aria-current`, which marks the current item
   * in a navigational set. */
  expect(startedBtn).toHaveAttribute("aria-pressed", "true");
  expect(totalBtn).toHaveAttribute("aria-pressed", "false");
});

test("labels both sides at their line ends, with no legend and no side toggle", () => {
  const { container } = render(
    <TradeProductionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{ u1: { total: [], started:[{season:2024,week:4,value:0},{season:2024,week:5,value:10}], regular:[], playoff:[], toilet:[] },
                u2: { total: [], started:[{season:2024,week:4,value:0},{season:2024,week:5,value:8}], regular:[], playoff:[], toilet:[] } }}
      verdict={{ started: { label:"Won.", sentence:"x", tone:"good", winner_uid:"u1", totals:{u1:10,u2:8} } }}
      names={{ u1: "Tom", u2: "Mikey" }}
    />,
  );
  // Owner names now live only as end-of-line labels inside the plot (desktop)
  // / stacked above it (mobile) — not a standalone always-visible legend row.
  const desktop = container.querySelector('[data-variant="desktop"]');
  expect(desktop).toBeTruthy();
  expect(desktop!.textContent).toContain("Tom");
  expect(desktop!.textContent).toContain("Mikey");
  // the old "Both" side toggle is gone (TradeProductionCard never had one;
  // this guards against it creeping back in during the port).
  expect(screen.queryByRole("button", { name: /^both$/i })).toBeNull();
});
