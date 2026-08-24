"use client";

import { useState, useEffect, useCallback } from "react";
import { SegmentControl } from "./SegmentControl";
import { IndeterminateBar } from "./furniture/IndeterminateBar";
import { StateMessage } from "./furniture/StateMessage";
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";

type Period = "today" | "7d" | "30d" | "all";

interface WriterCost {
  cost_usd: number;
  calls: number;
}

interface DailyBucket {
  date: string;
  cost_usd: number;
  calls: number;
  by_writer: Record<string, number>;
}

interface LlmCostData {
  period: string;
  total_cost_usd: number;
  total_calls: number;
  daily_avg_usd: number;
  daily: DailyBucket[];
  by_writer: Record<string, WriterCost>;
  by_league: Record<string, { cost_usd: number; calls: number; name?: string | null }>;
  active_model: string;
  monthly_budget_usd: number;
  month_to_date_usd: number;
  budget_remaining_usd: number | null;
}

const WRITER_LABELS: Record<string, string> = {
  trade_story: "Trade Stories",
  gm_rating_blurb: "GM Profiles",
  franchise_blurb: "Franchise Outlooks",
  recap: "Weekly Recap",
};

const PERIOD_LABELS: Record<Period, string> = {
  today: "Today",
  "7d": "7 days",
  "30d": "30 days",
  all: "All time",
};

// A `grid-template-columns` value, passed verbatim to `Row`'s `cols` prop —
// not a Tailwind `grid-cols-[...]` class (Row supplies `grid` itself).
const COST_COLS = "minmax(0,1fr) 64px 88px";

function fmt(usd: number) {
  return usd < 0.01 ? `$${usd.toFixed(5)}` : `$${usd.toFixed(3)}`;
}

