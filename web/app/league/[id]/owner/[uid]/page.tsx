import type { Metadata } from "next";
import Link from "next/link";
import { cache } from "react";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { OwnerDeepDive } from "@/components/OwnerDeepDive";
import { Button } from "@/components/furniture/Button";
import { ApiError, ownerDetail } from "@/lib/api";

export const dynamic = "force-dynamic";

// generateMetadata and the page body both need the same owner detail. The
// route is force-dynamic and lib/api's fetches use cache: "no-store" plus a
// freshly-minted per-request auth header, so Next's built-in fetch
// memoization can't dedupe them — wrap the call in React's request-scoped
// cache() so both call sites share one in-flight promise per request.
const getOwnerDetail = cache((leagueId: string, uid: string) =>
  ownerDetail(leagueId, uid),
);

export async function generateMetadata(
  { params }: { params: { id: string; uid: string } },
): Promise<Metadata> {
  try {
    const d = await getOwnerDetail(params.id, params.uid);
    const title = `${d.owner.owner_name} — ${Math.round(d.totals_by_lens.ktc).toLocaleString()} net value`;
    return { title, twitter: { card: "summary_large_image", title } };
  } catch {
    return { title: "Franchise · DyNASTY", twitter: { card: "summary_large_image" } };
  }
}

/* ---------------------------------------------------------------------------
 * Agate — Failure Is A Headline (design_handoff_agate/DESIGN.md § "Named
 * rules"; `Agate System.dc.html` §07 Fig. 7.3). A mono kicker naming the
 * condition, an Archivo headline in plain words, one line of body, one ink
 * button. No illustration, no centered card. The failure states are branched
 * by status — a bare catch used to render "Franchise not found." for 409s
 * and 500s alike, which lied about both.
 * ------------------------------------------------------------------------ */
function OwnerErrorState({
  leagueId, retryHref, err,
}: { leagueId: string; retryHref: string; err: unknown }) {
  const status = err instanceof ApiError ? err.status : null;
  const backLink = (
    <Link href={`/league/${leagueId}`} className="mt-4 inline-block font-mono text-label uppercase tracking-[0.11em] text-dim underline hover:text-ink">
      ← Back to league
    </Link>
  );
  if (status === 409) {
    // Cold cache: the league exists but hasn't been pulled + graded yet. The
    // dashboard owns the refresh flow, so point there instead of dead-ending.
    return (
      <Shell>
        <TopBar />
        <section className="mt-16 max-w-lg">
          <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">Not graded yet</div>
          <h1 className="mt-2 font-display text-lead font-extrabold leading-[1.05] tracking-[var(--track-lead)]">
            This league hasn&apos;t been graded yet.
          </h1>
          <p className="mt-2 text-prose leading-relaxed text-body">
            Franchise pages unlock once the league&apos;s history is pulled and
            graded — takes about a minute, and the dashboard runs it.
          </p>
          <Button as="link" href={`/league/${leagueId}`} className="mt-4 inline-block px-4 py-2">
            Open the league dashboard
          </Button>
        </section>
      </Shell>
    );
  }
  if (status === 404) {
    return (
      <Shell>
        <TopBar />
        <section className="mt-16">
          <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">Not found</div>
          <h1 className="mt-2 font-display text-lead font-extrabold leading-[1.05] tracking-[var(--track-lead)]">
            Franchise not found.
          </h1>
          {backLink}
        </section>
      </Shell>
    );
  }
  // Everything else — 401 token hiccup, 500, network failure — is on us.
  return (
    <Shell>
      <TopBar />
      <section className="mt-16 max-w-lg">
        <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">Couldn&apos;t load</div>
        <h1 className="mt-2 font-display text-lead font-extrabold leading-[1.05] tracking-[var(--track-lead)]">
          Something broke on our end.
        </h1>
        <p className="mt-2 text-prose leading-relaxed text-body">
          Not you — us. This franchise wouldn&apos;t load. Try again; if it keeps
          failing, the backend is having a moment.
        </p>
        {/* Plain anchor: re-navigating re-runs this force-dynamic server fetch
            without needing any client JS. */}
        <Button as="a" href={retryHref} className="mt-4 inline-block px-4 py-2">
          ↻ Try again
        </Button>
        <div>{backLink}</div>
      </section>
    </Shell>
  );
}

export default async function OwnerPage({
  params,
  searchParams,
}: {
  params: { id: string; uid: string };
  searchParams?: { tab?: string; year?: string };
}) {
  /* Must stay in step with `TABS` in `components/OwnerDeepDive.tsx`. "draft"
   * was missing here while the client rendered the tab regardless, so clicking
   * Draft worked and pushed `?tab=draft`, but OPENING that URL failed this
   * whitelist and silently landed on Overview — which is every shared link to
   * the tab, and the receipt action's own deep link. Found by screenshotting
   * the tab rather than by any test; nothing asserts these two lists agree. */
  const VALID_TABS = ["overview", "record", "trades", "draft", "outlook"] as const;
  const initialTab = (VALID_TABS as readonly string[]).includes(searchParams?.tab ?? "")
    ? (searchParams!.tab as (typeof VALID_TABS)[number])
    : "overview";
  // Trades-year deep link: parsed here, whitelist-validated against the owner's
  // actual trade seasons inside OwnerDeepDive (the data lives there).
  const yearNum = Number(searchParams?.year);
  const initialTradesYear = Number.isInteger(yearNum) ? yearNum : undefined;

  let data;
  try {
    data = await getOwnerDetail(params.id, params.uid);
  } catch (err) {
    const qs = new URLSearchParams();
    if (searchParams?.tab) qs.set("tab", searchParams.tab);
    if (searchParams?.year) qs.set("year", searchParams.year);
    const q = qs.toString();
    const retryHref = `/league/${params.id}/owner/${params.uid}${q ? `?${q}` : ""}`;
    return <OwnerErrorState leagueId={params.id} retryHref={retryHref} err={err} />;
  }
  return (
    <Shell>
      <TopBar activeNav="owners" leagueId={params.id} />
      <section className="mt-2">
        <Link
          href={`/league/${params.id}?tab=owners`}
          className="font-mono text-figure text-dim hover:text-ink"
        >
          ← All owners
        </Link>
        <div className="mt-5">
          {/* Read-only shared view: no rank/grade (no standings here) and no
              inline editor — editing lives in the Owners workspace. */}
          <OwnerDeepDive
            leagueId={params.id}
            detail={data}
            initialTab={initialTab}
            initialTradesYear={initialTradesYear}
            syncUrl
          />
        </div>
      </section>
    </Shell>
  );
}
