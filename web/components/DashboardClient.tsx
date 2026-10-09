"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, dashboard, getMe, getProfiles, myLeagues, refreshStream } from "@/lib/api";
import { DashboardResp, DashboardYear, Lens, ProfilesMap } from "@/lib/types";
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
import { StateMessage } from "./furniture/StateMessage";

export type DashboardTab = "dashboard" | "trades" | "owners" | "gm" | "bets";

interface Props {
  leagueId: string;
  initialYear: DashboardYear;
  initialLens: Lens;
  initialTab: DashboardTab;
}

export function DashboardClient({ leagueId, initialYear, initialLens, initialTab }: Props) {
  const [data, setData] = useState<DashboardResp | null>(null);
  const [profiles, setProfiles] = useState<ProfilesMap>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [yahooReconnect, setYahooReconnect] = useState(false);
  const [refreshProblem, setRefreshProblem] = useState(false);
  const [retryStopped, setRetryStopped] = useState(false);
  const loadVersion = useRef(0);
  const refreshWatcher = useRef<ReturnType<typeof refreshStream> | null>(null);
  const coldStartKeys = useRef(new Map<string, string>());
  const [events, setEvents] = useState<
    { stage: string; message?: string; done?: number; total?: number }[]
  >([]);
  // The signed-in user's Sleeper id, for "your franchise" highlighting.
  const [youUserId, setYouUserId] = useState<string | null>(null);
  // Only season-filtered ledgers opt into the active-season data default.
  // Keep initialYear for navigation so a career-wide view's fallback to All
  // does not become an explicit user choice when returning to the dashboard.
  const requestedYear = initialYear === "auto" && initialTab !== "dashboard" && initialTab !== "trades"
    ? "all" : initialYear;

  const loadOrRefresh = useCallback(async (startNewAttempt = false) => {
    const version = ++loadVersion.current;
    const isCurrent = () => version === loadVersion.current;
    refreshWatcher.current?.close();
    refreshWatcher.current = null;
    setRefreshing(false);
    setError(null);
    setRefreshProblem(false);
    setRetryStopped(false);
    setYahooReconnect(false);
    setLoading(true);
    try {
      const d = await dashboard(leagueId, { year: requestedYear, lens: initialLens });
      if (!isCurrent()) return;
      setData(d);
      setLoading(false);
    } catch (err) {
      if (!isCurrent()) return;
      if (leagueId.includes(".l.") && err instanceof ApiError && [403, 409].includes(err.status) && /yahoo|not a member/i.test(err.message)) {
        setLoading(false);
        setYahooReconnect(true);
        setError(err.message);
      } else if (err instanceof ApiError && err.status === 409) {
        // Cold does not mean running. Reopen the saved job first, so a failed
        // first build never becomes a POST loop on reload or filter changes.
        setLoading(false);
        setRefreshProblem(true);
        let league;
        try {
          league = (await myLeagues()).find((item) => item.league_id === leagueId);
        } catch {
          if (isCurrent()) setError("We couldn't check the refresh status. Check again in a moment.");
          return;
        }
        if (!isCurrent()) return;
        if (!league) {
          setError("This league needs its first refresh. A league member can start it.");
          return;
        }
        const job = league.refresh_job;
        const stopped = job && ["cancelled", "superseded"].includes(job.state);
        setRetryStopped(Boolean(stopped && !startNewAttempt));
        const observeJob = job && job.state !== "succeeded" && !(startNewAttempt && stopped);
        if (startNewAttempt && stopped) coldStartKeys.current.delete(leagueId);
        if (!coldStartKeys.current.has(leagueId)) {
          coldStartKeys.current.set(leagueId, crypto.randomUUID());
        }
        setRefreshing(true);
        setEvents([]);
        refreshWatcher.current = refreshStream(leagueId, async (ev) => {
          if (!isCurrent()) return;
          setEvents((cur) => [...cur, ev]);
          if (ev.stage === "error") {
            setRefreshing(false);
            setError(ev.message || "The refresh stopped before it finished. Try again.");
            return;
          }
          if (ev.stage === "done") {
            coldStartKeys.current.delete(leagueId);
            try {
              const d = await dashboard(leagueId, {
                year: requestedYear, lens: initialLens,
              });
              if (isCurrent()) {
                setData(d);
                setRefreshProblem(false);
              }
            } catch {
              if (isCurrent()) setError("The refresh finished, but the dashboard couldn't load. Check its status again.");
            } finally {
              if (isCurrent()) setRefreshing(false);
            }
          }
        }, {
          jobId: observeJob ? job.id : undefined,
          idempotencyKey: coldStartKeys.current.get(leagueId),
        });
      } else {
        setLoading(false);
        setError(err instanceof Error ? err.message : "Couldn't load the dashboard.");
      }
    }
  }, [leagueId, requestedYear, initialLens]);

  useEffect(() => {
    void loadOrRefresh();
    return () => {
      ++loadVersion.current;
      refreshWatcher.current?.close();
      refreshWatcher.current = null;
    };
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
    if (yahooReconnect) return (
      <section className="mt-8">
        <p role="alert" className="text-body">{error}</p>
        <Button as="link" href="/leagues/add?provider=yahoo" className="mt-5 px-4 py-2">Connect Yahoo</Button>
      </section>
    );
    return <ErrorState
      message={error}
      refreshProblem={refreshProblem}
      checkStatus={refreshProblem && !retryStopped}
      onRetry={() => void loadOrRefresh(retryStopped)}
    />;
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
            onClick={() => void loadOrRefresh()}
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

        <DashboardTabs leagueId={leagueId} active={initialTab} year={String(initialYear)} lens={initialLens} />
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

function ErrorState({ message, onRetry, refreshProblem, checkStatus }: {
  message: string;
  onRetry: () => void;
  refreshProblem: boolean;
  checkStatus: boolean;
}) {
  return (
    <div role="alert">
      <StateMessage
        className="mt-16 max-w-md"
        tone="negative"
        kicker={refreshProblem ? "Refresh status" : "Couldn't load"}
        headline={refreshProblem ? "Your league is saved. Its data isn't ready yet." : "The dashboard couldn't load."}
        body={message}
        action={
          <Button onClick={onRetry} className="px-4 py-2">
            {checkStatus ? "Check status" : "Try again"}
          </Button>
        }
      />
    </div>
  );
}