export function LlmCostPanel() {
  const [period, setPeriod] = useState<Period>("7d");
  const [data, setData] = useState<LlmCostData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/settings/llm-cost?period=${period}`);
      if (!res.ok) throw new Error(`${res.status}`);
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const writers = data ? Object.keys(data.by_writer) : [];
  const maxCost = data
    ? Math.max(...data.daily.map((d) => d.cost_usd), 0.00001)
    : 1;

  return (
    <div>
      {/* The period run rides the head beside the title, and the "Period"
          kicker it used to sit behind is gone — "Today · 7 days · 30 days ·
          All time" is self-evidently a period. */}
      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule pb-1.5">
        <div className="font-mono text-label uppercase tracking-[0.16em] text-dim">
          LLM spend
        </div>
        <SegmentControl<Period>
          aria-label="Filter spend by period"
          options={(Object.keys(PERIOD_LABELS) as Period[]).map((p) => ({ key: p, label: PERIOD_LABELS[p] }))}
          value={period}
          onChange={setPeriod}
        />
        <button
          type="button"
          onClick={fetchData}
          className="ml-auto font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink"
        >
          Refresh
        </button>
      </div>

      {loading && <IndeterminateBar className="max-w-[220px]" label="Loading cost data" />}

      {!loading && data && (
        <>
          {/* Headline figures: labelled cells on one rule, no tiles. */}
          <div className="mb-6">
            <Panel>
              <Row cols="repeat(3, minmax(0,1fr))">
                {[
                  { label: "Total", value: fmt(data.total_cost_usd) },
                  { label: "Calls", value: String(data.total_calls) },
                  { label: "Daily avg", value: fmt(data.daily_avg_usd) },
                ].map(({ label, value }) => (
                  <span key={label} className="flex min-w-0 items-baseline gap-1.5">
                    <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-label uppercase tracking-[0.1em]">
                      {label}
                    </span>
                    <span className="flex-none font-semibold tabular">
                      {value}
                    </span>
                  </span>
                ))}
              </Row>
            </Panel>
          </div>

          {/* Monthly budget guardrail */}
          {data.monthly_budget_usd > 0 && (
            <div className="mb-6">
              <div className="flex items-center justify-between border-t border-rule pt-1.5">
                <span className="font-mono text-label uppercase tracking-[0.1em] text-dim">
                  Monthly LLM budget
                </span>
                <span className="font-mono text-figure tabular">
                  {fmt(data.month_to_date_usd)} / {fmt(data.monthly_budget_usd)}
                </span>
              </div>
              {data.budget_remaining_usd !== null && (
                <p
                  className={`mt-1 text-figure ${
                    data.budget_remaining_usd <= 0 ? "text-neg-strong" : "text-dim"
                  }`}
                >
                  {data.budget_remaining_usd <= 0
                    ? "Budget reached — LLM generation paused (graded data still updates)."
                    : `${fmt(data.budget_remaining_usd)} remaining this month`}
                </p>
              )}
            </div>
          )}

          {/* Daily spend as one ink bar per day, square, on a hairline
              baseline. A cost is not a signed outcome, so the bars stay ink —
              never --pos-bar/--neg-bar. Each day's total and call count stay
              on hover. */}
          {data.daily.length > 0 && (
            <div className="mb-6">
              <div
                role="img"
                aria-label="Daily LLM spend"
                className="mb-1 flex h-20 items-end gap-0.5 border-b border-rule"
              >
                {data.daily.map((day) => (
                  <div
                    key={day.date}
                    className="min-h-[2px] min-w-0 flex-1 bg-ink"
                    style={{ height: `${(day.cost_usd / maxCost) * 100}%` }}
                    title={`${day.date}: ${fmt(day.cost_usd)} (${day.calls} calls)`}
                  />
                ))}
              </div>
              <div className="flex items-baseline justify-between font-mono text-label tabular text-dim">
                <span>{data.daily[0].date}</span>
                <span>peak {fmt(maxCost)}</span>
                <span>{data.daily[data.daily.length - 1].date}</span>
              </div>
            </div>
          )}

          {data.total_calls === 0 && (
            <p className="mb-4 text-figure text-dim">
              No LLM calls recorded for this period.
            </p>
          )}

          {/* Per-feature ledger: the Panel's Rows draw every divider, and the
              hue swatch that used to key the chart is gone with the chart. */}
          {writers.length > 0 && (
            <div className="mb-4">
              <Panel>
                <Row cols={COST_COLS} variant="head">
                  <div>Feature</div>
                  <div className="text-right">Calls</div>
                  <div className="text-right">Cost</div>
                </Row>
                {Object.entries(data.by_writer)
                  .sort(([, a], [, b]) => b.cost_usd - a.cost_usd)
                  .map(([w, info]) => (
                    <Row key={w} cols={COST_COLS}>
                      <div className="min-w-0 truncate">{WRITER_LABELS[w] || w}</div>
                      <div className="text-right">{info.calls}</div>
                      <div className="text-right">{fmt(info.cost_usd)}</div>
                    </Row>
                  ))}
                <Row cols={COST_COLS} variant="total">
                  <div className="text-label font-bold uppercase tracking-[0.1em]">Total</div>
                  <div className="text-right">{data.total_calls}</div>
                  <div className="text-right">{fmt(data.total_cost_usd)}</div>
                </Row>
              </Panel>
            </div>
          )}

          {/* Per-league ledger */}
          {data.by_league && Object.keys(data.by_league).length > 0 && (
            <div className="mb-4">
              <Panel>
                <Row cols={COST_COLS} variant="head">
                  <div>League</div>
                  <div className="text-right">Calls</div>
                  <div className="text-right">Cost</div>
                </Row>
                {Object.entries(data.by_league)
                  .sort(([, a], [, b]) => b.cost_usd - a.cost_usd)
                  .map(([lid, info]) => (
                    <Row key={lid} cols={COST_COLS}>
                      <div className="min-w-0 truncate">{info.name || lid}</div>
                      <div className="text-right">{info.calls}</div>
                      <div className="text-right">{fmt(info.cost_usd)}</div>
                    </Row>
                  ))}
              </Panel>
            </div>
          )}

          <p className="font-mono text-label uppercase tracking-[0.1em] text-dim">
            Active model <span className="tracking-normal normal-case">{data.active_model}</span>
          </p>
        </>
      )}

      {!loading && !data && (
        <StateMessage
          tone="negative"
          kicker="Cost data didn't load"
          headline="Spend is still being recorded — we couldn't read it back."
          body="Not you — us. Hit Refresh once the settings endpoint answers."
        />
      )}
    </div>
  );
}
