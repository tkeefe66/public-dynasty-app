import { test, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { ProductionTimeline } from "../components/ProductionTimeline";

const axis: [number, number][] = [[2024, 4], [2024, 5], [2024, 6]];
const lines = [
  { key: "u1", label: "Tom", byMetric: {
      total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 10 }, { season: 2024, week: 6, value: 25 }],
      started: [], regular: [], playoff: [], toilet: [],
  } },
  { key: "u2", label: "Mikey", byMetric: {
      total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 8 }, { season: 2024, week: 6, value: 14 }],
      started: [], regular: [], playoff: [], toilet: [],
  } },
];

// Both the desktop and mobile variants are always in the DOM (visibility is
// CSS-media-query driven, per DESIGN.md § Responsive), so every assertion
// below scopes to the desktop plot to avoid double-counting.
function desktopPlot(container: HTMLElement) {
  const el = container.querySelector('[data-variant="desktop"]');
  if (!el) throw new Error("desktop plot not found");
  return el as HTMLElement;
}

test("renders a polyline per visible line and switches metric", () => {
  const { container } = render(
    <ProductionTimeline axis={axis} lines={lines} defaultMetric="total" />,
  );
  expect(within(desktopPlot(container)).getAllByRole("img").length).toBe(1);
  expect(desktopPlot(container).querySelectorAll("polyline").length).toBe(2);
  expect(screen.getByRole("button", { name: /total/i })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /playoff/i }));
  // playoff series empty -> no polylines
  expect(desktopPlot(container).querySelectorAll("polyline").length).toBe(0);
});

/* INVERTED at the Furniture port (2026-08-16). This asserted the opposite —
 * every line `var(--ink)`, told apart by stroke weight alone, 2.5px solid vs
 * 1.25px dashed, and explicitly that no per-series colour ever appears.
 *
 * That was Agate's law, and it was right FOR AGATE: there a coloured pixel
 * could only ever mean a signed figure, so a chart had no colour to spend.
 * Furniture ships `--id-N-line` for exactly this job, and a 1.25px dash is the
 * least legible mark on the page for anyone who cannot resolve it.
 *
 * Same intent as the old test — "the two sides are told apart, and never by a
 * hue that means something else" — with the evidence inverted. What must still
 * hold, and is asserted below: the STROKE ramp, never the fill ramp, and never
 * the signed pair. */
test("tells series apart by identity STROKE, with weight as emphasis", () => {
  const { container } = render(
    <ProductionTimeline axis={axis} lines={lines} defaultMetric="total" />,
  );
  const polylines = Array.from(desktopPlot(container).querySelectorAll("polyline"));
  expect(polylines).toHaveLength(2);

  // Each side takes its own identity stroke, in series order.
  expect(polylines[0]).toHaveAttribute("stroke", "var(--id-1-line)");
  expect(polylines[1]).toHaveAttribute("stroke", "var(--id-2-line)");

  // Weight still marks the winner (Tom, 25.0 final) but is no longer the only
  // signal, and the dash is gone.
  const heavy = polylines.find((p) => p.getAttribute("stroke-width") === "2.5");
  expect(heavy).toBeTruthy();
  polylines.forEach((p) => expect(p).not.toHaveAttribute("stroke-dasharray"));

  // NEVER the fill ramp: as 1-3px lines only two of six --id-1..6 clear the
  // 3:1 WCAG 1.4.11 asks of a graphical object. And never the signed pair —
  // a series is an identity, not an outcome.
  polylines.forEach((p) => {
    expect(p.getAttribute("stroke")).toMatch(/--id-\d-line/);
    expect(p.getAttribute("stroke")).not.toMatch(/--pos|--neg/);
    expect(p.getAttribute("stroke")).not.toMatch(/var\(--id-\d\)/);
  });
});

test("labels each line at its own right end (owner + final figure); no legend, swatch row, or PTS caption", () => {
  const { container } = render(
    <ProductionTimeline axis={axis} lines={lines} defaultMetric="total" />,
  );
  const desktop = within(desktopPlot(container));
  expect(desktop.getByText("Tom")).toBeInTheDocument();
  expect(desktop.getByText("25.0")).toBeInTheDocument();
  expect(desktop.getByText("Mikey")).toBeInTheDocument();
  expect(desktop.getByText("14.0")).toBeInTheDocument();
  // The old swatch-row legend and its "cumulative pts ->" note are gone.
  expect(screen.queryByText(/cumulative pts/i)).toBeNull();
  expect(screen.queryByText("PTS")).toBeNull();
});

test("phase rail (not an amber band) marks postseason weeks", () => {
  const { container } = render(
    <ProductionTimeline
      axis={axis}
      lines={lines}
      defaultMetric="total"
      weekPhases={["pre", "pre", "post"]}
    />,
  );
  const desktop = within(desktopPlot(container));
  expect(desktop.getByText("PLAYOFFS")).toBeInTheDocument();
  expect(desktop.getByText("PHASE")).toBeInTheDocument();
  // The postseason segment is a solid ink rect, not a translucent amber fill.
  const rects = Array.from(desktopPlot(container).querySelectorAll("rect"));
  const postRect = rects.find((r) => r.getAttribute("fill") === "var(--ink)");
  expect(postRect).toBeTruthy();
  expect(postRect).not.toHaveAttribute("opacity");
});

test("measures divide the plot whole: 5 desktop rules over multiples of 100", () => {
  const { container } = render(
    <ProductionTimeline axis={axis} lines={lines} defaultMetric="total" />,
  );
  const desktop = within(desktopPlot(container));
  // max value is 25 -> step is the smallest multiple of 100 that covers it
  // over 5 rules, i.e. 100 -> measures are 500,400,300,200,100,0.
  ["500", "400", "300", "200", "100", "0"].forEach((v) => {
    expect(desktop.getByText(v)).toBeInTheDocument();
  });
});
