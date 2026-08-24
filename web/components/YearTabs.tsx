"use client";

import { useRouter } from "next/navigation";
import { SegmentControl } from "@/components/SegmentControl";
import { Year } from "@/lib/types";

interface Props {
  seasons: number[];
  current: Year;
  leagueId: string;
  lens: string;
  tab?: string;
  /** The league's active/most-recent season. Rendered in full ink among the
   *  otherwise-dim past years — a "now" cue distinct from the inverted
   *  "selected" year. */
  currentSeason?: number;
  /** COMPACT: two-digit years and no `Year` kicker, sized to ride a section
   *  head instead of owning a row of its own. The century is identical across
   *  every option, so it carries no information and is the first thing to go
   *  when the control has to fit beside a heading. */
  compact?: boolean;
}

/**
 * The year line — it IS a SegmentControl now. `.design/templates/dashboard/
 * Dashboard.dc.html` renders the season selector as a SegmentControl with
 * `label: "Season"` and options `["All-time","2025","2024","2023"]` —
 * exactly this component's content, so the year line is not a separate
 * dialect under Furniture. Wraps at narrow widths (SegmentControl's own
 * `flex-wrap`) rather than the old full-width `overflow-x-auto` — the
 * reason for that drift-guard exception was this scrolling year line, and
 * losing the exception is the point, not a regression.
 *
 * The "Year" whisper label stays as its own kicker beside the pill, and the
 * "now" cue (current season rendered in full ink among the otherwise-dim
 * inactive years) survives by styling that one option's label directly —
 * only when it isn't also the active/selected segment, since the active
 * segment's stamp-ink text already wins.
 */
export function YearTabs({ seasons, current, leagueId, lens, tab, currentSeason, compact = false }: Props) {
  const router = useRouter();
  const choose = (y: Year) => {
    const sp = new URLSearchParams();
    if (y !== "all") sp.set("year", String(y));
    if (lens !== "ktc") sp.set("lens", lens);
    if (tab && tab !== "dashboard") sp.set("tab", tab);
    const qs = sp.toString();
    router.push(`/league/${leagueId}${qs ? `?${qs}` : ""}`);
  };

  // All-time first, then years most-recent-first — `seasons` arrives
  // ascending from the API, so reverse it here rather than upstream.
  const items: { key: Year; label: React.ReactNode }[] = [
    { key: "all" as Year, label: compact ? "All" : "All-time" },
    ...[...seasons].reverse().map((s) => {
      const isNow = s === currentSeason;
      const active = s === current;
      // Two digits when compact. `String(s).slice(-2)` rather than arithmetic:
      // the label is a name for a season, not a number to compute with.
      const text = compact ? String(s).slice(-2) : String(s);
      return {
        key: s as Year,
        label: isNow && !active ? <span className="text-ink">{text}</span> : text,
      };
    }),
  ];

  // No wrapper row and no "Year" kicker at either size. The standalone branch
  // — a kicker plus a full-width row of its own — is DELETED rather than kept
  // for a caller that might want it: nothing rendered it (DashboardClient is
  // the only consumer and passes `compact`), and a spare variant of a control
  // is how a second dialect gets back in. `compact` now only decides the label
  // width, which is the one thing it was ever really deciding.
  return (
    <SegmentControl<Year>
      aria-label="Filter by season"
      options={items}
      value={current}
      onChange={choose}
      className="shrink-0"
    />
  );
}
