"use client";

import { useEffect, useState } from "react";
import { ApiError, tradesList } from "@/lib/api";
import type { ReactNode } from "react";
import { LatestTrade, StandingRow, Year } from "@/lib/types";
import { StandingsTable } from "./StandingsTable";
import { TradeCard } from "./TradeCard";
import { IndeterminateBar } from "./furniture/IndeterminateBar";
import { StateMessage } from "./furniture/StateMessage";

interface Props {
  leagueId: string;
  year: Year;
  /** The standings rows, for the Trade Grades ledger above the history. */
  rows: StandingRow[];
  currentSeason: number;
  youUserId?: string | null;
  yearControl?: ReactNode;
}

export function TradesTab({ leagueId, year, rows, currentSeason, youUserId, yearControl }: Props) {
  const [trades, setTrades] = useState<LatestTrade[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTrades(null);
    setError(null);
    tradesList(leagueId, { year: String(year) })
      .then((t) => {
        if (!cancelled) setTrades(t);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError && err.status === 409
            ? "Trade data is still loading — refresh in a moment."
            : "Couldn't load trades.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [leagueId, year]);

  const history = (() => {
  if (error) {
    return (
      <StateMessage
        tone="negative"
        kicker="Trades didn't load"
        headline={error}
        body="Not you — us. The ledger comes back once the league's cache is warm."
      />
    );
  }
  if (trades === null) {
    return <IndeterminateBar className="max-w-[220px]" label="Loading trades" />;
  }
  if (trades.length === 0) {
    return (
      <StateMessage
        kicker="No trades"
        headline={
          year === "all"
            ? "Every trade in this league's history will appear here."
            : `No deals were made in ${year}.`
        }
        body="Each one gets a graded verdict, a five-metric head-to-head, and the story of what the haul became."
      />
    );
  }

  return (
    <div className="mt-2">
      <div className="mb-2 flex items-baseline justify-between border-b border-rule pb-1.5">
        <h2 className="font-display text-section font-bold tracking-[-0.02em]">
          Trade history {year === "all" ? "· all-time" : `· ${year}`}
        </h2>
        <span className="font-mono text-label uppercase tracking-[0.1em] text-dim">
          {trades.length} trade{trades.length === 1 ? "" : "s"}
        </span>
      </div>
      {/* One ledger, not a grid of cards — entries stack on the ruled ground. */}
      <div>
        {trades.map((t) => (
          <TradeCard key={t.trade_id} leagueId={leagueId} trade={t} />
        ))}
      </div>
    </div>
  );
  })();

  return (
    <div>
      {/* TRADE GRADES sits above the history, and renders whatever the history
          fetch is doing — it is built from the standings the dashboard already
          has, so making it wait on a second request would be a spinner over
          data that is already in hand.

          Both sections are year-scoped, which is why this tab carries the
          season control: it governs the leaderboard AND the history, and one
          control that moves both is the honest shape. */}
      <StandingsTable
        sections="trades"
        yearControl={yearControl}
        leagueId={leagueId}
        rows={rows}
        year={year}
        currentSeason={currentSeason}
        youUserId={youUserId}
      />
      {history}
    </div>
  );
}
