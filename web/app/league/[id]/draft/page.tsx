import { redirect } from "next/navigation";
import { draftSeasons } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * `/league/{id}/draft` breaks the chicken-and-egg: the nav needs somewhere to
 * point that isn't already a season, and the season board
 * (`draft/[season]/page.tsx`) needs a season before it can fetch anything.
 * This route resolves the newest season and redirects into it.
 *
 * On ANY failure — 409 cold cache, network error, or an empty season list —
 * this falls through to the current NFL season's board instead of building a
 * second error surface. That page already owns the cold-start and 404
 * experiences (`DraftBoardErrorState` names the seasons that DO exist and
 * links them), so redirecting into it is strictly better than duplicating
 * that UI here.
 */
function currentNflSeason(): number {
  const now = new Date();
  // A season is named for the year it starts (Sept). Jan/Feb still belongs
  // to the season that started the previous calendar year.
  return now.getUTCMonth() < 2 ? now.getUTCFullYear() - 1 : now.getUTCFullYear();
}

export default async function DraftRedirectPage({
  params,
}: {
  params: { id: string };
}) {
  let target = currentNflSeason();
  try {
    const { seasons } = await draftSeasons(params.id);
    if (seasons.length > 0) target = seasons[0];
  } catch {
    // Fall through to the current-season guess — the target page's own
    // error state names the seasons that DO exist.
  }

  // `redirect()` throws a Next control-flow error — it must never be inside
  // the try/catch above, or the catch would swallow it and the route hangs.
  redirect(`/league/${params.id}/draft/${target}`);
}
