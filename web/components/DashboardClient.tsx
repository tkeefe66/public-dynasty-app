"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, dashboard, getMe, getProfiles, refreshStream } from "@/lib/api";
import { DashboardResp, Lens, ProfilesMap, Year } from "@/lib/types";
import { ProgressModal } from "./ProgressModal";
import { DashboardSkeleton } from "./DashboardSkeleton";
import { LeagueHeader } from "./LeagueHeader";
import { LeagueNotes } from "./LeagueNotes";
import { YearTabs } from "./YearTabs";
import { DashboardTabs } from "./DashboardTabs";
import { HeadlineMoves } from "./HeadlineMoves";
import { StandingsTable } from "./StandingsTable";
import { TradesTab } from "./TradesTab";
import { OwnersTab } from "./OwnersTab";
import { Leaderboard } from "./Leaderboard";
import { BetsTab } from "@/components/bets/BetsTab";
import { Button } from "./furniture/Button";

export type DashboardTab = "dashboard" | "trades" | "owners" | "gm" | "bets";

interface Props {
  leagueId: string;
  initialYear: Year;
  initialLens: Lens;
  initialTab: DashboardTab;
}

export function DashboardClient({ leagueId, initialYear, initialLens, initialTab }: Props) {
  const [data, setData] = useState<DashboardResp | null>(null);
  const [profiles, setProfiles] = useState<ProfilesMap>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<
    { stage: string; message?: string; done?: number; total?: number }[]
  >([]);
  // The signed-in user's Sleeper id, for "your franchise" highlighting.
  const [youUserId, setYouUserId] = useState<string | null>(null);

  const loadOrRefresh = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const d = await dashboard(leagueId, { year: initialYear, lens: initialLens });
      setData(d);
      setLoading(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Cold cache: kick off the SSE refresh that builds + grades the chain.
        setLoading(false);
        setRefreshing(true);
        setEvents([]);
        refreshStream(leagueId, async (ev) => {
          setEvents((cur) => [...cur, ev]);
          if (ev.stage === "error") {
            setRefreshing(false);
            setError("The refresh stopped before it finished. Try again.");
            return;
          }
          if (ev.stage === "done") {
            try {
              const d = await dashboard(leagueId, {
                year: initialYear, lens: initialLens,
              });
              setData(d);
            } catch (e) {
              setError(e instanceof Error ? e.message : "Couldn't load the dashboard.");
            } finally {
              setRefreshing(false);
            }
          }
        });
      } else {
        setLoading(false);
        setError(err instanceof Error ? err.message : "Couldn't load the dashboard.");
      }
    }
  }, [leagueId, initialYear, initialLens]);

  useEffect(() => {
    loadOrRefresh();
  }, [loadOrRefresh]);

  // The league "voice" data. Independent of year/lens and never 409s (returns
  // {} when nothing's saved yet), so fetch it once on mount.
  useEffect(() => {
    getProfiles(leagueId).then(setProfiles).catch(() => setProfiles({}));
  }, [leagueId]);

  // Who am I in this league? (sleeper_user_id matches a standings row's user_id)
  useEffect(() => {
    getMe().then((me) => setYouUserId(me.sleeper_user_id)).catch(() => {});
  }, []);

  // Cold-start: full-screen staged progress.
  if (refreshing) {
    return <ProgressModal open events={events} />;
  }

  // Error with nothing to show: full error state with retry.
  if (error && !data) {
    return <ErrorState message={error} onRetry={loadOrRefresh} />;
  }

  // First load (or post-cold-start reload) before any data: skeleton, not blank.
  if (!data) {
    return <DashboardSkeleton />;
  }

  const seasons = data.league.seasons ?? [data.league.season];

  /* ONE season control, built once and handed to whichever ledger is on screen.
   * It used to render as a full-width row above everything, which cost a row and
   * left "which sections does this filter?" to memory. Compact, it rides the
   * head of the ledger it governs.
   *
   * Owners and the GM board never receive it: both read all-time, and an inert
   * pill still moves when tapped — which tells the reader a filter applied when
   * nothing changed. Bets has its own season control and does not get a second. */
  const yearControl = (
    <YearTabs
      compact
      seasons={seasons}
      current={data.selected_year}
      leagueId={leagueId}
      lens={data.selected_lens}
      tab={initialTab}
      currentSeason={data.league.season}
    />
  );
  const activityCount = data.total_trades ?? 0;

  return (
    <>
      {/* Agate — a soft error: stale data stays visible underneath (Failure
          Is A Headline, but this is a banner, not a full page — no colored
          pill background; the signed --neg color lives on the word, not a
          fill, per "The Signed Number"). */}
      {error && (
        <div role="alert" className="mb-4 flex items-center justify-between gap-3 border border-ink px-3 py-2">
          <span className="font-mono text-figure text-neg-strong">{error}</span>
          <button
            type="button"
            onClick={loadOrRefresh}
            className="shrink-0 font-mono text-label font-bold uppercase tracking-[0.1em] text-dim hover:text-ink"
          >
            Retry
          </button>
        </div>
      )}

      {/* Stale data stays visible while a new view loads; dim + aria-busy
          signal the in-flight refetch instead of blank-flashing the page. */}
      <div
        aria-busy={loading}
        className={loading ? "opacity-60 transition-opacity duration-150" : "transition-opacity duration-150"}
      >
        <LeagueHeader league={data.league} totalTrades={isNaN(activityCount) ? 0 : activityCount} />
        {/* What the numbers on this page can't see (e.g. a redraft league's
            unvalued draft picks). Renders nothing when there is nothing to
            disclose — absence, not an empty state. */}
        <LeagueNotes notes={data.warnings} />

        <DashboardTabs leagueId={leagueId} active={initialTab} />
        {/* The GM board carries its own all-time/per-season toggle. Franchises
            reads as all-time (grades, track record, H2H are career-wide), so the
            season tabs would be inert there. */}


        {initialTab === "dashboard" && (
          <>
            <HeadlineMoves data={data} leagueId={leagueId} />
            <StandingsTable
              sections="franchises"
              yearControl={yearControl}
              leagueId={leagueId}
              rows={data.standings}
              year={data.selected_year}
              currentSeason={data.league.season}
              youUserId={youUserId}
            />
          </>
        )}

        {initialTab === "trades" && (
          <TradesTab
            leagueId={leagueId}
            year={data.selected_year}
            rows={data.standings}
            currentSeason={data.league.season}
            youUserId={youUserId}
            yearControl={yearControl}
          />
        )}

        {initialTab === "owners" && (
          // The owners tab skips YearTabs (its franchises read all-time), so
          // it's the one tab with nothing between it and the masthead band —
          // the band's own bottom padding is colored fill, not page gutter,
          // so content sat flush against it. `--gutter`/`--gutter-sm` is the
          // same page-edge rhythm the Shell already uses to size the band's
          // own horizontal margins.
          <div className="mt-[var(--gutter-sm)] min-[701px]:mt-[var(--gutter)]">
            <OwnersTab
              leagueId={leagueId}
              owners={data.standings}
              profiles={profiles}
              onProfilesChange={setProfiles}
              youUserId={youUserId}
            />
          </div>
        )}

        {initialTab === "gm" && (
          <Leaderboard
            leagueId={leagueId}
            initialYear={data.selected_year}
            seasons={seasons}
            format={data.capabilities?.format}
          />
        )}

        {initialTab === "bets" && (
          <BetsTab leagueId={leagueId} owners={data.standings} />
        )}
      </div>
    </>
  );
}

/* ---------------------------------------------------------------------------
 * Agate — Failure Is A Headline (design_handoff_agate/DESIGN.md § "Named
 * rules"; `Agate System.dc.html` §07 Fig. 7.3). A mono kicker naming the
 * condition, an Archivo headline in plain words, one line of body, one ink
 * button. No illustration, no centered card.
 * ------------------------------------------------------------------------ */
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mt-16 max-w-md">
      <div className="font-mono text-label uppercase tracking-[0.14em] text-dim">
        Couldn&apos;t load
      </div>
      <h2 className="mt-2 font-display text-lead font-extrabold leading-[1.05] tracking-[-0.035em] text-ink">
        Something broke on the way in.
      </h2>
      <p className="mt-2 text-figure leading-relaxed text-body">{message}</p>
      <Button onClick={onRetry} className="mt-4 px-4 py-2">
        ↻ Try again
      </Button>
    </div>
  );
}
