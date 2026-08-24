import Link from "next/link";
import { signOut } from "@/auth";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { Button } from "@/components/furniture/Button";
import { StateMessage } from "@/components/furniture/StateMessage";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { Name } from "@/components/furniture/Name";
import { adminOverview, myLeagues, type MyLeague } from "@/lib/api";

// Authenticated "My Leagues" home. Middleware guarantees a signed-in user.
export const dynamic = "force-dynamic";

export default async function HomePage() {
  let leagues: MyLeague[] = [];
  let loadError = false;
  try {
    leagues = await myLeagues();
  } catch {
    loadError = true;
  }

  // Show the Admin link only to app owners (admin endpoint 403s otherwise).
  let isAdmin = false;
  try {
    await adminOverview();
    isAdmin = true;
  } catch {
    isAdmin = false;
  }

  return (
    <Shell>
      <TopBar />
      <section className="mt-8 max-w-3xl">
        <div className="flex items-center justify-between">
          {/* No kicker. "Sleeper dynasty trade grader" sat above this heading
              restating the product one line under the wordmark that already
              names it — and naming it something the product is no longer
              called. `My Leagues` is the page. */}
          <h1 className="font-display text-lead font-extrabold tracking-[-0.03em]">My Leagues</h1>
          <Button as="link" href="/leagues/add" className="px-4 py-2">
            Add a league
          </Button>
        </div>

        {loadError && (
          <StateMessage
            className="mt-8"
            tone="negative"
            kicker="Leagues didn't load"
            headline="Your leagues are there — we couldn't reach them."
            body="Not you — us. The list comes back on a refresh once the backend answers."
          />
        )}

        {!loadError && leagues.length === 0 && (
          <StateMessage
            className="mt-8"
            kicker="No leagues yet"
            headline="Every trade in your league's history, graded."
            body="Add a Sleeper dynasty league and its full trade ledger, standings, and franchise ratings appear here."
            action={
              <Button as="link" href="/leagues/add" className="inline-block px-3 py-2">
                Add your first league
              </Button>
            }
          />
        )}

        {leagues.length > 0 && (
          /* A ledger: Panel is a solid ground, so every row draws its own
             `--rule` hairline — the Link carries one for the entry boundary,
             and the Row inside carries its own (StandingsTable's LedgerEntry
             pattern), so this stays one tap target. */
          <div className="mt-6">
            <Panel>
              <Row variant="head" cols="minmax(0,1fr) 84px">
                <div>League</div>
                <div className="text-right">Status</div>
              </Row>
              {leagues.map((lg) => (
                <Link
                  key={lg.league_id}
                  href={`/league/${lg.league_id}`}
                  className="block border-t border-rule hover:bg-surface-sunk"
                >
                  <Row cols="minmax(0,1fr) 84px">
                    <span className="min-w-0 truncate">
                      {/* The name alone. The season used to trail it, but a
                          dynasty league's chain spans every season it has
                          played and the picker inside it selects the year —
                          one year printed beside the name reads as "this
                          league is that season", which is the wrong claim. */}
                      <Name>
                        {lg.name ?? `League ${lg.league_id}`}
                      </Name>
                    </span>
                    <span className="text-right text-label uppercase tracking-[0.1em]">
                      {lg.warm ? "Ready" : "Warming"}
                    </span>
                  </Row>
                </Link>
              ))}
            </Panel>
          </div>
        )}

        {/* Secondary actions are mono uppercase text links — no border, no
            box, no second button fill (stamp has five slots and this is not
            one of them). */}
        <div className="mt-10 flex items-center gap-4 border-t border-rule pt-2 font-mono text-label uppercase tracking-[0.1em] text-dim">
          <Link href="/account" className="hover:text-ink">
            Account
          </Link>
          {isAdmin && (
            <Link href="/admin" className="hover:text-ink">
              Admin
            </Link>
          )}
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/login" });
            }}
          >
            <button type="submit" className="uppercase tracking-[0.1em] hover:text-ink">
              Sign out
            </button>
          </form>
        </div>
      </section>
    </Shell>
  );
}
