import Link from "next/link";
import type { WeekRecap } from "@/lib/types";
import { AnalystMasthead } from "./AnalystMasthead";
import { Panel } from "./furniture/Panel";

/** Completed results tell the story; the publication footer opens the same edition. */
export function WeekRecapLead({ recap, leagueId, week }: {
  recap?: WeekRecap | null;
  leagueId: string;
  week?: number | null;
}) {
  const high = recap?.high_score;
  const highName = high?.owner?.owner_name ?? high?.user_id;
  const blowout = recap?.blowout;
  const winner = blowout?.winner?.owner_name ?? blowout?.winner_user_id;
  const loser = blowout?.loser?.owner_name ?? blowout?.loser_user_id;
  const traded = recap?.traded_points;
  const tradedName = traded?.owner?.owner_name ?? traded?.user_id;
  // Match the source IDs, not editable display names. Two owners can share a name.
  const sameOwner = high && traded && high.user_id === traded.user_id;
  const recapWeek = recap?.week ?? week;
  const href = `/league/${leagueId}/analyst${recap ? `?edition=${recap.season}-${recap.week}` : ""}`;

  return (
    <section className="mb-8" aria-label={recapWeek ? `Week ${recapWeek} recap` : "Week recap"}>
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3 sm:px-7">
          <p className="font-mono text-label uppercase tracking-[var(--track-label)]">
            {recapWeek ? `Week ${recapWeek} recap` : "Week recap"}
          </p>
          <p className="font-mono text-label uppercase tracking-[var(--track-label)] text-dim">
            {recap ? `${recap.season} · Final scores` : "Awaiting final scores"}
          </p>
        </div>

        {recap && high && blowout ? (
          <div className="grid md:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
            <div className="min-w-0 px-5 py-6 sm:px-7 sm:py-7">
              <h2 className="max-w-[22ch] break-words font-display text-lead font-extrabold leading-[1.05] tracking-[var(--track-lead)] sm:text-nameplate">
                {highName} set the bar.
              </h2>
              <p className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1" aria-label={`High score: ${highName}, ${high.points.toFixed(1)} points`}>
                <span className="whitespace-nowrap font-mono text-nameplate font-semibold tabular leading-none tracking-[var(--track-lead)]">{high.points.toFixed(1)}</span>
                <span className="text-prose text-dim">points. The week&rsquo;s high score.</span>
              </p>
              {traded ? (
                <p className="mt-4 max-w-[56ch] text-prose leading-relaxed text-body">
                  {sameOwner ? <>
                    Trade-acquired starters supplied <strong className="font-mono font-semibold text-ink">{traded.points.toFixed(1)}</strong> of those points, the most in the league.
                  </> : <>
                    {tradedName} led the trade returns: <strong className="font-mono font-semibold text-ink">{traded.points.toFixed(1)}</strong> points from trade-acquired starters.
                  </>}
                </p>
              ) : null}
            </div>

            <div className="min-w-0 border-t border-rule bg-surface-sunk px-5 py-6 sm:px-7 sm:py-7 md:border-l md:border-t-0">
              <h3 className="break-words font-display text-lead font-bold leading-tight tracking-[var(--track-lead)]">
                {winner} over {loser}.
              </h3>
              <p className="mt-4 font-mono text-nameplate tabular leading-none tracking-[var(--track-lead)]" aria-label={`Biggest margin: ${winner} beat ${loser} by ${blowout.margin.toFixed(1)} points`}>
                {blowout.margin > 0 ? "+" : ""}{blowout.margin.toFixed(1)}
              </p>
              <p className="mt-3 text-prose text-body">The week&rsquo;s widest margin.</p>
            </div>
          </div>
        ) : (
          <div className="px-5 py-7 sm:px-7">
            <h2 className="max-w-[28ch] font-display text-lead font-extrabold leading-tight tracking-[var(--track-lead)]">This week&rsquo;s story is still being written.</h2>
            <p className="mt-3 max-w-[65ch] text-prose leading-relaxed text-body">High scores, biggest margins, and trade-acquired starter points land once the week is final. The Analyst keeps each published edition in the archive.</p>
          </div>
        )}

        <AnalystMasthead compact>
          <Link href={href} className="inline-flex min-h-tap w-full items-center justify-between gap-4 rounded-sm bg-bg px-4 py-3 font-display text-name font-bold text-ink transition-colors hover:bg-surface sm:w-auto">
            {recap ? `Read the Week ${recap.week} roast` : "Browse The Analyst"}
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" className="shrink-0">
              <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Link>
        </AnalystMasthead>
      </Panel>
    </section>
  );
}
