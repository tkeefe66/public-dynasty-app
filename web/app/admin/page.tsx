import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { BudgetEditor } from "@/components/BudgetEditor";
import { LlmCostPanel } from "@/components/LlmCostPanel";
import { DauBar } from "@/components/admin/DauBar";
import { StateMessage } from "@/components/furniture/StateMessage";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import {
  ApiError,
  adminBackups,
  adminLeagues,
  adminOverview,
  adminUsers,
  adminActiveUsers,
  type AdminBackupStatus,
  type AdminLeague,
  type AdminOverview,
  type AdminUser,
  type AdminActiveUsers,
} from "@/lib/api";

export const dynamic = "force-dynamic";

function usd(n: number) {
  return n < 0.01 ? `$${n.toFixed(5)}` : `$${n.toFixed(2)}`;
}

function lastSeen(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function leagueType(format: string | null) {
  if (!format) return "—";
  return format.charAt(0).toUpperCase() + format.slice(1);
}

function leagueLink(lg: { league_id: string; name: string | null }) {
  return (
    <Link
      href={`/league/${lg.league_id}`}
      className="text-ink hover:underline"
    >
      {lg.name ?? `League ${lg.league_id}`}
    </Link>
  );
}

// `grid-template-columns` values, passed verbatim to `Row`'s `cols` prop —
// not Tailwind `grid-cols-[...]` classes (Row supplies `grid` itself).
const LEAGUE_COLS = "minmax(0,1fr) 68px 66px 54px 54px 86px 78px";
const USER_COLS = "minmax(0,1.4fr) minmax(0,1fr) 50px 86px 52px";

/** One labelled figure inside a wrapped phone entry. */
function AdminCell({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="flex min-w-0 items-baseline gap-1.5">
      <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-label uppercase tracking-[0.1em] text-dim">
        {label}
      </span>
      <span className="flex-none whitespace-nowrap">{value}</span>
    </span>
  );
}

/** Shared labelled-figure strip (overview + usage). Three bare columns of
 *  whisper label over a mono figure — no tiles, no boxes. */
function StatGrid({
  stats,
  className = "",
}: {
  stats: { label: string; value: number }[];
  className?: string;
}) {
  return (
    <div className={`grid grid-cols-3 gap-5 ${className}`}>
      {stats.map((s) => (
        <div key={s.label}>
          <div className="font-mono text-label uppercase tracking-[0.1em] text-dim">{s.label}</div>
          <div className="font-mono text-lead font-semibold tabular tracking-[-0.02em]">
            {s.value}
          </div>
        </div>
      ))}
    </div>
  );
}

export default async function AdminPage() {
  let overview: AdminOverview;
  let leagues: AdminLeague[];
  let users: AdminUser[];
  let activeUsers: AdminActiveUsers;
  let backups: AdminBackupStatus | null;
  try {
    [overview, leagues, users, activeUsers, backups] = await Promise.all([
      adminOverview(),
      adminLeagues(),
      adminUsers(),
      adminActiveUsers(),
      // Newest endpoint of the five: if web ships ahead of api in a deploy, a
      // 404 here would otherwise render the whole page as an auth error.
      adminBackups().catch(() => null),
    ]);
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
            kicker={denied ? "App owners only" : "Admin data didn't load"}
            headline={
              denied
                ? "This area is for app owners."
                : "The numbers are there — we couldn't reach them."
            }
            body={
              denied
                ? "Your leagues and franchise pages are all on the home screen."
                : "Not you — us. Refresh once the backend answers."
            }
          />
          <Link
            href="/"
            className="mt-4 inline-block font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink"
          >
            ← Back to My Leagues
          </Link>
        </section>
      </Shell>
    );
  }

  const stats = [
    { label: "Users", value: overview.users },
    { label: "Leagues", value: overview.leagues },
    { label: "Memberships", value: overview.memberships },
  ];
  const usage = [
    { label: "Active today", value: activeUsers.d1 },
    { label: "Active 7d", value: activeUsers.d7 },
    { label: "Active 30d", value: activeUsers.d30 },
  ];

  return (
    <Shell>
      <TopBar />
      <section className="mt-8 max-w-4xl">
        <p className="font-mono text-label uppercase tracking-widest text-dim">
          App owner
        </p>
        <h1 className="mt-2 font-display text-lead font-extrabold tracking-[-0.03em]">Admin</h1>

        {/* Stat cards */}
        <StatGrid stats={stats} className="mt-6" />

        {/* Usage */}
        <h2 className="mt-10 border-b border-rule pb-1.5 font-display text-section font-bold tracking-[-0.024em]">Usage</h2>
        <StatGrid stats={usage} className="mt-3" />
        <DauBar daily={activeUsers.daily} />

        {/* Backups — last outcome the daily job stamped. A stale "Last OK"
            or a present error is the signal that backups broke silently. */}
        <div className="mt-4">
          <Panel>
            <Row cols="repeat(3, minmax(0,1fr))">
              <AdminCell
                label="Backups"
                value={backups ? (backups.enabled ? "on" : "off") : "unavailable"}
              />
              <AdminCell
                label="Last ok"
                value={backups ? lastSeen(backups.last_ok_at) : "—"}
              />
              <AdminCell label="Run" value={backups?.last_run_id ?? "—"} />
            </Row>
            {backups?.last_error ? (
              <Row cols="minmax(0,1fr)">
                <span
                  className="min-w-0 truncate text-neg-strong"
                  title={backups.last_error}
                >
                  {backups.last_error}
                </span>
              </Row>
            ) : null}
          </Panel>
        </div>

        {/* Leagues */}
        <h2 className="mt-10 border-b border-rule pb-1.5 font-display text-section font-bold tracking-[-0.024em]">Leagues</h2>
        {leagues.length === 0 ? (
          <p className="mt-2 font-mono text-label uppercase tracking-[0.1em] text-dim">
            No leagues imported yet
          </p>
        ) : (
          <div className="mt-3">
            {/* Desktop — six columns on one rule. */}
            <div className="hidden min-[701px]:block">
              <Panel>
                <Row cols={LEAGUE_COLS} variant="head">
                  <div>League</div>
                  <div className="text-right">Type</div>
                  <div className="text-right">Members</div>
                  <div className="text-right">Cache</div>
                  <div className="text-right">Active</div>
                  <div className="text-right">Last seen</div>
                  <div className="text-right">Spend (mo)</div>
                </Row>
                {leagues.map((lg) => (
                  <Row key={lg.league_id} cols={LEAGUE_COLS}>
                    <div className="min-w-0 truncate">
                      <Link href={`/league/${lg.league_id}`} className="hover:underline">
                        {lg.name ?? `League ${lg.league_id}`}
                      </Link>
                      {lg.season ? <span className="text-dim"> · {lg.season}</span> : null}
                    </div>
                    <div className="text-right text-label uppercase tracking-[0.1em] text-dim">
                      {leagueType(lg.format)}
                    </div>
                    <div className="text-right">{lg.member_count}</div>
                    <div className="text-right text-label uppercase tracking-[0.1em] text-dim">
                      {lg.warm ? "warm" : "cold"}
                    </div>
                    <div className="text-right">{lg.active_users}</div>
                    <div className="whitespace-nowrap text-right text-dim">{lastSeen(lg.last_activity)}</div>
                    <div className="text-right">{usd(lg.spend_mtd_usd)}</div>
                  </Row>
                ))}
              </Panel>
            </div>
            {/* Phone — each league is its own ledger card. Every column stays. */}
            <div className="min-[701px]:hidden space-y-2.5">
              {leagues.map((lg) => (
                <Panel key={lg.league_id}>
                  <Row cols="minmax(0,1fr) auto">
                    <Link href={`/league/${lg.league_id}`} className="min-w-0 truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink hover:underline">
                      {lg.name ?? `League ${lg.league_id}`}
                    </Link>
                    <span className="text-label uppercase tracking-[0.1em] text-dim">
                      {lg.warm ? "warm" : "cold"}
                    </span>
                  </Row>
                  <Row cols="repeat(2, minmax(0,1fr))">
                    <AdminCell label="Type" value={leagueType(lg.format)} />
                    <AdminCell label="Members" value={lg.member_count} />
                  </Row>
                  <Row cols="repeat(2, minmax(0,1fr))">
                    <AdminCell label="Active" value={lg.active_users} />
                    <AdminCell label="Last seen" value={lastSeen(lg.last_activity)} />
                  </Row>
                  <Row cols="minmax(0,1fr)">
                    <AdminCell label="Spend" value={usd(lg.spend_mtd_usd)} />
                  </Row>
                </Panel>
              ))}
            </div>
          </div>
        )}

        {/* Users */}
        <h2 className="mt-10 border-b border-rule pb-1.5 font-display text-section font-bold tracking-[-0.024em]">Users</h2>
        {/* One entry per user on the ledger; a user in several leagues gets
            one extra row per additional league. */}
        <div className="mt-3">
          <Panel>
            <Row cols={USER_COLS} variant="head">
              <div>Email</div>
              <div>League</div>
              <div className="text-right">Days</div>
              <div className="text-right">Last seen</div>
              <div className="text-right">Admin</div>
            </Row>
            {users.map((u) => {
              const first = u.leagues[0];
              const extra = u.leagues.slice(1);
              return (
                <div key={u.id}>
                  <Row cols={USER_COLS}>
                    <div className="min-w-0 truncate">
                      <Link href={`/admin/user/${u.id}`} className="hover:underline">
                        {u.email}
                      </Link>
                      {u.name ? <span className="text-dim"> · {u.name}</span> : null}
                    </div>
                    <div className="min-w-0 truncate">
                      {first ? leagueLink(first) : <span className="text-dim">—</span>}
                    </div>
                    <div className="text-right">{u.active_days}</div>
                    <div className="whitespace-nowrap text-right text-dim">{lastSeen(u.last_active_at)}</div>
                    <div className="text-right text-dim">
                      {u.is_admin ? <span title="App owner">✓</span> : ""}
                    </div>
                  </Row>
                  {extra.map((lg) => (
                    <Row key={lg.league_id} cols={USER_COLS}>
                      <div />
                      <div className="min-w-0 truncate text-dim">{leagueLink(lg)}</div>
                      <div />
                      <div />
                      <div />
                    </Row>
                  ))}
                </div>
              );
            })}
          </Panel>
        </div>

        {/* Cost: budget control + spend breakdown. Both cards self-title with
            the app's mono-uppercase kicker, so no extra h2 (which duplicated
            LlmCostPanel's own "LLM Spend" header). */}
        <div className="mt-10 space-y-6">
          <BudgetEditor initial={overview.budget} />
          <LlmCostPanel />
        </div>
      </section>
    </Shell>
  );
}
