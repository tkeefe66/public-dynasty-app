import type { Metadata } from "next";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { DashboardClient } from "@/components/DashboardClient";
import { dashboard } from "@/lib/api";
import { Year } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function generateMetadata(
  { params }: { params: { id: string } },
): Promise<Metadata> {
  try {
    const d = await dashboard(params.id);
    const title = `${d.league.name} · Franchise Ratings`;
    return {
      title,
      description: `Franchise Rating leaderboard for ${d.league.name}.`,
      twitter: { card: "summary_large_image", title },
    };
  } catch {
    return {
      title: "DyNASTY · Franchise Ratings",
      twitter: { card: "summary_large_image" },
    };
  }
}

export default function GmPage({
  params, searchParams,
}: {
  params: { id: string };
  searchParams: { year?: string };
}) {
  const year: Year =
    !searchParams.year || searchParams.year === "all"
      ? "all"
      : Number(searchParams.year);

  return (
    <Shell>
      <TopBar activeNav="gm" leagueId={params.id} year={String(year)} lens="ktc" />
      <DashboardClient
        leagueId={params.id}
        initialYear={year}
        initialLens="ktc"
        initialTab="gm"
      />
    </Shell>
  );
}
