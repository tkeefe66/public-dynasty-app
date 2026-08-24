import { test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { ProductionProgressionCard } from "../components/ownerdeepdive/ProductionProgressionCard";

test("renders received vs given timeline and aggregate verdict", () => {
  render(
    <ProductionProgressionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{
        received: { total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 20 }], started: [], regular: [], playoff: [], toilet: [] },
        given: { total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 12 }], started: [], regular: [], playoff: [], toilet: [] },
      }}
      verdict={{
        started: { label: "Started strong.", sentence: "Your hauls outscored what you shipped out in your lineup.", tone: "good" },
        total: { label: "Net positive.", sentence: "Across 3 trades, your hauls have produced +8 total points more than what you shipped out.", tone: "good" },
      }}
    />,
  );
  // No ownerName passed here: falls back to name-agnostic third-person copy.
  expect(screen.getByText(/did these trades pan out/i)).toBeInTheDocument();
  // Opens on Started, not Total. Both verdicts are in the fixture precisely so
  // this asserts a CHOICE — with only one present it would pass on any default.
  expect(screen.getByText(/Started strong/i)).toBeInTheDocument();
  expect(screen.queryByText(/Net positive/i)).toBeNull();
});

test("verdict tracks the metric switch", () => {
  render(
    <ProductionProgressionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{
        received: { total: [{season:2024,week:4,value:0},{season:2024,week:5,value:20}], started:[], regular:[], playoff:[{season:2024,week:4,value:0},{season:2024,week:5,value:5}], toilet:[] },
        given: { total: [{season:2024,week:4,value:0},{season:2024,week:5,value:12}], started:[], regular:[], playoff:[{season:2024,week:4,value:0},{season:2024,week:5,value:3}], toilet:[] },
      }}
      verdict={{
        started: { label: "Started strong.", sentence: "You are up on started.", tone: "good" },
        total: { label: "Net positive.", sentence: "You are up on total.", tone: "good" },
        playoff: { label: "Playoff edge.", sentence: "You are up on playoff.", tone: "good" },
      }}
    />,
  );
  expect(screen.getByText(/You are up on started/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /playoff/i }));
  expect(screen.getByText(/You are up on playoff/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^total$/i }));
  expect(screen.getByText(/You are up on total/)).toBeInTheDocument();
});

test("offers Both / Got / Gave views, no per-trade clutter", () => {
  render(
    <ProductionProgressionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{
        received: { total: [{season:2024,week:4,value:0},{season:2024,week:5,value:20}], started:[], regular:[], playoff:[], toilet:[] },
        given: { total: [{season:2024,week:4,value:0},{season:2024,week:5,value:12}], started:[], regular:[], playoff:[], toilet:[] },
      }}
    />,
  );
  expect(screen.getByRole("button", { name: /both/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /got/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /gave/i })).toBeInTheDocument();
  // The messy per-trade view is gone.
  expect(screen.queryByRole("button", { name: /by trade/i })).toBeNull();
});
