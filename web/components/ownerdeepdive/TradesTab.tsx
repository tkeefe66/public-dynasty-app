"use client";

import { Fragment } from "react";
import Link from "next/link";
import { OwnerDetailResp, OwnerTradeRow } from "@/lib/types";
import { OwnerLabel } from "../OwnerLabel";
import { CareerArc } from "../CareerArc";
import { InfoTooltip } from "@/components/InfoTooltip";
import { SegmentControl } from "@/components/SegmentControl";
import { Panel } from "../furniture/Panel";
import { EntryCard, CardList, MetaLine, Meta } from "../furniture/EntryCard";
import { Row } from "../furniture/Row";
import { ProductionProgressionCard } from "./ProductionProgressionCard";
import { signed, tone, whenLabel } from "./util";

/** Seasons with at least one trade, newest first. Also used by OwnerDeepDive
 *  to whitelist-validate the ?year= deep link. */
export function tradeSeasons(trades: OwnerTradeRow[]): number[] {
  return Array.from(new Set(trades.map((t) => t.season))).sort((a, b) => b - a);
}


/** Full metric names are the desktop column headers; a card's meta line needs
 *  the short forms the rest of the app already uses. */
const SHORT_LENS: Record<string, string> = {
  "Total Points": "Total",
  "Regular Season": "Reg",
  "Playoff Points": "Playoff",
  "Toilet Bowl": "Toilet",
};

/** `tone()` returns a className; `Meta` wants the tone NAME. Zero is dim — a
 *  zero swing is not a result. */
function metaTone(n: number): "pos" | "neg" | "dim" {
  return n > 0 ? "pos" : n < 0 ? "neg" : "dim";
}


/**
 * "92%" — the share of a haul that was actually started.
 *
 * The gap between Started Points and Total Points IS this number, and it is the
 * one figure on the card that says "you left points on your bench". Rendered as
 * a whole percent: the precision people argue with is 60 vs 90, not 61.4.
 *
 * NOTHING, never "0%", when the rate is null — a haul that has not played has
 * no start rate, and 0% is the most damning reading of the least information.
 */
function startPct(v: number | null | undefined): string | null {
  return v == null ? null : `${Math.round(v * 100)}%`;
}

