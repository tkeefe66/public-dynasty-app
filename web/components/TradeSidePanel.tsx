import Link from "next/link";
import { LensMargins, LensWinners, StandingAtTrade, TradeCall, TradeSideView } from "@/lib/types";
import { OwnerLabel } from "./OwnerLabel";
import { LENS_LABEL_LOWER, LENS_ORDER, soleDecidedLens } from "@/lib/trade-lens";
import { StatTotals, TradeStatTable, realizedTotals } from "./TradeStatTable";

interface Props {
  side: TradeSideView;
  winnersByLens: LensWinners;
  marginsByLens: LensMargins;
  call: TradeCall;
  /** When set, the owner header links through to the owner's franchise page. */
  leagueId?: string;
  /** player_id -> the week this side dropped them. */
  dropWeeks?: Record<string, number>;
}

/** The header word beside the owner name — derived straight from
 *  `winnersByLens`/`call`, never a local recomputation (DESIGN.md §
 *  "Figures Reconcile"). No word at all for a "none" call: nobody prevailed,
 *  and saying so twice (stamp + every side panel) is noise. */
function statusWord(
  userId: string, call: TradeCall, winnersByLens: LensWinners,
): { text: string; tone: "pos" | "dim" } | null {
  if (call === "none") return null;
  const wins = LENS_ORDER.filter((l) => winnersByLens[l] === userId).length;

  // ONE decided lens is not a sweep. `call` is "unanimous" whenever every
  // decided lens went to one side, which includes the case where only one
  // lens could be decided at all — the normal state of a trade nobody has
  // played yet, since all four production lenses sit at 0 for both sides and
  // are therefore unscored. Saying "Prevailed"/"Lost" there claims a verdict
  // the data cannot carry. Name the lens instead.
  const sole = soleDecidedLens(winnersByLens);
  if (sole) {
    return winnersByLens[sole] === userId
      ? { text: `Ahead on ${LENS_LABEL_LOWER[sole]}`, tone: "pos" }
      : null;  // the other side is not "losing" on one lens — say nothing.
  }

  if (call === "unanimous") {
    return wins > 0 ? { text: "Prevailed", tone: "pos" } : { text: "Lost", tone: "dim" };
  }
  // split
  return wins > 0
    ? { text: `Won ${wins}`, tone: "pos" }
    : { text: "Won 0", tone: "dim" };
}

export function TradeSidePanel({
  side, winnersByLens, marginsByLens, call, leagueId, dropWeeks,
}: Props) {
  // The TOTAL reflects what the side actually realized: kept assets contribute
  // their own line, flipped assets contribute what they became.
  const totals: StatTotals = realizedTotals(side.breakdown);
  const word = statusWord(side.user_id, call, winnersByLens);

  const standing: StandingAtTrade | null | undefined = side.at_trade_standing;
  const record = standing
    ? `${standing.wins}-${standing.losses}${standing.ties > 0 ? `-${standing.ties}` : ""}`
    : null;

  const ownerBlock = (
    <OwnerLabel
      owner={{ user_id: side.user_id, owner_name: side.owner_name,
               team_name: side.team_name, avatar_url: side.avatar_url }}
      variant="full"
    />
  );

  return (
    <TradeStatTable
      ownerName={side.owner_name}
      userId={side.user_id}
      header={
        <div className="flex items-baseline justify-between gap-2">
          <div className="min-w-0">
            {leagueId ? (
              <Link
                href={`/league/${leagueId}/owner/${side.user_id}`}
                className="inline-block hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ringfocus)]"
              >
                {ownerBlock}
              </Link>
            ) : ownerBlock}
            {standing && (
              <div className="hidden sm:block font-mono text-figure text-dim mt-1">
                #{standing.rank} of {standing.total_teams} · {record} · {standing.points_for.toFixed(1)} pts
              </div>
            )}
            {/* THE BENCH-MISS READING, finally rendered.
                `start_pct` has been computed here since the trade view was
                written and typed all the way to this file, but nothing ever
                displayed it — its only consumer was the "Barely played"
                finding, which fires solely when one side is under 50% AND
                another cleared 70%. A side that started 60% of its haul, which
                is a real amount of points left on a bench, was never told.
                Absent (never "0%") when the haul has not played — see
                api/app/services/start_rate.py. */}
            {side.start_pct != null && (
              <div className="mt-1 font-mono text-label uppercase tracking-[0.11em] text-dim">
                Started {Math.round(side.start_pct * 100)}% of the haul
              </div>
            )}
          </div>
          {word && (
            <span className={`shrink-0 font-mono text-label uppercase tracking-[0.11em] ${
              word.tone === "pos" ? "text-pos-strong" : "text-dim"
            }`}>
              {word.text}
            </span>
          )}
        </div>
      }
      rows={side.breakdown}
      totals={totals}
      winnersByLens={winnersByLens}
      marginsByLens={marginsByLens}
      dropWeeks={dropWeeks}
    />
  );
}
