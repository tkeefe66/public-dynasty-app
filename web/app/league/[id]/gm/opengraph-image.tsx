import { ogDashboard, ogLeaderboard } from "@/lib/og-api";
import { leaderboardCard } from "@/lib/og-card-data";
import { ogImage, OG_SIZE } from "@/lib/og-route";

export const runtime = "nodejs";
export const alt = "Franchise Ratings card";
export const size = OG_SIZE;
export const contentType = "image/png";

export default async function Image({ params }: { params: { id: string } }) {
  return ogImage(async () => {
    // The dashboard call is the NAME lookup only, and it carries its own catch:
    // a warm leaderboard with a cold dashboard should still render a real card
    // with the league id standing in, not fall through to the fallback.
    const [board, dash] = await Promise.all([
      ogLeaderboard(params.id),
      ogDashboard(params.id).catch(() => null),
    ]);
    return leaderboardCard(board, dash?.league.name ?? board.league_id);
  });
}
