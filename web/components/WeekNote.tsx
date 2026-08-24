"use client";

import { useEffect, useState } from "react";

/**
 * Agate — the week note (followup C2). Drawn at the right end of the nav strip
 * in `design-system/templates/Dashboard.dc.html`: mono 9px, 0.14em tracking,
 * uppercase, `--dim`, reading exactly **"Currently it is Week 14"**.
 *
 * Renders **nothing** until the week is known, on any error, and outside the NFL
 * regular season. Only the in-season case was drawn, so rather than invent
 * offseason copy the note simply isn't there — which is also why it degrades to
 * silence instead of a placeholder: chrome that says "—" is noise.
 *
 * Fetches once on mount. `/api/nfl-state` is user-scoped and in-process cached
 * on the backend, so this costs one upstream call per process per five minutes
 * no matter how many page views ask.
 */
export function WeekNote() {
  const [week, setWeek] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/nfl-state")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d) return;
        // Only the regular season is drawn; the NFL postseason is the league's
        // offseason, so the note stays silent there.
        if (String(d.season_type ?? "").toLowerCase() !== "regular") return;
        if (typeof d.week === "number" && d.week > 0) setWeek(d.week);
      })
      .catch(() => {
        // Silent by contract — the note is a whisper, not a status page.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (week === null) return null;
  return (
    <span className="hidden shrink-0 whitespace-nowrap font-mono text-label uppercase tracking-[0.14em] text-dim sm:inline">
      Currently it is Week {week}
    </span>
  );
}
