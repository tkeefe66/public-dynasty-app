"use client";

import { LensMargins, LensWinners, TradeCall, TradeSideView } from "@/lib/types";
import { LENS_LABEL_FULL, LENS_ORDER, realizedTotals, StatTotals } from "@/lib/trade-lens";
import { InfoTooltip } from "./InfoTooltip";
import { SectionHeader, useSectionCollapse } from "./furniture/SectionCollapse";
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";
import { CardList, EntryCard } from "./furniture/EntryCard";
import { Figure } from "./furniture/Figure";
import { Bar } from "./furniture/Bar";

/* ---------------------------------------------------------------------------
 * SCOREBOARD — `.design/templates/trade/Trade.dc.html` § "Scored by lens".
 *
 * A Panel ledger, one rule per lens: `Lens · Margin · bar · Winner`. The five
 * lenses are a FIXED vocabulary in a FIXED order (Trade Value · Total Points ·
 * Regular Season Points · Playoff Points · Toilet Bowl Points) and come from
 * `lib/trade-lens.ts`, never from the template's illustrative placeholders.
 *
 * Every figure here is the API's `margins_by_lens` verbatim — never recomputed
 * client-side, so it cannot drift from the side ledgers' "Total realized" rows
 * or from the hero's ruling stamp (all three read the same two fields).
 *
 * The bar is scale, not information: its track is the whole pot for that lens
 * (both sides' realized totals added), so its length reads as "the margin's
 * share of everything that lens measured". The signed figure sits beside it, so
 * colour is never the only carrier — the guard rule that makes a coloured bar
 * legal in Furniture at all.
 * ------------------------------------------------------------------------ */

/** ONE `grid-template-columns` string, passed to the head row and every body
 *  row. Row's contract is that `cols` repeats VERBATIM across the ledger — a
 *  mismatch between head and body is the most common ledger bug — so it is a
 *  single constant rather than a string typed six times.
 *
 *  The winner track is 150px, not the template's 96px. `Trade.dc.html` sizes
 *  its columns around the fixture name "Reznik"; real Sleeper display names are
 *  longer, and at 96px this shipped rendering the winner as "ChocGummyBe…".
 *  Truncating the winner defeats the row — the margin says how much, the winner
 *  says who, and only one of those has a fallback. A drawn template is a
 *  composition spec, not a promise about the width of somebody's username. */
const COLS = "minmax(0,1fr) 96px 130px 150px";

/** Per-lens help. Bodies describe the MARGIN, because that is what this table
 *  shows.
 *
 *  The row label is `LENS_LABEL_FULL`, not the ledger's abbreviation. This
 *  briefly shipped as `LENS_LABEL` ("Value · Total · Reg · Playoff · Toilet")
 *  justified as keeping the column's width — but the lens column is
 *  `minmax(0,1fr)`, ~830px at template width, so there was no width to keep.
 *  The five metrics are a fixed vocabulary; abbreviate only where the column
 *  genuinely cannot hold the name (`TradeStatTable`'s 56-60px metric columns). */
const LENS_HELP: Record<keyof LensMargins, { title: string; body: string }> = {
  value: {
    title: "Trade Value",
    body: "Today's market-value margin between the two sides — the one true swing metric, read on what each side actually realized.",
  },
  total: {
    title: "Total Points",
    body: "Margin in points scored by everything each side received, bench included, every week it was held.",
  },
  regular: {
    title: "Regular Season Points",
    body: "Margin in started points in the weeks before the playoffs begin.",
  },
  playoff: {
    title: "Playoff Points",
    body: "Margin in started points in live title-path winners-bracket games only — byes, eliminated weeks, and placement games count zero.",
  },
  toilet: {
    title: "Toilet Bowl Points",
    body: "Margin in started points in losers-bracket (consolation) games only.",
  },
};

/** Which `StatTotals` field each lens reads. */
const LENS_FIELD: Record<keyof LensMargins, keyof StatTotals> = {
  value: "ktc",
  total: "total",
  regular: "regular",
  playoff: "playoff",
  toilet: "toilet",
};

/** Trade Value is a whole number with thousands separators; the four
 *  production lenses are points to one decimal, ungrouped — the exact split
 *  `fmtLensValue` applies in the side ledgers, so the two agree glyph for
 *  glyph. */
function figureFormat(lens: keyof LensMargins): { dp: number; grouped: boolean } {
  return lens === "value" ? { dp: 0, grouped: true } : { dp: 1, grouped: false };
}


