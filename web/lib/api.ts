import {
  BetsSummaryResp, DashboardResp, DraftBoardResp, DraftSeasonsResp, LatestTrade, LeaderboardResp,
  Lens, OwnerDetailResp, OwnerNameEntry, OwnerNamesResp, OwnerProfile, ProfilesMap,
  SideBetCreateBody, SideBetListResp, SideBetUpdateBody, SideBetView, TradeDetailResp, Year,
} from "./types";

const BASE = typeof window === "undefined"
  ? `${process.env.API_URL || "http://localhost:8000"}/api`
  : "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Server-side auth-header provider. Client fetches go through the same-origin
// Route Handler proxy (which swaps the session cookie for a Bearer), so they
// need nothing here. RSC fetches call the backend (API_URL) directly and must
// attach a Bearer themselves — lib/auth-server.ts registers a provider for that
// via this hook. Kept as an injected function so this module stays free of any
// server-only import and is safe to bundle into client components.
type ServerAuthProvider = () => Promise<Record<string, string>>;
let _serverAuth: ServerAuthProvider | null = null;

export function registerServerAuth(provider: ServerAuthProvider): void {
  _serverAuth = provider;
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  // Default to no-store: this is live league data kept current by the backend's
  // periodic auto-refresh. Next.js 14 fetch() otherwise defaults to force-cache
  // (the Data Cache), which pins SSR responses to the first build and serves
  // stale dashboard/trade/owner data indefinitely. Callers may override via init.
  let headers: Record<string, string> = { ...(init?.headers as Record<string, string>) };
  if (typeof window === "undefined" && _serverAuth) {
    headers = { ...headers, ...(await _serverAuth()) };
  }
  const resp = await fetch(url, { cache: "no-store", ...init, headers });
  if (!resp.ok) {
    const detail = await resp
      .json().then((d) => d.detail).catch(() => resp.statusText);
    throw new ApiError(resp.status, String(detail));
  }
  return (await resp.json()) as T;
}

export function dashboard(
  leagueId: string,
  opts: { year?: Year; lens?: Lens } = {},
): Promise<DashboardResp> {
  const sp = new URLSearchParams();
  if (opts.year !== undefined) sp.set("year", String(opts.year));
  if (opts.lens) sp.set("lens", opts.lens);
  const qs = sp.toString();
  return jsonFetch<DashboardResp>(
    `${BASE}/league/${leagueId}${qs ? `?${qs}` : ""}`,
  );
}

export function tradesList(
  leagueId: string,
  opts: { year?: Year | string; lens?: Lens | string } = {},
): Promise<LatestTrade[]> {
  const sp = new URLSearchParams();
  if (opts.year !== undefined && String(opts.year) !== "all") {
    sp.set("year", String(opts.year));
  }
  if (opts.lens) sp.set("lens", String(opts.lens));
  const qs = sp.toString();
  return jsonFetch<LatestTrade[]>(
    `${BASE}/league/${leagueId}/trades${qs ? `?${qs}` : ""}`,
  );
}

export function leaderboard(
  leagueId: string,
  opts: { year?: Year | string } = {},
): Promise<LeaderboardResp> {
  const sp = new URLSearchParams();
  if (opts.year !== undefined && String(opts.year) !== "all") {
    sp.set("year", String(opts.year));
  }
  const qs = sp.toString();
  return jsonFetch<LeaderboardResp>(
    `${BASE}/league/${leagueId}/leaderboard${qs ? `?${qs}` : ""}`,
  );
}

export function ownerDetail(
  leagueId: string, userId: string,
): Promise<OwnerDetailResp> {
  return jsonFetch<OwnerDetailResp>(
    `${BASE}/league/${leagueId}/owner/${userId}`,
  );
}

export function tradeDetail(
  leagueId: string, tradeId: string,
): Promise<TradeDetailResp> {
  return jsonFetch<TradeDetailResp>(
    `${BASE}/league/${leagueId}/trade/${tradeId}`,
  );
}

/** One draft class, every owner. 409 on a cold cache; 404 (with the seasons
 *  that DO exist named in the detail) when this season has no draft class. */
export function draftBoard(
  leagueId: string, season: number,
): Promise<DraftBoardResp> {
  return jsonFetch<DraftBoardResp>(
    `${BASE}/league/${leagueId}/draft/${season}`,
  );
}

