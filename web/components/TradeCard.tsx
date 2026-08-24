import { Fragment } from "react";
import Link from "next/link";
import { LatestTrade } from "@/lib/types";
import { OwnerLabel } from "./OwnerLabel";
import { Row } from "./furniture/Row";
import { seasonWeekLabel } from "@/lib/season-week";
import { fmtDate, fmtDateShort } from "@/lib/format-date";

interface Props {
  leagueId: string;
  trade: LatestTrade;
}

function tone(n: number): string {
  return n > 0 ? "text-pos-strong" : n < 0 ? "text-neg-strong" : "text-dim";
}

/**
 * Agate — a trade summary is a ledger entry, not a card (DESIGN.md § "The
 * Ledger Is The Layout"). Two rules: who traded and what it was worth, then the
 * haul with its date. The entry carries the ruled ground at its own height so it
 * stays one tap target, and hover is the lit stripe. Caller supplies the band.
 *
 * **The rule count is the same at every width, and it has to be.** `.ruled > *`
 * sets `display: grid` at line ~114 of globals.css — after `@tailwind utilities`
 * and at equal specificity — so a `hidden` class on a direct child of `.ruled`
 * loses the cascade and the rule renders anyway. A responsive entry therefore
 * varies its *contents*, never its rule count: the breakpoint swaps live on
 * inner spans, which `.ruled > *` does not touch. Getting this wrong ships both
 * variants stacked on top of each other.
 *
 * Phone drops Total Points rather than the haul: it reads 0.0 for every
 * offseason trade, and all five metrics are one tap away on the trade page.
 */
export function TradeCard({ leagueId, trade }: Props) {
  const swing = trade.swing_ktc;
  const prod = trade.swing_prod;
  const parties = trade.parties.map((p, i) => (
    <Fragment key={p.user_id}>
      {i > 0 && <span className="text-dim">↔</span>}
      <OwnerLabel owner={p} variant="compact" />
    </Fragment>
  ));
  return (
    <Link
      href={`/league/${leagueId}/trade/${trade.trade_id}`}
      className="block border-t border-rule hover:bg-surface-sunk"
    >
      <Row className="items-center grid-cols-[minmax(0,1fr)_auto] gap-3">
        <span className="flex min-w-0 items-center gap-x-1.5 overflow-hidden whitespace-nowrap text-prose">
          {parties}
        </span>
        <span className="flex shrink-0 items-baseline gap-3 font-mono text-figure tabular">
          {/* Total Points — desktop only. An inner span, so `hidden` applies. */}
          <span className="hidden items-baseline gap-1.5 min-[701px]:flex">
            <span className="text-label uppercase tracking-[0.11em] text-dim">Total Pts</span>
            <span className={tone(prod)}>
              {prod > 0 ? "+" : ""}
              {prod.toFixed(1)}
            </span>
          </span>
          <span className="flex items-baseline gap-1.5">
            <span className="hidden text-label uppercase tracking-[0.11em] text-dim min-[701px]:inline">
              Trade Value
            </span>
            <span className={tone(swing)}>
              {swing > 0 ? "+" : ""}
              {Math.round(swing)}
            </span>
          </span>
        </span>
      </Row>
      <Row className="items-center grid-cols-[minmax(0,1fr)_auto] gap-3">
        <span className="truncate text-figure text-dim" title={trade.assets_short}>
          {trade.assets_short}
        </span>
        <span className="shrink-0 font-mono text-label uppercase tracking-[0.11em] text-dim">
          <span className="min-[701px]:hidden">{fmtDateShort(trade.date)}</span>
          <span className="hidden min-[701px]:inline">
            {fmtDate(trade.date)} · {seasonWeekLabel(trade.date, trade.week)}
          </span>
        </span>
      </Row>
    </Link>
  );
}
