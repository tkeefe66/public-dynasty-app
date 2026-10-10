import Link from "next/link";
import { AnalystArchive } from "@/components/AnalystArchive";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { analystArchive, analystShareState } from "@/lib/api";
import { publicAnalyst } from "@/lib/public-analyst";
import type { RecapMediaInfo } from "@/lib/recap-media";

export const dynamic = "force-dynamic";
export const metadata = { title: "Weekly recap · DyNASTY" };

export default async function AnalystPage({ params, searchParams }: {
  params: { id: string }; searchParams: { edition?: string };
}) {
  let data;
  try {
    data = await analystArchive(params.id);
  } catch {
    return <Shell><TopBar leagueId={params.id} />
      <h1 className="font-display text-lead font-extrabold">Weekly recap is unavailable.</h1>
      <p className="mt-4 text-body">We could not load the saved editions. Please reload the page to try again.</p>
      <Link href={`/league/${params.id}`} className="mt-5 inline-flex min-h-tap items-center underline">Back to league homepage</Link>
    </Shell>;
  }
  const editions = data.editions.filter(item => item.edition_type !== "results");
  const edition = searchParams.edition
    ? editions.find(item => `${item.season}-${item.week}` === searchParams.edition)
    : editions[0];
  let media: { token: string; info: RecapMediaInfo } | undefined;
  let mediaError = false;
  if (edition) {
    try {
      // Read existing publication only. Opening an archive must never enable sharing.
      const { token } = await analystShareState(params.id, edition.season, edition.week);
      const shared = token ? await publicAnalyst(token) : null;
      if (token && shared?.media && shared.status !== "withdrawn" &&
          shared.season === edition.season && shared.week === edition.week && shared.markdown === edition.markdown) {
        media = { token, info: shared.media };
      }
    } catch {
      mediaError = true;
    }
  }
  return <Shell><TopBar leagueId={params.id} />
    <AnalystArchive leagueId={params.id} editions={editions} selected={searchParams.edition} media={media} mediaError={mediaError} />
  </Shell>;
}
