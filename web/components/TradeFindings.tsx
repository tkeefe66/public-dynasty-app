import { TradeProductionSeries, TradeSideView } from "@/lib/types";
import { buildInsights, collectDrivers } from "@/lib/trade-insights";

export interface TradeFindingsProps {
  sides: TradeSideView[];
  winner_user_id: string | null;
  series?: TradeProductionSeries;
}

/* ---------------------------------------------------------------------------
 * FINDINGS — design_handoff_agate: three derived stats, mono figure + one-line
 * sentence (Dynasty Directions.dc.html "2a", Fig. 2a.2). Built entirely from
 * `lib/trade-insights.ts`'s deterministic comparison library — no LLM, no
 * invented data. Sits after the side ledgers on the trade page.
 * ------------------------------------------------------------------------ */

export function TradeFindings({ sides, winner_user_id, series }: TradeFindingsProps) {
  const winner = winner_user_id ? (sides.find((s) => s.user_id === winner_user_id) ?? null) : null;
  const loser = winner ? (sides.find((s) => s.user_id !== winner_user_id) ?? null) : null;

  const insights =
    winner && loser
      ? buildInsights(winner, loser, collectDrivers([winner], winner_user_id), series, 3)
      : [];

  if (insights.length === 0) return null;

  return (
    <div className="mt-5 border-t border-rule pt-3.5">
      <div className="font-mono text-label uppercase tracking-[0.14em] text-dim">Findings</div>
      <div className="mt-2.5 grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-[18px]">
        {insights.map((ins, i) => (
          <div key={i}>
            <div
              className={`font-mono text-section font-semibold tabular tracking-[-0.02em] ${
                ins.tone === "neg" ? "text-neg-strong" : "text-pos-strong"
              }`}
            >
              {ins.stat}
            </div>
            <div className="mt-1 text-figure leading-[1.45] text-body">{ins.text}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
