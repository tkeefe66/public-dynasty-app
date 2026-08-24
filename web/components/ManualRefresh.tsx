"use client";

import { useState } from "react";
import { refreshStream } from "@/lib/api";
import { ProgressModal } from "./ProgressModal";
import { EntryCard, Meta, MetaLine } from "./furniture/EntryCard";
import { SectionHead } from "./furniture/SectionHead";

interface Props {
  leagueId: string;
  /** Teams in the league — the owner-name roll this page already loaded. */
  teams?: number | null;
  /** Entry-point season from the membership row. */
  season?: number | null;
  /** Whether a chain cache exists. `null` when membership couldn't be read. */
  warm?: boolean | null;
}

/**
 * Admin tooling: the state of this league's cached data, and the action that
 * rebuilds it.
 *
 * It reads as a small card rather than a bare button because "refresh" is only
 * meaningful next to what you'd be refreshing. The facts are the ones actually
 * available without a dashboard call — that endpoint returns `409 cache cold`
 * until a refresh has run, so fetching it here to describe a cold league would
 * fail exactly when this card matters most.
 *
 * LAST REFRESHED IS SESSION-LOCAL, deliberately. Nothing on `/api/me/leagues`
 * carries a build timestamp, so this shows the refresh you ran on this page and
 * "—" otherwise. Inventing a time from the cache's mtime would be a different
 * claim than the one the label makes.
 *
 * The action is the design system's GHOST button, not a second stamp fill:
 * `.design/components/controls/Button.jsx` — "a 1.5px --rule-strong outline
 * that darkens to ink on hover, never a second fill: two filled buttons side by
 * side make neither of them primary." The one primary on this page is
 * `Save names`. The 44px floor is unconditional and applies here too.
 */
export function ManualRefresh({ leagueId, teams, season, warm }: Props) {
  const [refreshing, setRefreshing] = useState(false);
  const [events, setEvents] = useState<{ stage: string; message?: string }[]>([]);
  const [status, setStatus] = useState<"idle" | "done" | "error">("idle");
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);

  function trigger() {
    setRefreshing(true);
    setEvents([]);
    setStatus("idle");
    refreshStream(leagueId, (ev) => {
      setEvents((cur) => [...cur, ev]);
      if (ev.stage === "done") {
        setRefreshing(false);
        setStatus("done");
        setLastRefreshed(
          new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        );
        setTimeout(() => setStatus("idle"), 3000);
      } else if (ev.stage === "error") {
        setRefreshing(false);
        setStatus("error");
      }
    });
  }

  return (
    <section>
      <SectionHead title="Data" meta="Admin only" />

      <EntryCard>
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
            Last refreshed
          </span>
          <span className="font-mono text-figure tabular text-ink">
            {refreshing ? "Refreshing…" : (lastRefreshed ?? "—")}
          </span>
        </div>

        {/* The card's ONE hairline, separating headline from detail. No divider
            between the facts themselves — the card's edge is the boundary. */}
        <MetaLine>
          <Meta label="Teams">{teams != null ? teams : "—"}</Meta>
          <Meta label="Season">{season != null ? season : "—"}</Meta>
          <Meta label="Cache" tone={warm === false ? "dim" : undefined}>
            {warm == null ? "—" : warm ? "Built" : "Not built"}
          </Meta>
        </MetaLine>

        <button
          type="button"
          onClick={trigger}
          disabled={refreshing}
          className="mt-3 inline-flex min-h-tap w-full items-center justify-center gap-2 rounded-sm border-[1.5px] border-rule-strong bg-transparent px-4 font-mono text-label font-bold uppercase tracking-[0.11em] text-ink transition-colors hover:border-ink disabled:cursor-not-allowed disabled:border-rule disabled:text-dim min-[701px]:w-auto"
        >
          {refreshing ? "Refreshing…" : "Refresh data"}
        </button>
      </EntryCard>

      {/* Status lines sit on `--bg`, so they take the -strong half of the pair:
          the base tone is tuned for the white --surface a card draws. */}
      {/* PERSISTENT live region. Mounting a node that already carries its text
          is the classic way to lose an announcement — VoiceOver and NVDA
          commonly miss a region that appears together with its content. The
          node is always in the DOM; only its text changes. (The sibling
          `OwnerNamesForm` already did this correctly; this one did not.) */}
      <p
        aria-live="polite"
        className={`mt-2 font-mono text-label uppercase tracking-[0.11em] text-pos-strong ${
          status === "done" ? "" : "sr-only"
        }`}
      >
        {status === "done" ? "Refresh complete." : ""}
      </p>
      {status === "error" && (
        <p
          role="alert"
          className="mt-2 font-mono text-label uppercase tracking-[0.11em] text-neg-strong"
        >
          Refresh failed. Try again.
        </p>
      )}
      <ProgressModal open={refreshing} events={events} />
    </section>
  );
}