interface Props {
  margins: LensMargins;
  winners: LensWinners;
  /** Both sides — the winner column's names, and the bars' scale. */
  sides: TradeSideView[];
  call: TradeCall;
  lensTally: string;
}

export function TradeScoreboard({ margins, winners, sides, call, lensTally }: Props) {
  const { open, toggle } = useSectionCollapse("trade-scoreboard");

  const nameOf = (uid: string) => sides.find((s) => s.user_id === uid)?.owner_name ?? uid;

  // Both sides' realized totals — the same rows-plus-became reading the side
  // ledgers render, used only to scale the bars. The MARGIN itself still comes
  // straight off `margins_by_lens`; nothing here recomputes it.
  const realized = sides.map((s) => realizedTotals(s.breakdown));
  const scaleFor = (lens: keyof LensMargins) =>
    realized.reduce((sum, t) => sum + Math.abs(t[LENS_FIELD[lens]]), 0);

  // THE BARS ARE UNSIGNED, and that is not an oversight. `_lens_verdict`
  // (api/app/services/trade_view.py) emits `top - runner_up` and only when a
  // single leader exists, so every margin that reaches here is strictly
  // POSITIVE — a tie or an unscored lens arrives as null instead.
  //
  // A `signed` Bar therefore renders a diverging axis that can never diverge:
  // `--neg-bar` is unreachable, and a signed fill is capped at `width: pct/2`,
  // so half the 130px track plus its centre line are dead pixels and every bar
  // reads at half the resolution the column affords. This shipped once and the
  // suite stayed green, because nothing asserts bar width.
  //
  // The scale is the POT (both sides' realized totals for the lens), so the bar
  // reads as the margin's share of what was actually on the table. `m <= P`
  // holds in every sign case, so the drawn proportion is always the true one.

  return (
    <div className="mt-5">
      <SectionHeader title="Scoreboard" open={open} onToggle={toggle} />
      {!open ? null : (
        <>
          {/* Desktop — the drawn four-track ledger. */}
          <div className="mt-3 hidden min-[701px]:block">
            <Panel>
              <Row variant="head" cols={COLS}>
                <span>Lens</span>
                <span className="text-right">Margin</span>
                <span />
                <span className="text-right">Winner</span>
              </Row>
              {LENS_ORDER.map((lens) => {
                const margin = margins[lens];
                const winnerUid = winners[lens];
                const { dp, grouped } = figureFormat(lens);
                return (
                  <Row key={lens} cols={COLS}>
                    <span className="flex min-w-0 items-center gap-1.5 text-ink">
                      <span className="truncate">{LENS_LABEL_FULL[lens]}</span>
                      <InfoTooltip title={LENS_HELP[lens].title} body={LENS_HELP[lens].body} />
                    </span>
                    <Figure value={margin} signed dp={dp} grouped={grouped} />
                    {/* An unscored lens has no magnitude to draw — an empty
                        track keeps the column contract without implying a
                        zero-length result. */}
                    {margin == null ? (
                      <span />
                    ) : (
                      <Bar value={margin} max={scaleFor(lens)} />
                    )}
                    <span
                      className={`truncate text-right ${winnerUid ? "text-ink" : "text-dim"}`}
                    >
                      {winnerUid ? nameOf(winnerUid) : "—"}
                    </span>
                  </Row>
                );
              })}
            </Panel>
          </div>

          {/* ≤700px — an entry becomes a CARD, not a row. Every column
              survives: lens, margin, bar, winner. Nothing scrolls sideways. */}
          <CardList className="mt-3 min-[701px]:hidden">
            {LENS_ORDER.map((lens) => {
              const margin = margins[lens];
              const winnerUid = winners[lens];
              const { dp, grouped } = figureFormat(lens);
              return (
                <EntryCard key={lens}>
                  <span className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5 text-ink">
                      <span className="truncate">{LENS_LABEL_FULL[lens]}</span>
                      <InfoTooltip title={LENS_HELP[lens].title} body={LENS_HELP[lens].body} />
                    </span>
                    <Figure value={margin} signed dp={dp} grouped={grouped} />
                  </span>
                  {margin != null && (
                    <Bar value={margin} max={scaleFor(lens)} className="mt-2.5" />
                  )}
                  <span className="mt-2.5 flex items-baseline justify-between gap-2">
                    <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
                      Winner
                    </span>
                    <span className={`truncate ${winnerUid ? "text-ink" : "text-dim"}`}>
                      {winnerUid ? nameOf(winnerUid) : "—"}
                    </span>
                  </span>
                </EntryCard>
              );
            })}
          </CardList>
        </>
      )}
    </div>
  );
}
