"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { betsSummary, createBet, listBets, updateBet } from "@/lib/api";
import type {
  BetsSummaryResp,
  SideBetCreateBody,
  SideBetUpdateBody,
  SideBetView,
  StandingRow,
} from "@/lib/types";
import { Button } from "@/components/furniture/Button";
import { IndeterminateBar } from "@/components/furniture/IndeterminateBar";
import { StateMessage } from "@/components/furniture/StateMessage";
import { SectionHead } from "@/components/furniture/SectionHead";
import { SegmentControl } from "@/components/SegmentControl";
import { BetLeaderboard } from "./BetLeaderboard";
import { BetLedger } from "./BetLedger";
import { RecordBetForm } from "./RecordBetForm";

export function BetsTab({
  leagueId,
  owners,
}: {
  leagueId: string;
  owners: StandingRow[];
}) {
  const [bets, setBets] = useState<SideBetView[] | null>(null);
  const [summary, setSummary] = useState<BetsSummaryResp | null>(null);
  const [season, setSeason] = useState<number | null>(null);
  const [seasonOptions, setSeasonOptions] = useState<number[]>([]);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [l, s] = await Promise.all([
        listBets(leagueId, { season: season ?? undefined }),
        betsSummary(leagueId, season ?? undefined),
      ]);
      setBets(l.bets);
      setSummary(s);
      // Grow-only so picking a season doesn't collapse the options.
      setSeasonOptions((cur) =>
        Array.from(new Set([...cur, ...l.bets.map((b) => b.season)])).sort(
          (a, b) => b - a,
        ),
      );
    } catch {
      setError("Couldn't load the bets ledger.");
    }
  }, [leagueId, season]);

  useEffect(() => {
    void load();
  }, [load]);

  const onAction = useCallback(
    async (betId: string, body: SideBetUpdateBody) => {
      await updateBet(leagueId, betId, body);
      await load();
    },
    [leagueId, load],
  );

  const onSave = useCallback(
    async (body: SideBetCreateBody) => {
      await createBet(leagueId, body);
      setRecording(false);
      // Reset to All seasons so the new bet is visible even when it falls
      // outside the active filter. Changing `season` retriggers the load
      // effect; only reload directly when the filter was already clear.
      if (season !== null) {
        setSeason(null);
      } else {
        await load();
      }
    },
    [leagueId, season, load],
  );

  if (error) {
    return (
      <StateMessage
        tone="negative"
        kicker="Ledger didn't load"
        headline="The bets are recorded — we couldn't read them back."
        body="Not you — us. Reload and the ledger comes back."
      />
    );
  }
  if (bets === null || summary === null) {
    return <IndeterminateBar className="max-w-[220px]" label="Loading the ledger" />;
  }

  const seasonOptionsList: { key: number | "all"; label: ReactNode }[] = [
    { key: "all", label: "All seasons" },
    ...seasonOptions.map((s) => ({ key: s, label: String(s) })),
  ];

  return (
    <div>
      {/* The form is BEHIND THIS BUTTON at every width, and that is a phone
          decision: five fields sitting open push the ledger — the thing you
          opened this tab to read — below the fold. `Button` carries
          `min-h-tap`, so the trigger is a 44px target even at `py-1.5`. */}
      {/* Season beside the title (it filters the ledger); the record button
          keeps the far end (it acts on the section rather than narrowing it). */}
      <SectionHead
        title="Side bets"
        filter={
          <SegmentControl<number | "all">
            aria-label="Filter bets by season"
            options={seasonOptionsList}
            value={season ?? "all"}
            onChange={(v) => setSeason(v === "all" ? null : v)}
          />
        }
        action={
          !recording && (
            <Button as="button" className="px-3 py-1.5" onClick={() => setRecording(true)}>
              Record a bet
            </Button>
          )
        }
      />
      {recording && (
        <RecordBetForm
          owners={owners.map((o) => ({
            user_id: o.user_id,
            name: o.owner.owner_name,
          }))}
          onSave={onSave}
          onCancel={() => setRecording(false)}
        />
      )}
      <BetLeaderboard rows={summary.owners} />
      <BetLedger bets={bets} onAction={onAction} />
    </div>
  );
}
