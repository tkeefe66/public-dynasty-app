"use client";

import { useState } from "react";
import type {
  ProductionMetric, ProductionVerdict, TradeProductionSeries, PlayerInjury, Departure,
} from "../lib/types";
import { ProductionTimeline, type TimelineLine } from "./ProductionTimeline";
import { SectionHeader, useSectionCollapse } from "./furniture/SectionCollapse";

export function TradeProductionCard({
  axis, series, verdict, names, playerNames, injury, weekPhases, departures,
}: {
  axis: [number, number][];
  series: TradeProductionSeries;
  verdict?: Record<string, ProductionVerdict>;
  names: Record<string, string>;
  // player_id -> name (a plain map, not a function: RSC can't pass functions
  // to client components).
  playerNames?: Record<string, string>;
  injury?: Record<string, Record<string, PlayerInjury>>;
  weekPhases?: string[];
  departures?: Record<string, Departure[]>;
}) {
  const [metric, setMetric] = useState<ProductionMetric>("started");
  const { open, toggle } = useSectionCollapse("trade-production");
  const uids = Object.keys(series || {});
  if (!axis?.length || uids.length === 0) return null;
  const pname = (id: string) => playerNames?.[id] ?? id;

  // Always both sides. Departures (drop/trade) for a side's players are
  // marked on that side's line. Injury weeks no longer paint the chart
  // (DESIGN.md § "The Plot" — the phase rail replaced those tints); the
  // Injury Impact block below still carries that context.
  const lines: TimelineLine[] = uids.map((uid) => ({
    key: uid,
    label: names[uid] || uid,
    byMetric: series[uid],
    departures: departures?.[uid]?.map((d) => ({
      season: d.season, week: d.week, label: pname(d.player_id), kind: d.kind,
    })),
  }));

  const v = verdict?.[metric];

  return (
    <div className="mt-5">
      <SectionHeader title="Production" open={open} onToggle={toggle} />
      {!open ? null : (
      <div className="pt-3">
      <ProductionTimeline axis={axis} lines={lines} metric={metric} onMetricChange={setMetric}
                          weekPhases={weekPhases} />
      {v && (
        <div className="mt-3 border-t border-rule pt-2.5 text-prose text-body">
          <strong className="text-ink">{v.label}</strong> {v.sentence}
        </div>
      )}
      {(() => {
        if (!injury) return null;
        // One column per side (mirrors the haul boxes above), listing that
        // owner's received players who missed games to injury / are out now.
        const perSide = uids.map((uid) => ({
          uid,
          players: Object.keys(injury[uid] ?? {})
            .map((pid) => ({ pid, inj: injury[uid][pid] }))
            .filter(({ inj }) =>
              inj.games_missed.regular + inj.games_missed.playoff + inj.games_missed.toilet > 0
              || inj.currently_out),
        }));
        if (perSide.every((s) => s.players.length === 0)) return null;
        return (
          <div className="mt-4 border-t border-rule pt-3">
            <div className="font-mono text-label uppercase tracking-[0.16em] text-dim mb-2">
              Injury Impact
            </div>
            {/* Horizontal: each owner's injured players flow inline and wrap, and
                the two owners sit side by side — compact, not a tall vertical stack. */}
            <div className="flex flex-wrap gap-x-8 gap-y-2">
              {perSide.map(({ uid, players }) => (
                <div key={uid} className="flex items-baseline gap-x-3 gap-y-1 flex-wrap">
                  <span className="font-mono text-label uppercase tracking-[0.11em] text-dim shrink-0">
                    {names[uid] || uid}
                  </span>
                  {players.length === 0 ? (
                    <span className="text-figure text-dim/60">No injuries</span>
                  ) : (
                    players.map(({ pid, inj }) => {
                      const name = pname(pid);
                      const gm = inj.games_missed;
                      const total = gm.regular + gm.playoff + gm.toilet;
                      return (
                        <span key={pid} className="text-figure whitespace-nowrap">
                          <span className="text-ink font-medium">{name}</span>
                          {total > 0 && (
                            <span className="text-dim">
                              {" "}missed {total}
                              {gm.regular > 0 && <span> · {gm.regular} reg</span>}
                              {gm.playoff > 0 && <span className="text-ink"> · {gm.playoff} playoff</span>}
                              {gm.toilet > 0 && <span className="text-ink"> · {gm.toilet} TB</span>}
                            </span>
                          )}
                          {inj.currently_out && inj.out_detail && (
                            <span className="text-neg-strong">{" "}{inj.out_detail}</span>
                          )}
                        </span>
                      );
                    })
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })()}
      </div>
      )}
    </div>
  );
}
