"use client";

import { useState } from "react";
import type {
  ProductionMetric, ProductionVerdict, OwnerProductionSeries,
} from "../../lib/types";
import { ProductionTimeline, type TimelineLine } from "../ProductionTimeline";
import { SegmentControl } from "../SegmentControl";
import { Section as Card, SectionTitle as CardHead } from "../furniture/Section";

type ViewMode = "both" | "received" | "given";

export function ProductionProgressionCard({
  axis, series, verdict, ownerName,
}: {
  axis: [number, number][];
  series?: OwnerProductionSeries;
  verdict?: Record<string, ProductionVerdict>;
  /** Third-person label for a page ~10 of 11 viewers are looking at someone
   *  else's franchise on. Falls back to a name-agnostic phrasing if omitted. */
  ownerName?: string;
}) {
  const [view, setView] = useState<ViewMode>("both");
  const [metric, setMetric] = useState<ProductionMetric>("started");
  const whoseTrades = ownerName ? `${ownerName}'s trades` : "these trades";

  if (!axis?.length || !series) {
    return (
      <Card>
        <CardHead title={`Did ${whoseTrades} pan out?`} />
        <p className="text-figure leading-relaxed text-body">
          The chart appears once there is a trade with weeks on the other side of it.
        </p>
      </Card>
    );
  }

  // Lines are told apart by stroke weight, not hue — `TimelineLine.color` was
  // deleted with the shared ProductionTimeline port.
  const receivedLine: TimelineLine = {
    key: "received", label: ownerName ? `What ${ownerName} got` : "What they got", byMetric: series.received,
  };
  const givenLine: TimelineLine = {
    key: "given", label: ownerName ? `What ${ownerName} gave up` : "What they gave up", byMetric: series.given,
  };

  const lines: TimelineLine[] =
    view === "received" ? [receivedLine]
      : view === "given" ? [givenLine]
        : [receivedLine, givenLine];

  const v = verdict?.[metric];

  return (
    <Card>
      <CardHead title={`Did ${whoseTrades} pan out?`} />
      {/* The side switch shares the metric run's LINE rather than owning one
          above it. Two 50px controls plus two whisper labels used to cost
          120px before the chart drew anything; this is 52px. */}
      <ProductionTimeline
        axis={axis}
        lines={lines}
        metric={metric}
        onMetricChange={setMetric}
        leading={
          <SegmentControl<ViewMode>
            aria-label="Choose which side of the trades to chart"
            options={[
              { key: "both", label: "Both" },
              { key: "received", label: "Got" },
              { key: "given", label: "Gave" },
            ]}
            value={view}
            onChange={setView}
          />
        }
      />
      {/* The verdict was a tinted panel — a colored ground outside the five
          sanctioned stamp slots, and depth besides. It is a mono kicker over
          plain prose on `--bg` now; the tone lives in the words. */}
      {v && (
        <div className="mt-3 border-t border-rule pt-2">
          <div className="font-mono text-label uppercase tracking-[0.16em] text-dim">{v.label}</div>
          <p className="mt-1 max-w-[68ch] text-prose leading-relaxed text-body">{v.sentence}</p>
        </div>
      )}
    </Card>
  );
}
