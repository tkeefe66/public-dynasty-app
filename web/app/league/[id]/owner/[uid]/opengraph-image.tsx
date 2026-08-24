import { ogOwnerDetail, ogDashboard } from "@/lib/og-api";
import { ownerCard } from "@/lib/og-card-data";
import { ogImage, OG_SIZE } from "@/lib/og-route";

export const runtime = "nodejs";
export const alt = "Franchise card";
export const size = OG_SIZE;
export const contentType = "image/png";

export default async function Image({ params }: { params: { id: string; uid: string } }) {
  return ogImage(async () => {
    // Same as the leaderboard card: the dashboard is only here for the league
    // name, so its failure must not cost a real owner card.
    const [owner, dash] = await Promise.all([
      ogOwnerDetail(params.id, params.uid),
      ogDashboard(params.id).catch(() => null),
    ]);
    return ownerCard(owner, dash?.league.name ?? "DyNASTY");
  });
}
