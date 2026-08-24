import { myLeagues } from "@/lib/api";

export const dynamic = "force-dynamic";

/* ---------------------------------------------------------------------------
 * Admin support access — the persistent indicator.
 *
 * The app owner can open leagues they do not belong to, to see how one is set
 * up and to reproduce reported bugs (api/app/auth/deps.py::require_league_member,
 * read-only). This layout exists so that access is never silent: without it,
 * someone else's league is visually indistinguishable from your own, and the
 * numbers on screen belong to strangers.
 *
 * It wraps every route under /league/[id] at once — dashboard, draft board,
 * owner, trade, gm, settings — which is why it is a layout rather than a
 * component each page has to remember to render.
 *
 * The condition is INFERRED: "this league is not in your list" rather than a
 * server-provided flag. That is sound because a non-member non-admin never
 * reaches these pages — the API refuses them first. If the leagues call fails
 * we show the banner, which is the safe direction to fail: over-warning beats
 * quietly presenting a stranger's data as your own.
 * ------------------------------------------------------------------------ */

export default async function LeagueLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { id: string };
}) {
  let isMember = true;
  try {
    const mine = await myLeagues();
    isMember = mine.some((l) => l.league_id === params.id);
  } catch {
    isMember = false;
  }

  return (
    <>
      {!isMember && <AdminAccessBanner />}
      {children}
    </>
  );
}

/* A mono kicker on a hairline — the same grammar StateMessage opens with, at
 * notice weight rather than lead weight. A full StateMessage headline above
 * every league screen would outrank the screen itself. */
function AdminAccessBanner() {
  return (
    <div className="border-b border-rule pb-1.5 pt-3">
      <span className="font-mono text-label uppercase tracking-[0.16em] text-warn-strong">
        Admin access
      </span>
      <span className="ml-2 text-figure text-body">
        Not your league. Read-only — edits are refused.
      </span>
    </div>
  );
}
