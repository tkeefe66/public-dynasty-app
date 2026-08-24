import { ogTradeDetail } from "@/lib/og-api";
import { tradeCard } from "@/lib/og-card-data";
import { ogImage, OG_SIZE } from "@/lib/og-route";

export const runtime = "nodejs";
export const alt = "Trade card";
export const size = OG_SIZE;
export const contentType = "image/png";

export default async function Image({ params }: { params: { id: string; tid: string } }) {
  return ogImage(async () => tradeCard(await ogTradeDetail(params.id, params.tid)));
}
