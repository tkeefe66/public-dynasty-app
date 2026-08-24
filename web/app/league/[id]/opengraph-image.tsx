import { ogDashboard } from "@/lib/og-api";
import { leagueCard } from "@/lib/og-card-data";
import { ogImage, OG_SIZE } from "@/lib/og-route";

export const runtime = "nodejs";
export const alt = "League card";
export const size = OG_SIZE;
export const contentType = "image/png";

export default async function Image({ params }: { params: { id: string } }) {
  return ogImage(async () => leagueCard(await ogDashboard(params.id)));
}
