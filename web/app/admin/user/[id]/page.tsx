import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { DauBar } from "@/components/admin/DauBar";
import { StateMessage } from "@/components/furniture/StateMessage";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { ApiError, adminUserActivity, type AdminUserActivity } from "@/lib/api";

export const dynamic = "force-dynamic";

// A `grid-template-columns` value, passed verbatim to `Row`'s `cols` prop —
// not a Tailwind `grid-cols-[...]` class (Row supplies `grid` itself).
const PAGE_COLS = "130px minmax(0,1.3fr) minmax(0,1fr)";

function when(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export default async function AdminUserPage({ params }: { params: { id: string } }) {
  let activity: AdminUserActivity;
  try {
    activity = await adminUserActivity(params.id);
  } catch (err) {
    // 401/403 = not an app owner; anything else is a backend hiccup and
    // shouldn't masquerade as an authorization problem.
    const denied =
      err instanceof ApiError && (err.status === 401 || err.status === 403);
    return (
      <Shell>
        <TopBar />
        <section className="mt-16 max-w-lg">
          <StateMessage
            tone={denied ? "neutral" : "negative"}
            kicker={denied ? "App owners only" : "Activity didn't load"}
            headline={
              denied
                ? "This area is for app owners."
                : "This user's activity is recorded — we couldn't read it back."
            }
            body={denied ? undefined : "Not you — us. Refresh once the backend answers."}
          />
          <Link
            href="/admin"
            className="mt-4 inline-block font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink"
          >
            ← Back to Admin
          </Link>
        </section>
      </Shell>
    );
  }

  return (
    <Shell>
      <TopBar />
      <section className="mt-8 max-w-3xl">
        <Link href="/admin" className="font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink">
          ← Admin
        </Link>
        <h1 className="mt-2 font-display text-lead font-extrabold tracking-[-0.03em]">
          {activity.email}
          {activity.name && (
            <span className="ml-2 font-mono text-prose font-normal tracking-normal text-dim">
              {activity.name}
            </span>
          )}
        </h1>

        {/* Per-user daily is a pageview count (events per UTC day), not the
            0/1 active-day flag — label it as what it is. */}
        <h2 className="mt-8 border-b border-rule pb-1.5 font-display text-section font-bold tracking-[-0.024em]">Pageviews per day (30d)</h2>
        <DauBar daily={activity.daily} label="Pageviews per day" />

        <h2 className="mt-10 border-b border-rule pb-1.5 font-display text-section font-bold tracking-[-0.024em]">Recent pages</h2>
        {activity.recent.length === 0 ? (
          <p className="mt-2 font-mono text-label uppercase tracking-[0.1em] text-dim">
            No pageviews recorded yet
          </p>
        ) : (
          <div className="mt-3">
            <Panel>
              <Row cols={PAGE_COLS} variant="head">
                <div>When</div>
                <div>Page</div>
                <div>League</div>
              </Row>
              {activity.recent.map((e, i) => (
                <Row key={i} cols={PAGE_COLS}>
                  <div className="whitespace-nowrap text-dim tabular">{when(e.created_at)}</div>
                  <div className="min-w-0 truncate" title={e.route}>{e.route}</div>
                  <div className="min-w-0 truncate">
                    {e.league_id ? (
                      <Link href={`/league/${e.league_id}`} className="hover:underline">
                        {e.league_name ?? e.league_id}
                      </Link>
                    ) : (
                      <span className="text-dim">—</span>
                    )}
                  </div>
                </Row>
              ))}
            </Panel>
          </div>
        )}
      </section>
    </Shell>
  );
}
