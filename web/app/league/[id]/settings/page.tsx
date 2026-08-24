import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { OwnerNamesForm } from "@/components/OwnerNamesForm";
import { ManualRefresh } from "@/components/ManualRefresh";
import { LlmCostPanel } from "@/components/LlmCostPanel";
import { StateMessage } from "@/components/furniture/StateMessage";
import { getOwnerNames, getMe, myLeagues } from "@/lib/api";
import { OwnerNamesResp } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function SettingsPage({
  params,
}: {
  params: { id: string };
}) {
  let data: OwnerNamesResp | null = null;
  try {
    data = await getOwnerNames(params.id);
  } catch {
    data = null;
  }

  // Data + LLM Spend are operator tooling — admins only. Fail closed: any
  // failure to resolve the profile (no session, network) is treated as
  // non-admin so the sections never render. See spec
  // docs/superpowers/specs/2026-06-28-settings-admin-gating-design.md.
  let isAdmin = false;
  try {
    isAdmin = (await getMe()).is_admin;
  } catch {
    isAdmin = false;
  }

  // The kicker's league name and the refresh card's season/warmth come from the
  // membership list, which the league layout already fetches on every route
  // here — no new endpoint, and no dashboard call (that one 409s on a cold
  // cache, which is precisely the state this page exists to get you out of).
  // An admin viewing a league they are not in gets no row; the kicker then
  // degrades to the owner count alone rather than guessing at a name.
  let league: { name: string | null; season: number | null; warm: boolean } | null = null;
  try {
    const mine = await myLeagues();
    league = mine.find((l) => l.league_id === params.id) ?? null;
  } catch {
    league = null;
  }

  const owners = data?.owners ?? [];
  const ownerCount = owners.length;
  const countLabel = `${ownerCount} owner${ownerCount === 1 ? "" : "s"}`;
  const kicker = league?.name ? `${league.name} · ${countLabel}` : countLabel;

  return (
    <Shell>
      <TopBar leagueId={params.id} activeNav="settings" />
      {/* One column at every width. `max-w-lg` keeps the owner cards from
          stretching to a 1180px measure on a desktop while the phone gets the
          full width of the Shell's padding box. */}
      <section className="mt-2 max-w-lg">
        <h1 className="font-display text-lead font-extrabold tracking-[var(--track-lead)]">
          Settings
        </h1>
        <p className="mt-1.5 font-mono text-label uppercase tracking-[0.11em] text-dim">
          {kicker}
        </p>

        {/* Owner names FIRST: everyone in the league edits these. The two
            admin sections below are operator tooling one person needs, so they
            sit after the thing the page is for. */}
        <div className="mt-8">
          {data ? (
            <OwnerNamesForm leagueId={params.id} initial={data.owners} />
          ) : (
            <StateMessage
              kicker="League not built yet"
              headline="Owner display names appear here once this league has been read."
              body="League not loaded yet. Run a refresh first."
            />
          )}
        </div>

        {isAdmin && (
          <div className="mt-10">
            <ManualRefresh
              leagueId={params.id}
              teams={data ? ownerCount : null}
              season={league?.season ?? null}
              warm={league?.warm ?? null}
            />
          </div>
        )}

        {isAdmin && (
          <div className="mt-10">
            <LlmCostPanel />
          </div>
        )}
      </section>
    </Shell>
  );
}
