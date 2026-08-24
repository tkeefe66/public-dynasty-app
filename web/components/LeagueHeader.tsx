"use client";

import { useEffect, useState } from "react";
import { LeagueSummary } from "@/lib/types";
import { LeagueSwitcher } from "./LeagueSwitcher";

/**
 * The masthead — `.design/components/ledger/StampBand.{prompt.md,jsx}`.
 *
 * A ROUNDED PANEL, not a full-bleed slab. `StampBand.jsx` draws
 * `borderRadius: var(--radius)` on a `var(--stamp)` ground with
 * `var(--stamp-ink)` reversed out of it, and it sits in the page like every
 * other panel. This band used to cancel `Shell`'s `px-3 sm:px-6 lg:px-8` with
 * matching negative margins so the cobalt bled to both page edges — an
 * Agate-era decision ("the kicker+H1+subline block ... bled to the page edge",
 * `Agate System.dc.html` §02) that the docstring was still citing after Agate
 * was retired. Furniture has one radius and one elevation, and a masthead is
 * not exempt from either.
 *
 * Stamp is a GROUND you reverse type out of, never a word painted on paper —
 * the nameplate takes `--stamp-ink`, the folio line `--stamp-ink-dim`. Never an
 * alpha of the reversed ink: `text-stamp-ink/70` is 3.97:1 at this size and
 * small reversed type gets no large-text exemption, which is the defect the
 * drawn second ink exists to prevent.
 *
 * The league name IS the picker. `LeagueSwitcher` moved out of the chrome strip
 * and into the nameplate, so the league is stated exactly once per screen
 * instead of twice (mono chip above, nameplate below). Nameplate tiers are
 * unchanged and still a pure function of `name.length` computed at render time
 * — not measured in the browser — so the first paint is already correct.
 */
/* The four tiers, reading the design system's own `--nameplate-*` tokens rather
 * than restating their pixel values. Written as literal arbitrary-value classes
 * (never string-interpolated) so Tailwind's JIT can find them. */
const NAMEPLATE_TIERS: { max: number; classes: string }[] = [
  { max: 14, classes: "text-[length:var(--nameplate-1-sm)] min-[701px]:text-[length:var(--nameplate-1)]" },
  { max: 24, classes: "text-[length:var(--nameplate-2-sm)] min-[701px]:text-[length:var(--nameplate-2)]" },
  { max: 38, classes: "text-[length:var(--nameplate-3-sm)] min-[701px]:text-[length:var(--nameplate-3)]" },
  { max: Infinity, classes: "text-[length:var(--nameplate-4-sm)] min-[701px]:text-[length:var(--nameplate-4)]" },
];

function nameplateClasses(name: string): string {
  const len = name.length;
  return (NAMEPLATE_TIERS.find((t) => len <= t.max) ?? NAMEPLATE_TIERS[NAMEPLATE_TIERS.length - 1])
    .classes;
}

/** `/api/nfl-state` (`api/app/routes/nfl_state.py`) — every field nullable. */
interface NflState {
  season_type?: string | null;
  week?: number | null;
}

/**
 * Where the league calendar stands, or `null` when it is not knowable yet.
 *
 * `null` is the answer for an unresolved fetch, a failed one, an unrecognised
 * `season_type`, AND a regular season with no week number — every one of those
 * renders NOTHING rather than a guess. The old segment here was
 * `refreshed ${new Date(...).toLocaleString()}`, which put a seconds-precise
 * machine timestamp in the folio ("8/14/2026, 8:35:01 PM") and was long enough
 * to wrap the meta line onto a second row on a phone. Cache freshness is not
 * what a manager opens this page to learn; where the season is, is.
 */
export function phaseLabel(state: NflState | null | undefined): string | null {
  const type = String(state?.season_type ?? "").toLowerCase();
  if (type === "off") return "Offseason";
  if (type === "pre") return "Preseason";
  if (type === "post") return "Postseason";
  if (type === "regular") {
    const week = state?.week;
    return typeof week === "number" && week > 0 ? `Week ${week}` : null;
  }
  return null;
}

/**
 * One fetch on mount, silent on every failure — the same contract `WeekNote`
 * established for this endpoint. `/api/nfl-state` is user-scoped and cached
 * in-process on the backend, so both callers together still cost one upstream
 * call per process per five minutes.
 */
function usePhaseLabel(): string | null {
  const [phase, setPhase] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/nfl-state")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: NflState | null) => {
        if (cancelled) return;
        setPhase(phaseLabel(d));
      })
      .catch(() => {
        // Silent by contract: an unknown phase is an absent segment, never an
        // error in the masthead of an otherwise working page.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return phase;
}

export function LeagueHeader({ league, totalTrades }: {
  league: LeagueSummary;
  totalTrades: number;
}) {
  const phase = usePhaseLabel();

  return (
    <div className="mb-6 rounded-panel bg-stamp px-4 pb-5 pt-4 text-stamp-ink shadow-panel sm:px-6 sm:pb-6 sm:pt-5">
      {/* Fixed band height across every tier — a flex box bottom-aligns 1 or 2
          lines of type inside a constant-height container instead of letting
          the band grow and shrink with the tier. */}
      <div className="flex min-h-[40px] items-end min-[701px]:min-h-[58px]">
        <h1
          className="min-w-0 flex-1 font-display font-extrabold tracking-[var(--track-nameplate)]"
          style={{ lineHeight: 0.95 }}
        >
          {/* The name is the control. `LeagueSwitcher` keeps its own list,
              admin row, outside-click and Escape handling — this is where it
              is drawn, not a second implementation of it. */}
          <LeagueSwitcher
            currentLeagueId={league.league_id}
            variant="masthead"
            name={league.name}
            labelClassName={nameplateClasses(league.name)}
          />
        </h1>
      </div>
      {/* The folio line. `--stamp-ink-dim`, NOT an opacity of `--stamp-ink`.
          Ends in the league's calendar phase — Offseason · Preseason · Week N ·
          Postseason — and renders that segment only once it is known. */}
      <p className="mt-1.5 font-mono text-label uppercase tracking-[0.11em] text-stamp-ink-dim">
        {league.total_rosters} teams · {totalTrades} trade{totalTrades === 1 ? "" : "s"} graded
        {phase ? ` · ${phase}` : ""}
      </p>
    </div>
  );
}