/** Every draft season on this chain, newest first. 409 on a cold cache, same
 *  contract as `draftBoard` — used by the `/draft` redirect route to pick a
 *  season before it can fetch a board. */
export function draftSeasons(leagueId: string): Promise<DraftSeasonsResp> {
  return jsonFetch<DraftSeasonsResp>(
    `${BASE}/league/${leagueId}/draft/seasons`,
  );
}

/** All owner profiles for the league ({} if none saved). Never 409s. */
export function getProfiles(leagueId: string): Promise<ProfilesMap> {
  return jsonFetch<ProfilesMap>(`${BASE}/league/${leagueId}/profiles`);
}

/** Upsert one owner's profile; resolves to the full updated league map. */
export function putProfile(
  leagueId: string, userId: string, profile: OwnerProfile,
): Promise<ProfilesMap> {
  return jsonFetch<ProfilesMap>(
    `${BASE}/league/${leagueId}/profiles/${userId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    },
  );
}

export function getOwnerNames(leagueId: string): Promise<OwnerNamesResp> {
  return jsonFetch<OwnerNamesResp>(`${BASE}/league/${leagueId}/owner-names`);
}

export function putOwnerNames(
  leagueId: string,
  overrides: Record<string, string>,
): Promise<{ ok: boolean }> {
  return jsonFetch<{ ok: boolean }>(`${BASE}/league/${leagueId}/owner-names`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overrides }),
  });
}

// ── Onboarding / memberships (/api/me/*) ──────────────────────────────────────

export interface MyLeague {
  league_id: string;
  name: string | null;
  season: number | null;
  warm: boolean;
  sleeper_roster_id: number | null;
  added_at: string;
}

export interface SleeperLeague {
  league_id: string;
  name: string;
  season: number;
  total_rosters: number;
  already_imported: boolean;
  format: "dynasty" | "keeper" | "redraft";
}

/** The current user's imported leagues. */
export function myLeagues(): Promise<MyLeague[]> {
  return jsonFetch<MyLeague[]>(`${BASE}/me/leagues`);
}

export interface MeProfile {
  email: string;
  name: string | null;
  avatar_url: string | null;
  sleeper_user_id: string | null;
  sleeper_username: string | null;
  is_admin: boolean;
}

/** The current user's profile (incl. soft Sleeper link). */
export function getMe(): Promise<MeProfile> {
  return jsonFetch<MeProfile>(`${BASE}/me`);
}

/** Link a Sleeper username to the account (personalization only). */
export function linkSleeper(username: string): Promise<MeProfile> {
  return jsonFetch<MeProfile>(`${BASE}/me/link-sleeper`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
}

/** Clear the Sleeper link. */
export function unlinkSleeper(): Promise<MeProfile> {
  return jsonFetch<MeProfile>(`${BASE}/me/link-sleeper`, { method: "DELETE" });
}

/** Discover a Sleeper user's leagues (dynasty, keeper, or redraft). Omit
 *  username to use the linked account. Defaults to current season. */
export function sleeperLeagues(
  username?: string,
  season?: number,
): Promise<SleeperLeague[]> {
  const sp = new URLSearchParams();
  if (username) sp.set("username", username);
  if (season) sp.set("season", String(season));
  const qs = sp.toString();
  return jsonFetch<SleeperLeague[]>(
    `${BASE}/me/sleeper-leagues${qs ? `?${qs}` : ""}`,
  );
}

/** Import a league for the current user (idempotent, cap-enforced). */
export function addLeague(
  leagueId: string,
  opts: { name?: string; sleeperRosterId?: number } = {},
): Promise<MyLeague> {
  return jsonFetch<MyLeague>(`${BASE}/me/leagues`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      league_id: leagueId,
      name: opts.name,
      sleeper_roster_id: opts.sleeperRosterId,
    }),
  });
}

/** Drop a membership (204, no body). */
export async function removeLeague(leagueId: string): Promise<void> {
  const headers: Record<string, string> = {};
  if (typeof window === "undefined" && _serverAuth) {
    Object.assign(headers, await _serverAuth());
  }
  const resp = await fetch(`${BASE}/me/leagues/${leagueId}`, {
    method: "DELETE",
    cache: "no-store",
    headers,
  });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
}

// ── App-owner admin (/api/admin/*) ────────────────────────────────────────────

export interface BudgetStatus {
  monthly_budget_usd: number;
  month_to_date_usd: number;
  budget_remaining_usd: number | null;
}

export interface AdminOverview {
  users: number;
  memberships: number;
  leagues: number;
  budget: BudgetStatus;
}

export interface AdminLeague {
  league_id: string;
  name: string | null;
  season: number | null;
  format: string | null;
  member_count: number;
  warm: boolean;
  spend_mtd_usd: number;
  active_users: number;
  last_activity: string | null;
}

export interface AdminUserLeague {
  league_id: string;
  name: string | null;
}

export interface AdminUser {
  id: string;
  email: string;
  name: string | null;
  is_admin: boolean;
  league_count: number;
  leagues: AdminUserLeague[];
  active_days: number;
  last_active_at: string | null;
  created_at: string;
}

export interface DailyPoint {
  date: string;
  count: number;
}

export interface AdminActiveUsers {
  daily: DailyPoint[];
  d1: number;
  d7: number;
  d30: number;
}

export interface AdminActivityEvent {
  path: string;
  route: string;
  league_id: string | null;
  league_name: string | null;
  created_at: string;
}

export interface AdminUserActivity {
  email: string;
  name: string | null;
  recent: AdminActivityEvent[];
  daily: DailyPoint[];
}

export function adminOverview(): Promise<AdminOverview> {
  return jsonFetch<AdminOverview>(`${BASE}/admin/overview`);
}

export function adminLeagues(): Promise<AdminLeague[]> {
  return jsonFetch<AdminLeague[]>(`${BASE}/admin/leagues`);
}

export function adminUsers(): Promise<AdminUser[]> {
  return jsonFetch<AdminUser[]>(`${BASE}/admin/users`);
}

export function adminActiveUsers(): Promise<AdminActiveUsers> {
  return jsonFetch<AdminActiveUsers>(`${BASE}/admin/telemetry/active-users`);
}

export function adminUserActivity(userId: string): Promise<AdminUserActivity> {
  return jsonFetch<AdminUserActivity>(`${BASE}/admin/users/${userId}/activity`);
}

export interface AdminBackupStatus {
  enabled: boolean;
  last_ok_at: string | null;
  last_error: string | null;
  last_run_id: string | null;
}

export function adminBackups(): Promise<AdminBackupStatus> {
  return jsonFetch<AdminBackupStatus>(`${BASE}/admin/backups`);
}

export function setBudget(monthlyBudgetUsd: number): Promise<BudgetStatus> {
  return jsonFetch<BudgetStatus>(`${BASE}/admin/budget`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ monthly_budget_usd: monthlyBudgetUsd }),
  });
}

export function refreshStream(
  leagueId: string,
  onEvent: (e: { stage: string; message?: string; done?: number; total?: number }) => void,
): EventSource {
  const es = new EventSource(
    `${BASE}/league/${leagueId}/refresh`,
    { withCredentials: false } as EventSourceInit,
  );
  es.addEventListener("progress", (ev) => {
    onEvent(JSON.parse((ev as MessageEvent).data));
  });
  es.addEventListener("done", (ev) => {
    onEvent(JSON.parse((ev as MessageEvent).data));
    es.close();
  });
  es.addEventListener("error", () => {
    onEvent({ stage: "error", message: "stream error" });
    es.close();
  });
  return es;
}

// ── Side bets ──────────────────────────────────────────────────────────────

export function listBets(
  leagueId: string,
  opts: { ownerId?: string; season?: number } = {},
): Promise<SideBetListResp> {
  const params = new URLSearchParams();
  if (opts.ownerId) params.set("owner_id", opts.ownerId);
  if (opts.season != null) params.set("season", String(opts.season));
  const qs = params.toString();
  return jsonFetch<SideBetListResp>(
    `${BASE}/league/${leagueId}/bets${qs ? `?${qs}` : ""}`,
  );
}

export function createBet(
  leagueId: string,
  body: SideBetCreateBody,
): Promise<SideBetView> {
  return jsonFetch<SideBetView>(`${BASE}/league/${leagueId}/bets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateBet(
  leagueId: string,
  betId: string,
  body: SideBetUpdateBody,
): Promise<SideBetView> {
  return jsonFetch<SideBetView>(`${BASE}/league/${leagueId}/bets/${betId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function betsSummary(
  leagueId: string,
  season?: number,
): Promise<BetsSummaryResp> {
  const qs = season != null ? `?season=${season}` : "";
  return jsonFetch<BetsSummaryResp>(
    `${BASE}/league/${leagueId}/bets/summary${qs}`,
  );
}
