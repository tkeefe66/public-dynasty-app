"use client";

import { useEffect, useState } from "react";
import { LOADING_GRADING } from "@/lib/swagger";
import { Mark as Icon } from "./furniture/Mark";
import { IndeterminateBar } from "./furniture/IndeterminateBar";
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";

interface Props {
  open: boolean;
  events: { stage: string; message?: string; done?: number; total?: number }[];
}

const FRIENDLY: Record<string, string> = {
  chain: "Walking your league history",
  players: "Loading the Sleeper player database",
  trades: "Normalizing trades",
  supporting: "Fetching matchups, market values, projections",
  grading: LOADING_GRADING,
  became: "Tracing what every haul became",
  stories: "Writing the trade verdicts",
  owner_blurbs: "Writing GM profiles",
  franchise_blurbs: "Writing franchise outlooks",
  done: "Finishing up",
  error: "Something went wrong",
};

type Step = { stage: string; count: number; done?: number; total?: number };

// Collapse the raw event stream into ordered, de-duplicated steps. The grader
// emits one event per trade/profile while writing prose, so a stage can repeat
// dozens of times — we fold consecutive same-stage events into one step and
// keep a count instead of printing a wall of identical lines. When the backend
// includes done/total on an event (e.g. story writing), keep the latest so the
// active step can show "17/30" instead of a bare running count.
function toSteps(events: Props["events"]): Step[] {
  const steps: Step[] = [];
  for (const e of events) {
    if (e.stage === "done") continue; // header handles the finish state
    const last = steps[steps.length - 1];
    if (last && last.stage === e.stage) {
      last.count += 1;
      if (e.done != null) last.done = e.done;
      if (e.total != null) last.total = e.total;
    } else {
      steps.push({ stage: e.stage, count: 1, done: e.done, total: e.total });
    }
  }
  return steps;
}

/* ---------------------------------------------------------------------------
 * Furniture — Floating Layers. The overlay recipe: a full-bleed `--ink` field
 * at 55% behind (`.overlay-field`, globals.css — the one sanctioned use; a
 * popover or tooltip gets no field), a `--bg` panel in front. Under Furniture
 * the panel can take the one sanctioned radius + elevation (rounded-panel,
 * shadow-panel), which it could not before. Steps sit in a Panel of Rows,
 * each drawing its own `--rule` hairline, with `done`/`closed` marks (the
 * icon set's "done" checkmark and "closed" right-pointing triangle) and
 * counts; a pending step stays the plain "·" glyph. The progress bar is the
 * shared IndeterminateBar — the one animated element in this view.
 * ------------------------------------------------------------------------ */
export function ProgressModal({ open, events }: Props) {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    if (!open) return;
    setSecs(0);
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [open]);

  if (!open) return null;
  const latest = events[events.length - 1];
  const isError = latest?.stage === "error";
  const steps = toSteps(events);
  const activeIdx = isError ? -1 : steps.length - 1;

  return (
    <div className="overlay-field fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isError ? "Refresh failed" : "Building your league"}
        className="w-[440px] max-w-full rounded-panel border border-ink bg-bg p-[18px] shadow-panel"
      >
        <div className="flex items-baseline justify-between border-b border-rule pb-1.5">
          <div className="font-display text-prose font-bold tracking-[-0.02em]">
            {isError ? "Error" : "Building your league"}
          </div>
          <div className="font-mono text-label uppercase tracking-[0.14em] text-dim" aria-label={`${secs} seconds elapsed`}>
            {secs}s
          </div>
        </div>

        <h2 className="mt-2.5 font-display text-lead font-extrabold leading-[1.05] tracking-[var(--track-lead)]">
          {isError ? "Something went wrong" : FRIENDLY[latest?.stage ?? "chain"] ?? "Starting…"}
        </h2>

        <p className="mt-1.5 max-w-[52ch] text-prose leading-relaxed text-body">
          {isError
            ? "The refresh stopped before it finished — give it another try."
            : "First load rebuilds your whole league history — every season, every trade, graded. It can take up to a minute, then it's cached and instant from here."}
        </p>

        {!isError && (
          <div className="mt-3">
            <IndeterminateBar />
          </div>
        )}

        <Panel className="mt-4" role="list">
          {steps.map((s, i) => {
            const active = i === activeIdx;
            const done = i < activeIdx;
            return (
              <Row
                key={s.stage}
                role="listitem"
                cols="14px minmax(0,1fr) 48px"
              >
                <span aria-hidden="true" className={done || active ? "flex text-ink" : "text-dim"}>
                  {done ? <Icon name="done" size={12} /> : active ? <Icon name="closed" size={12} /> : "·"}
                </span>
                <span className={`truncate ${active ? "font-semibold text-ink" : "text-dim"}`}>
                  {FRIENDLY[s.stage] ?? s.stage}
                </span>
                <span className="text-right">
                  {s.total != null ? `${s.done ?? s.count}/${s.total}` : s.count > 1 ? s.count : ""}
                </span>
              </Row>
            );
          })}
        </Panel>
      </div>
    </div>
  );
}
