import type { Metadata } from "next";
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { TradeSidePanel } from "@/components/TradeSidePanel";
import { TradeHero } from "@/components/TradeHero";
import { TradeScoreboard } from "@/components/TradeScoreboard";
import { TradeFindings } from "@/components/TradeFindings";
import { TradeProductionCard } from "@/components/TradeProductionCard";
import { TradeReceiptButton } from "@/components/TradeReceiptButton";
import { tradeDetail } from "@/lib/api";
import { tradeReceipt } from "@/lib/receipts";
import { LensMargins, LensWinners } from "@/lib/types";

export const dynamic = "force-dynamic";

const EMPTY_WINNERS: LensWinners = { value: null, total: null, regular: null, playoff: null, toilet: null };
const EMPTY_MARGINS: LensMargins = { value: null, total: null, regular: null, playoff: null, toilet: null };

export async function generateMetadata(
  { params }: { params: { id: string; tid: string } },
): Promise<Metadata> {
  try {
    const d = await tradeDetail(params.id, params.tid);
    const title = d.story?.verdict ?? `${d.sides[0]?.owner_name} ↔ ${d.sides[1]?.owner_name}`;
    return {
      title,
      description: `${d.league_name} · ${d.season}`,
      openGraph: { title, type: "article" },
      twitter: { card: "summary_large_image", title },
    };
  } catch {
    return { title: "Trade · DyNASTY", twitter: { card: "summary_large_image" } };
  }
}

export default async function TradePage({
  params,
}: {
  params: { id: string; tid: string };
}) {
  let data;
  try {
    data = await tradeDetail(params.id, params.tid);
  } catch {
    return (
      <Shell>
        <TopBar />
        <h1 className="mt-16 font-display text-lead font-extrabold tracking-[var(--track-lead)]">
          Trade not found.
        </h1>
        <Link href={`/league/${params.id}`} className="text-dim underline">
          ← Back
        </Link>
      </Shell>
    );
  }
  // Full league owner map first (covers a pick's original owner who isn't a
  // party to this trade), then the trade's own sides take precedence.
  const displayNames: Record<string, string> = {
    ...(data.owner_names ?? {}),
    ...Object.fromEntries(data.sides.map((s) => [s.user_id, s.owner_name])),
  };
  // player_id -> display name, gathered from the haul breakdowns (incl. the
  // terminal players that flipped picks became), so the production drill and
  // injury block show names instead of raw Sleeper ids.
  const playerNameMap: Record<string, string> = {};
  for (const s of data.sides) {
    for (const a of s.received ?? []) {
      if (a.player_id && a.name) playerNameMap[a.player_id] = a.name;
    }
    for (const a of s.breakdown ?? []) {
      if (a.player_id && a.label) playerNameMap[a.player_id] = a.label;
      for (const b of a.flip?.became ?? []) {
        if (b.player_id && b.label) playerNameMap[b.player_id] = b.label;
      }
    }
  }
  // uid -> player_id -> the week they were dropped, for the side ledgers'
  // "DROPPED WK n" tag (covers both directly-received players and terminal
  // players a flipped pick became — `departures` carries both).
  const dropWeeksByUid: Record<string, Record<string, number>> = {};
  for (const [uid, deps] of Object.entries(data.departures ?? {})) {
    dropWeeksByUid[uid] = {};
    for (const d of deps) {
      if (d.kind === "dropped") dropWeeksByUid[uid][d.player_id] = d.week;
    }
  }

  const winnersByLens = data.winners_by_lens ?? EMPTY_WINNERS;
  const marginsByLens = data.margins_by_lens ?? EMPTY_MARGINS;
  const call = data.call ?? "none";
  const lensTally = data.lens_tally ?? "0";

  return (
    <Shell>
      <TopBar activeNav="trades" leagueId={params.id} />
      <section>
        <Link href={`/league/${params.id}`}
              className="font-mono text-label text-dim hover:text-ink">
          ← All trades
        </Link>
        <div className="mt-3">
          <TradeHero
            date={data.date}
            story={data.story}
            sides={data.sides}
            lopsidedness={data.lopsidedness ?? 0}
            winnersByLens={winnersByLens}
            marginsByLens={marginsByLens}
            call={call}
            lensTally={lensTally}
            receipt={
              <TradeReceiptButton
                claim={tradeReceipt(data)}
                path={`/league/${params.id}/trade/${params.tid}`}
              />
            }
          />
        </div>

        <TradeScoreboard
          margins={marginsByLens}
          winners={winnersByLens}
          sides={data.sides}
          call={call}
          lensTally={lensTally}
        />

        <div className="mt-5 flex flex-col gap-8">
          {data.sides.map((s) => (
            <TradeSidePanel
              key={s.user_id}
              side={s}
              winnersByLens={winnersByLens}
              marginsByLens={marginsByLens}
              call={call}
              leagueId={params.id}
              dropWeeks={dropWeeksByUid[s.user_id]}
            />
          ))}
        </div>

        <TradeFindings
          sides={data.sides}
          winner_user_id={data.winner_user_id ?? null}
          series={data.production_series}
        />

        {data.production_week_axis && data.production_series && (
          <div className="mt-8 border-t border-rule pt-5">
            <TradeProductionCard
              axis={data.production_week_axis}
              series={data.production_series}
              verdict={data.production_verdict}
              names={displayNames}
              playerNames={playerNameMap}
              injury={data.injury}
              weekPhases={data.production_week_phases}
              departures={data.departures}
            />
          </div>
        )}
      </section>
    </Shell>
  );
}
