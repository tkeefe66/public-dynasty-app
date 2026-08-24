"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { betsSummary } from "@/lib/api";
import type { OwnerBetSummary } from "@/lib/types";
import { formatCents, formatSignedCents } from "@/lib/money";
import { Card, CardHead } from "./ui";

function Stat({ label, value, cls = "" }: { label: string; value: string; cls?: string }) {
  return (
    <div>
      <div className="text-figure text-dim">{label}</div>
      <div className={`font-mono tabular text-sm font-semibold ${cls}`}>{value}</div>
    </div>
  );
}

export function SideBetsCard({
  leagueId,
  userId,
}: {
  leagueId: string;
  userId: string;
}) {
  const [row, setRow] = useState<OwnerBetSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    betsSummary(leagueId)
      .then((s) => {
        if (cancelled) return;
        setRow(s.owners.find((o) => o.owner.user_id === userId) ?? null);
      })
      .catch(() => {
        /* No bets card on error — the ledger page surfaces failures. */
      });
    return () => {
      cancelled = true;
    };
  }, [leagueId, userId]);

  if (!row) return null;

  return (
    <Card>
      <CardHead
        title="Side bets"
        right={
          <Link
            className="text-figure text-dim underline"
            href={`/league/${leagueId}?tab=bets`}
          >
            Full ledger
          </Link>
        }
      />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat
          label="Net"
          value={formatSignedCents(row.net_cents)}
          cls={row.net_cents > 0 ? "text-pos-strong" : row.net_cents < 0 ? "text-neg-strong" : "text-dim"}
        />
        <Stat label="Record" value={`${row.won}-${row.lost}-${row.pushed}`} />
        <Stat label="Biggest win" value={formatCents(row.biggest_win_cents)} />
        <Stat label="Worst loss" value={formatCents(row.worst_loss_cents)} />
      </div>
      {row.cents_at_stake > 0 && (
        <p className="text-figure text-dim mt-2">
          {formatCents(row.cents_at_stake)} still at stake on open bets.
        </p>
      )}
    </Card>
  );
}