export function TradesTab({
  leagueId, detail, yearFilter, onYearFilterChange,
}: {
  leagueId: string;
  detail: OwnerDetailResp;
  /** Controlled by OwnerDeepDive so the filter can round-trip via the URL. */
  yearFilter: number | "all";
  onYearFilterChange: (year: number | "all") => void;
}) {
  const byId = new Map(detail.trades.map((t) => [t.trade_id, t]));
  const best = detail.best_trade_id ? byId.get(detail.best_trade_id) : undefined;
  const worst = detail.worst_trade_id ? byId.get(detail.worst_trade_id) : undefined;
  const showWorst = worst && worst.trade_id !== best?.trade_id;

  const seasons = tradeSeasons(detail.trades);
  // Guard against a stale filter (e.g. the Owners pane swapped `detail` to an
  // owner who never traded in the selected year) — fall back to All rather
  // than silently showing "0 deals" with no active chip.
  const effectiveYear = yearFilter === "all" || seasons.includes(yearFilter)
    ? yearFilter
    : "all";
  const shownTrades = effectiveYear === "all"
    ? detail.trades
    : detail.trades.filter((t) => t.season === effectiveYear);

  const totals = [
    { k: "Trade Value", v: signed(detail.totals_by_lens.ktc), n: detail.totals_by_lens.ktc },
    { k: "Total Points", v: signed(detail.totals_by_lens.production, 1), n: detail.totals_by_lens.production },
    { k: "Regular Season", v: signed(detail.totals_by_lens.regular, 1), n: detail.totals_by_lens.regular },
    { k: "Playoff Points", v: signed(detail.totals_by_lens.playoff, 1), n: detail.totals_by_lens.playoff },
    { k: "Toilet Bowl", v: signed(detail.totals_by_lens.toilet, 1), n: detail.totals_by_lens.toilet },
  ];

  /** The desktop strip shows Started alongside the five, between the total it
   *  is a subset of and the phases that are subsets of it. Omitted entirely
   *  when the response predates the field, rather than printing a zero. */
  const totalsWithStarted = detail.totals_by_lens.started != null
    ? [
        ...totals.slice(0, 2),
        {
          k: "Started",
          v: signed(detail.totals_by_lens.started, 1),
          n: detail.totals_by_lens.started,
        },
        ...totals.slice(2),
      ]
    : totals;

  /**
   * THE PHONE CARD LEADS WITH STARTED POINTS.
   *
   * A card has one headline slot, and on a trading record the question is what
   * the deals produced ON THE FIELD — not what the assets are worth on the
   * market today, and not points a bench player scored while you sat him.
   *
   * `started` is `production_started` from the engine: starters only, every
   * week. It is NOT `regular + playoff + toilet`. `production_playoff` counts
   * live title-path games only, so started points in a placement game or an
   * eliminated week belong to no phase — measured on this league, 14 of 52
   * non-zero owner/trade pairs differ from that sum, by up to 23.6 points.
   * Summing the phases would have produced a quietly wrong number.
   *
   * This is a SIXTH metric, not one of the fixed five. The five and their
   * order stay contract in the ledgers and the desktop columns; only the
   * card's headline uses this, and Total Points keeps its place in the meta
   * line beside it so the bench-inclusive figure is never lost.
   *
   * A response served before the field existed omits it: fall back to Total
   * Points rather than printing a zero, which would read as "these trades
   * produced nothing".
   */
  const startedTotal = detail.totals_by_lens.started;
  const lead = startedTotal != null
    ? { k: "Started Points", v: signed(startedTotal, 1), n: startedTotal }
    : (totals.find((t) => t.k === "Total Points") ?? totals[0]);
  const rest = totals.filter((t) => t.k !== lead.k);

  return (
    <div className="space-y-6">
      {/* The five metrics, in the Scoreboard's grammar (TradeScoreboard.tsx):
          five bare columns of whisper label + mono figure at desktop, five
          rules on a phone. No tiles — a figure needs a label, not a box. */}
      <div>
        {/* Six now: Started sits with the five so a laptop reader sees the
            figure the phone card leads with. */}
        <div className="hidden min-[701px]:grid grid-cols-6 gap-2">
          {totalsWithStarted.map((it) => (
            <div key={it.k}>
              <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">{it.k}</div>
              <div
                className={`font-mono text-section font-semibold tabular tracking-[-0.02em] ${tone(it.n)}`}
              >
                {it.v}
              </div>
            </div>
          ))}
        </div>
        {/* ONE CARD on a phone, not five stacked rows.
            Five rules to state five totals put them at the same weight as each
            other and at no weight relative to the ledger below, which they are
            the sum of. As a card with Trade Value as the headline and the four
            production metrics as its meta line, it reads as the total OF the
            trades underneath it — the same shape the trade page's "Total
            realized" card uses, so a total looks like a total everywhere. */}
        <EntryCard className="border-t-2 border-t-ink bg-surface-sunk min-[701px]:hidden">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="min-w-0 flex-1 truncate font-display text-name font-bold tracking-[-0.01em] text-ink">
              All trades
            </span>
            <span data-testid="trades-totals-lead" className="grid shrink-0 justify-items-end text-right">
              <b className={`font-mono text-name font-semibold tabular leading-none ${tone(lead.n)}`}>
                {lead.v}
              </b>
              <span className="mt-0.5 font-mono text-label uppercase tracking-[0.12em] text-dim">
                {lead.k}
              </span>
            </span>
          </div>
          <MetaLine className="mt-2.5">
            {startPct(detail.totals_by_lens.start_pct) && (
              <Meta label="Started">{startPct(detail.totals_by_lens.start_pct)!}</Meta>
            )}
            {rest.map((it) => (
              <Meta key={it.k} label={SHORT_LENS[it.k] ?? it.k} tone={metaTone(it.n)}>{it.v}</Meta>
            ))}
          </MetaLine>
        </EntryCard>
      </div>

      <CareerArc arc={detail.career_arc} />

      {/* Did the hauls pan out? Cumulative production over the franchise's tenure. */}
      <ProductionProgressionCard
        axis={detail.production_week_axis ?? []}
        series={detail.production_series}
        verdict={detail.production_verdict}
        ownerName={detail.owner.owner_name}
      />

      {(best || showWorst) && (
        <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
          {best && <DealCard leagueId={leagueId} row={best} kind="best" />}
          {showWorst && <DealCard leagueId={leagueId} row={worst!} kind="worst" />}
        </div>
      )}

      <section>
        <div className="mb-3.5 flex items-baseline justify-between gap-3 border-b border-rule pb-1.5">
          <div className="flex min-w-0 items-baseline gap-3">
            <h2 className="font-display text-section font-bold tracking-[-0.02em]">
              Every trade
            </h2>
            {seasons.length > 1 && (
              <SegmentControl<number | "all">
                aria-label="Filter trades by year"
                options={[{ key: "all", label: "All" }, ...seasons.map((s) => ({ key: s, label: `'${String(s).slice(2)}` }))]}
                value={effectiveYear}
                onChange={onYearFilterChange}
              />
            )}
          </div>
          <div className="font-mono text-figure text-dim shrink-0">{shownTrades.length} deals</div>
        </div>
        {detail.trades.length === 0 ? (
          <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">
            No trades on record
          </div>
        ) : (
          <>
            {/* Desktop: the full ledger on the ruled ground. Rows stay Links
                and the ARIA table roles restore the semantics the CSS grid
                drops. Started joined the columns so the metric the phone card
                leads with is not invisible on a laptop. */}
            <div className="hidden font-mono text-figure tabular min-[701px]:block">
             <div role="table" aria-label="Every trade">
              <Panel>
              <Row role="row" className="grid-cols-[58px_1fr_64px_60px_60px_60px_68px_60px] gap-2 text-label uppercase tracking-[0.11em] text-dim">
                <div role="columnheader">When</div>
                <div role="columnheader" className="font-sans normal-case tracking-normal text-figure font-semibold">With · received</div>
                <div role="columnheader" className="text-right whitespace-nowrap">
                  Value <InfoTooltip title="Trade Value" body="Today's market-value swing for this side of the deal — the one true swing metric, positive when this owner's side is worth more right now." align="right" />
                </div>
                <div role="columnheader" className="text-right whitespace-nowrap">
                  Total <InfoTooltip title="Total Points" body="Net points swing across every week, bench included — what came in minus what went out." align="right" />
                </div>
                <div role="columnheader" className="text-right whitespace-nowrap">
                  Started <InfoTooltip title="Started Points" body="Points from starters only, across every week. NOT the sum of Reg + Playoff + Toilet: playoff counts live title-path games only, so started points in a placement game or an eliminated week belong to no phase." align="right" />
                </div>
                <div role="columnheader" className="text-right whitespace-nowrap">
                  Reg <InfoTooltip title="Regular Season Points" body="Net started-points swing in the regular season only." align="right" />
                </div>
                <div role="columnheader" className="text-right whitespace-nowrap">
                  Playoff <InfoTooltip title="Playoff Points" body="Net started-points swing in live title-path winners-bracket games only — byes, eliminated weeks, and placement games count zero." align="right" />
                </div>
                <div role="columnheader" className="text-right whitespace-nowrap">
                  Toilet <InfoTooltip title="Toilet Bowl Points" body="Net started-points swing in losers-bracket (consolation) games only." align="right" />
                </div>
              </Row>
              </Panel>
              {/* One entry = two rules: the figures on rule 1, the haul as its
                  own ellipsised prose rule below (§ "Prose Never Shares A
                  Rule"). The entry carries the ground at its own height so it
                  stays a single tap target, and hover is the lit stripe. */}
              {shownTrades.map((t) => (
                <Link key={t.trade_id} href={`/league/${leagueId}/trade/${t.trade_id}`}
                  className="block border-t border-rule hover:bg-surface-sunk" >
                  <Row role="row" className="grid-cols-[58px_1fr_64px_60px_60px_60px_68px_60px] items-center gap-2 ">
                    <div role="cell" className="text-dim">{whenLabel(t)}</div>
                    <div role="cell" className="flex min-w-0 flex-wrap items-center gap-x-1.5">
                      {t.counterparties.length === 0 ? <span className="text-dim">—</span> : t.counterparties.map((p, i) => (
                        <Fragment key={p.user_id}>{i > 0 && <span className="text-dim">·</span>}<OwnerLabel owner={p} variant="compact" /></Fragment>
                      ))}
                    </div>
                    <div role="cell" className={`text-right ${tone(t.swing_ktc)}`}>{signed(t.swing_ktc)}</div>
                    <div role="cell" className={`text-right ${tone(t.swing_prod)}`}>{signed(t.swing_prod, 1)}</div>
                    <div role="cell" className={`text-right ${tone(t.swing_started ?? 0)}`}>
                      {t.swing_started != null ? signed(t.swing_started, 1) : <span className="text-dim">—</span>}
                    </div>
                    <div role="cell" className={`text-right ${tone(t.swing_regular)}`}>{signed(t.swing_regular, 1)}</div>
                    <div role="cell" className={`text-right ${tone(t.swing_playoff)}`}>{signed(t.swing_playoff, 1)}</div>
                    <div role="cell" className={`text-right ${tone(t.swing_toilet)}`}>{signed(t.swing_toilet, 1)}</div>
                  </Row>
                  <Row className="">
                    <span className="block truncate text-figure text-dim" title={t.assets_short}>
                      {t.assets_short}
                    </span>
                  </Row>
                </Link>
              ))}
             </div>
            </div>

            {/* Phone — ONE CARD per trade.
                It was three rules each: when + Value, the haul on its own
                prose rule, then the four production metrics. The counterparty
                is now the card's identity, because that is how a trade is
                remembered — "the crh121 deal", not "the November one" — and
                the date joins the haul on the sub-line where it belongs as
                circumstance rather than headline.

                BREAKPOINT: `min-[701px]:hidden`, not `sm:hidden`. This block
                and its desktop twin used to switch at 640px while the totals
                above them switched at 701px, so between 640 and 700px the page
                showed the phone treatment for the totals and the seven-column
                desktop table for the ledger, on one screen. 701 is the
                system's mobile threshold and everything else in the app uses
                it. */}
            <div className="min-[701px]:hidden">
              <CardList>
                {shownTrades.map((t) => (
                  <EntryCard key={t.trade_id} href={`/league/${leagueId}/trade/${t.trade_id}`}>
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5">
                        {t.counterparties.length === 0 ? (
                          <span className="text-dim">—</span>
                        ) : (
                          t.counterparties.map((p, i) => (
                            <Fragment key={p.user_id}>
                              {i > 0 && <span className="text-dim">·</span>}
                              <OwnerLabel owner={p} variant="compact" />
                            </Fragment>
                          ))
                        )}
                      </span>
                      <span data-testid="trade-card-lead" className="grid shrink-0 justify-items-end text-right">
                        <b className={`font-mono text-name font-semibold tabular leading-none ${tone(t.swing_started ?? t.swing_prod)}`}>
                          {signed(t.swing_started ?? t.swing_prod, 1)}
                        </b>
                        <span className="mt-0.5 font-mono text-label uppercase tracking-[0.12em] text-dim">
                          {t.swing_started != null ? "Started Points" : "Total Points"}
                        </span>
                      </span>
                    </div>
                    {/* Trade Value moves into the meta line rather than off
                        the card — it is still the one true zero-sum swing, it
                        is just not what the card leads with. Order otherwise
                        follows the fixed five-metric vocabulary. */}
                    <MetaLine className="mt-2.5" data-testid="trade-card-meta">
                      {/* THREE FACTS, NOT SIX — a deliberate departure from
                          "every column survives", and the one place on this tab
                          the height actually is.

                          Measured at 390px: this ledger was 2,058px of a
                          3,889px tab, 158px per trade across 13 deals. It was
                          ~110px until Started Points joined the meta line and
                          pushed it to six facts wrapping onto three lines —
                          adding the metric made the page taller.

                          Why these three: Value is the market swing, Started %
                          is the bench-miss reading that exists nowhere else on
                          the card, and Playoff is the metric people actually
                          argue about. Total is a close cousin of the headline
                          (same weeks, plus bench). Reg is the bulk but the
                          least contested. Toilet is almost always 0.0.

                          Nothing is lost, and that is what makes it allowable:
                          the "All trades" card at the top of this tab still
                          carries ALL of them, the desktop table has every
                          column, and each card is a LINK to the trade page
                          where the full five sit per asset. Same justification
                          `StandingsTable`'s mobile card already uses for
                          dropping five columns — the data lives on the page
                          the card links to. */}
                      <Meta label="Value" tone={metaTone(t.swing_ktc)}>{signed(t.swing_ktc)}</Meta>
                      {startPct(t.start_pct) && (
                        <Meta label="Started">{startPct(t.start_pct)!}</Meta>
                      )}
                      <Meta label="Playoff" tone={metaTone(t.swing_playoff)}>{signed(t.swing_playoff, 1)}</Meta>
                    </MetaLine>
                    <div className="mt-2 truncate font-mono text-label uppercase tracking-[0.09em] text-dim"
                         title={t.assets_short}>
                      {whenLabel(t)} · {t.assets_short}
                    </div>
                  </EntryCard>
                ))}
              </CardList>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

/**
 * The best/worst deal, as a section rather than a card: a kicker on a hairline,
 * the figure, then the haul. The kicker is `--dim` — a colored word is a lie,
 * and the signed figure underneath already says which way it went. Hover is the
 * lit stripe; the old `hover:border-ink` changed the drawing.
 */
function DealCard({ leagueId, row, kind }: { leagueId: string; row: OwnerTradeRow; kind: "best" | "worst" }) {
  const best = kind === "best";
  return (
    <Link href={`/league/${leagueId}/trade/${row.trade_id}`} className="block hover:bg-rule-lit">
      <div className="border-b border-rule pb-1.5 font-mono text-label uppercase tracking-[0.16em] text-dim">
        {best ? "Best heist" : "Worst beat"}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className={`font-mono text-[length:var(--nameplate-4)] font-semibold tabular tracking-[-0.02em] ${tone(row.swing_ktc)}`}>{signed(row.swing_ktc)}</span>
        <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">Trade Value · {signed(row.swing_prod, 1)} pts</span>
      </div>
      <div className="mt-1.5 truncate text-figure text-body">{row.assets_short}</div>
      <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
        <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">{whenLabel(row)} · vs</span>
        {row.counterparties.map((p) => <OwnerLabel key={p.user_id} owner={p} variant="compact" />)}
      </div>
    </Link>
  );
}
