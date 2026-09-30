import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { DashboardTabs } from "@/components/DashboardTabs";
import { ScoringLeaders } from "@/components/ScoringLeaders";
import { StateMessage } from "@/components/furniture/StateMessage";
import { Button } from "@/components/furniture/Button";
import { ApiError, scoringLeaders } from "@/lib/api";

export const dynamic = "force-dynamic";
export const metadata = { title: "Scoring leaders · Fantasy Analyzer" };

export default async function ScoringPage({ params }: { params: { id: string } }) {
  let data;
  let failure;
  try {
    data = await scoringLeaders(params.id);
  } catch (error) {
    failure = error instanceof ApiError ? error.message : "Could not load player scores. Reload the page to try again.";
  }
  return <Shell>
    <TopBar leagueId={params.id} activeNav="scoring" />
    <DashboardTabs leagueId={params.id} active="scoring" />
    {data ? <ScoringLeaders data={data} /> : <StateMessage kicker="Scoring unavailable"
      headline="We couldn’t load the scoring leaders." body={failure} tone="negative"
      action={<Button as="a" href={`/league/${params.id}/scoring`} className="px-4 py-2">Try again</Button>} />}
  </Shell>;
}
