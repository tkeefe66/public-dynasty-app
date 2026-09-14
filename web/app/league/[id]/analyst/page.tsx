import Link from "next/link";
import { AnalystArchive } from "@/components/AnalystArchive";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { analystArchive } from "@/lib/api";

export const dynamic = "force-dynamic";
export const metadata = { title: "The Analyst · DyNASTY" };

export default async function AnalystPage({ params, searchParams }: {
  params: { id: string }; searchParams: { edition?: string };
}) {
  let data;
  try {
    data = await analystArchive(params.id);
  } catch {
    return <Shell><TopBar leagueId={params.id} />
      <h1 className="font-display text-lead font-extrabold">The Analyst is unavailable.</h1>
      <p className="mt-4 text-body">We could not load the saved editions. Please reload the page to try again.</p>
      <Link href={`/league/${params.id}`} className="mt-5 inline-flex min-h-tap items-center underline">Back to league homepage</Link>
    </Shell>;
  }
  return <Shell><TopBar leagueId={params.id} />
    <AnalystArchive leagueId={params.id} editions={data.editions} selected={searchParams.edition} />
  </Shell>;
}
