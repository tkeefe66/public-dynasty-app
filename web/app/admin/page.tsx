import Link from "next/link";
import { AdminWorkspace } from "@/components/admin/AdminWorkspace";
import { BackupStatus, LeagueReport, UserReport } from "@/components/admin/AdminReports";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { BudgetEditor } from "@/components/BudgetEditor";
import { LlmCostPanel } from "@/components/LlmCostPanel";
import { StateMessage } from "@/components/furniture/StateMessage";
import {
  ApiError,
  adminBackups,
  adminLeagues,
  adminOverview,
  adminUsers,
  adminActiveUsers,
  getMe,
  type AdminBackupStatus,
  type AdminLeague,
  type AdminOverview,
  type AdminUser,
  type AdminActiveUsers,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  let isAdmin = false;
  let overview: AdminOverview;
  let leagues: AdminLeague[];
  let users: AdminUser[];
  let activeUsers: AdminActiveUsers;
  let backups: AdminBackupStatus | null;
  try {
    isAdmin = (await getMe()).is_admin;
    if (!isAdmin) throw new ApiError(403, "App owners only");
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
    if (isAdmin && !denied) {
      const unavailable = <StateMessage tone="negative" kicker="Reporting unavailable" headline="This report is unavailable." body="Refresh to try again. AI writing controls remain available in their own tab." />;
      return <Shell><TopBar activeNav="admin" /><p role="alert" className="mt-8 text-prose text-neg-strong">Admin reports didn&apos;t load. We couldn&apos;t load usage, league, user, or budget reports. Refresh to try again.</p><AdminWorkspace counts={{ leagues: null, users: null }} backup={<BackupStatus backups={null} />} leagues={unavailable} users={unavailable} budget={unavailable} /></Shell>;
    }
    return (
      <Shell>
        <TopBar activeNav="admin" />
        <section className="mt-8 max-w-4xl">
          <StateMessage
            className="mt-8 max-w-lg"
            tone={denied ? "neutral" : "negative"}
            kicker={denied ? "App owners only" : "Reporting unavailable"}
            headline={
              denied
                ? "This area is for app owners."
                : "Admin reports didn't load."
            }
            body={
              denied
                ? "Your leagues and franchise pages are all on the home screen."
                : "We couldn't load usage, league, or user reports. Refresh to try again."
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

  return <Shell><TopBar activeNav="admin" /><AdminWorkspace
    counts={{ leagues: overview.leagues, users: overview.users }}
    backup={<BackupStatus backups={backups} />}
    leagues={<LeagueReport leagues={leagues} />}
    users={<UserReport users={users} activeUsers={activeUsers} memberships={overview.memberships} />}
    budget={<><BudgetEditor initial={overview.budget} title="App-wide monthly cap" /><LlmCostPanel /></>}
  /></Shell>;
}
