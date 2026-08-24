import type { Metadata } from "next";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { DashboardClient, DashboardTab } from "@/components/DashboardClient";
import { dashboard } from "@/lib/api";
import { Lens, Year } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function generateMetadata(
  { params }: { params: { id: string } },
): Promise<Metadata> {
  try {
    const d = await dashboard(params.id);
    const title = `${d.league.name} · ${d.league.season}`;
    return {
      title,
      description: `${d.league.total_rosters} managers, ${d.standings.reduce((n, r) => n + r.trades, 0)} trades graded`,
      twitter: { card: "summary_large_image", title },
    };
  } catch {
    return { title: "DyNASTY trade grader", twitter: { card: "summary_large_image" } };
  }
}

const TABS: DashboardTab[] = ["dashboard", "trades", "owners", "gm", "bets"];

export default function LeaguePage({
  params, searchParams,
}: {
  params: { id: string };
  searchParams: { year?: string; lens?: string; tab?: string };
}) {
  const year: Year =
    !searchParams.year || searchParams.year === "all"
      ? "all"
      : Number(searchParams.year);
  const lens: Lens =
    (searchParams.lens as Lens) &&
    ["ktc", "production"].includes(searchParams.lens!)
      ? (searchParams.lens as Lens)
      : "ktc";
  const tab: DashboardTab = TABS.includes(searchParams.tab as DashboardTab)
    ? (searchParams.tab as DashboardTab)
    : "dashboard";

  return (
    <Shell>
      <TopBar activeNav={tab} leagueId={params.id} year={String(year)} lens={lens} />
      <DashboardClient
        leagueId={params.id}
        initialYear={year}
        initialLens={lens}
        initialTab={tab}
      />
    </Shell>
  );
}
