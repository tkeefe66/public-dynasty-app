"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, ownerDetail } from "@/lib/api";
import { OwnerDetailResp, ProfilesMap, StandingRow } from "@/lib/types";
import { winName } from "@/lib/swagger";
import { OwnerLabel } from "./OwnerLabel";
import { OwnerDeepDive } from "./OwnerDeepDive";
import { franchiseLetterTone } from "./ownerdeepdive/util";
import { IndeterminateBar } from "./furniture/IndeterminateBar";
import { StateMessage } from "./furniture/StateMessage";

/** Desktop swaps the pane inline; mobile lets the <Link> navigate to the full
 *  owner page (same deep-dive component). */
function isWide(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia("(min-width: 1024px)").matches;
}

interface Props {
  leagueId: string;
  owners: StandingRow[];
  profiles: ProfilesMap;
  onProfilesChange: (profiles: ProfilesMap) => void;
  youUserId?: string | null;
}

export function OwnersTab({ leagueId, owners, profiles, onProfilesChange, youUserId }: Props) {
  const [selected, setSelected] = useState<string | null>(
    owners[0]?.user_id ?? null,
  );
  const [details, setDetails] = useState<Record<string, OwnerDetailResp>>({});
  const [loadingUid, setLoadingUid] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected || details[selected]) return;
    let cancelled = false;
    setLoadingUid(selected);
    setError(null);
    ownerDetail(leagueId, selected)
      .then((d) => {
        if (!cancelled) setDetails((m) => ({ ...m, [selected]: d }));
      })
      .catch((e) => {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 409
            ? "Still loading — refresh in a moment."
            : "Couldn't load this franchise.",
        );
      })
      .finally(() => {
        if (!cancelled) setLoadingUid(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, leagueId, details]);

  if (owners.length === 0) {
    return (
      <StateMessage
        kicker="No franchises"
        headline="The league's franchises will be listed here."
        body="They appear as soon as the league's rosters have been pulled."
      />
    );
  }

  const detail = selected ? details[selected] : undefined;
  const others = owners
    .filter((o) => o.user_id !== selected)
    .map((o) => ({
      user_id: o.user_id,
      name: winName(o.user_id, o.owner.owner_name, profiles),
    }));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-5">
      {/* Roster rail */}
      {/* max-w cap keeps rows from stretching full-bleed in the single-column
          band (≤1023px), where name + grade would otherwise sit at opposite
          edges with a wide dead gap. At lg the grid track is already 240px. */}
      <nav aria-label="Franchises" className="flex flex-col gap-1 max-w-xl lg:max-w-none">
        <div className="flex justify-between items-baseline mb-1.5 px-1">
          <div className="text-prose font-bold tracking-tight">Franchise Grades</div>
          <div className="font-mono text-figure text-dim">{owners.length}</div>
        </div>
        {owners.map((o) => {
          const active = o.user_id === selected;
          const isYou = !!youUserId && o.user_id === youUserId;
          return (
            <Link
              key={o.user_id}
              href={`/league/${leagueId}/owner/${o.user_id}`}
              aria-current={active ? "true" : undefined}
              onClick={(e) => {
                if (isWide()) {
                  e.preventDefault();
                  setSelected(o.user_id);
                }
              }}
              className={
                "flex items-center gap-2 px-2 py-2 border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ringfocus)] "
                + (active
                  ? "bg-rule-lit border-ink"
                  : "border-transparent hover:bg-rule-lit hover:border-rule")
                + (isYou ? " you-marker" : "")
              }
            >
              <span className="font-mono text-figure text-dim w-5 shrink-0">#{o.rank}</span>
              <span className="min-w-0 flex-1 flex items-center gap-1.5">
                <OwnerLabel owner={o.owner} variant="compact" />
                {isYou && (
                  <span className="shrink-0 font-mono text-label tracking-[0.11em] text-dim">
                    YOU
                  </span>
                )}
              </span>
              {(() => {
                // Franchise Rating letter is the rail headline. `grade` is a
                // DIFFERENT verdict — the trade-scoped letter (net Trade
                // Value swing vs peers), computed off a completely different
                // signal set. StandingsTable's Trade Grades card carries the
                // same warning verbatim: "that grade is the trade-scoped
                // one, NOT the Franchise Rating letter ... they are
                // different verdicts". Falling back to it here rendered the
                // wrong verdict in identical styling, indistinguishable from
                // the real one — an absent Franchise letter must render as
                // absence, never as a stand-in metric.
                const letter = o.gm_letter ?? null;
                return (
                  <span
                    title="Franchise Rating"
                    className={`shrink-0 font-display text-name font-bold ${letter ? franchiseLetterTone(letter) : "text-dim"}`}
                  >
                    {letter ?? "—"}
                  </span>
                );
              })()}
            </Link>
          );
        })}
      </nav>

      {/* Deep-dive pane (desktop only; mobile taps through to the full page) */}
      <div className="hidden lg:block min-w-0">
        {error && !detail ? (
          <StateMessage
            tone="negative"
            kicker="Franchise didn't load"
            headline={error}
            body="Not you — us. Pick the franchise again once the backend answers."
          />
        ) : loadingUid === selected && !detail ? (
          <IndeterminateBar className="max-w-[220px]" label="Loading franchise" />
        ) : detail ? (
          <OwnerDeepDive
            leagueId={leagueId}
            detail={detail}
            profile={selected ? profiles[selected] : undefined}
            others={others}
            onProfilesChange={onProfilesChange}
          />
        ) : null}
      </div>
    </div>
  );
}
