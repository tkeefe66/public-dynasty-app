import type { Metadata } from "next";
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { DraftBoard } from "@/components/DraftBoard";
import { Button } from "@/components/furniture/Button";
import { StateMessage } from "@/components/furniture/StateMessage";
import { ApiError, draftBoard } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function generateMetadata(
  { params }: { params: { id: string; season: string } },
): Promise<Metadata> {
  try {
    const d = await draftBoard(params.id, Number(params.season));
    const title = `${d.season} Draft Board`;
    return { title, twitter: { card: "summary_large_image", title } };
  } catch {
    return { title: "Draft Board · DyNASTY", twitter: { card: "summary_large_image" } };
  }
}

/* ---------------------------------------------------------------------------
 * Agate — "Failure Is A Headline" (design_handoff_agate/DESIGN.md § "Named
 * rules"), reusing the shared `StateMessage` primitive rather than
 * hand-rolling the kicker/headline/body/action markup again. Branched by
 * status, same as the owner franchise page's error state:
 *  - 409 (cold cache): the league exists but hasn't been graded yet — point
 *    at the dashboard, which owns the refresh flow.
 *  - 404 (no draft class this season): names the seasons that DO exist —
 *    the endpoint's own `detail` message already states them plainly, so
 *    it's relayed as the body rather than re-derived here.
 *  - anything else (401 hiccup, 500, network): "Not you — us", with a plain
 *    retry link that re-runs this force-dynamic server fetch.
 * ------------------------------------------------------------------------ */
function DraftBoardErrorState({
  leagueId, season, err,
}: { leagueId: string; season: string; err: unknown }) {
  const status = err instanceof ApiError ? err.status : null;
  const backLink = (
    <Link
      href={`/league/${leagueId}`}
      className="mt-1 inline-block font-mono text-label uppercase tracking-[0.1em] text-dim underline hover:text-ink"
    >
      ← Back to league
    </Link>
  );

  if (status === 409) {
    return (
      <Shell>
        <TopBar leagueId={leagueId} />
        <StateMessage
          className="mt-16 max-w-lg"
          kicker="Not graded yet"
          headline="This league hasn't been graded yet."
          body="Draft boards unlock once the league's history is pulled and graded — takes about a minute, and the dashboard runs it."
          action={
            <Button as="link" href={`/league/${leagueId}`} className="inline-block px-4 py-2">
              Open the league dashboard
            </Button>
          }
        />
      </Shell>
    );
  }

  if (status === 404) {
    const detail = err instanceof ApiError && err.message
      ? err.message.charAt(0).toUpperCase() + err.message.slice(1)
      : `No draft class for ${season}.`;
    return (
      <Shell>
        <TopBar leagueId={leagueId} />
        <StateMessage
          className="mt-16 max-w-lg"
          kicker="No draft class"
          headline={`No draft board for ${season}.`}
          body={detail}
          action={backLink}
        />
      </Shell>
    );
  }

  return (
    <Shell>
      <TopBar leagueId={leagueId} />
      <StateMessage
        className="mt-16 max-w-lg"
        kicker="Couldn't load"
        headline="Something broke on our end."
        body="Not you — us. The draft board wouldn't load. Try again; if it keeps failing, the backend is having a moment."
        tone="negative"
        action={
          <div>
            {/* Plain anchor: re-navigating re-runs this force-dynamic server
                fetch without needing any client JS. */}
            <Button as="a" href={`/league/${leagueId}/draft/${season}`} className="inline-block px-4 py-2">
              ↻ Try again
            </Button>
            {backLink}
          </div>
        }
      />
    </Shell>
  );
}

export default async function DraftBoardPage({
  params,
}: {
  params: { id: string; season: string };
}) {
  let data;
  try {
    data = await draftBoard(params.id, Number(params.season));
  } catch (err) {
    return <DraftBoardErrorState leagueId={params.id} season={params.season} err={err} />;
  }

  return (
    <Shell>
      <TopBar leagueId={params.id} />
      <section className="mt-2">
        <Link
          href={`/league/${params.id}`}
          className="font-mono text-label text-dim hover:text-ink"
        >
          ← League dashboard
        </Link>
        <h1 className="mt-3 font-display text-lead font-extrabold tracking-[var(--track-lead)]">
          {data.season} Draft Board
        </h1>
        <div className="mt-5">
          <DraftBoard leagueId={params.id} board={data} />
        </div>
      </section>
    </Shell>
  );
}
