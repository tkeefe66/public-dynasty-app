import "server-only";
import { ApiError } from "./api";
import { getOgCardToken } from "./og-token";
import {
  DashboardResp, LeaderboardResp, OwnerDetailResp, TradeDetailResp,
} from "./types";

/**
 * The only consumer of `getOgCardToken()`. Read the header comment there first.
 *
 * This is a deliberately separate, tiny client rather than an option on
 * `lib/api.ts`: `lib/api.ts` is shared by the browser bundle, the RSC pages and
 * the proxy, and every one of those must keep using the session-derived token.
 * Nothing here is reachable from them — no exported helper takes a method, a
 * body, or an arbitrary path, so this module can only ever issue the four
 * card GETs the backend allowlists.
 */

const BASE = `${process.env.API_URL || "http://localhost:8000"}/api`;

/** GET one backend path with an og-card token. No method, body or header
 *  parameter by design — this is the whole verb surface of this module. */
async function ogGet<T>(path: string): Promise<T> {
  const token = await getOgCardToken();
  const resp = await fetch(`${BASE}${path}`, {
    // Card data is live league data; never serve a build-time snapshot.
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) {
    const detail = await resp
      .json().then((d) => d.detail).catch(() => resp.statusText);
    throw new ApiError(resp.status, String(detail));
  }
  return (await resp.json()) as T;
}

const seg = (s: string) => encodeURIComponent(s);

export function ogDashboard(leagueId: string): Promise<DashboardResp> {
  return ogGet<DashboardResp>(`/league/${seg(leagueId)}`);
}

export function ogLeaderboard(leagueId: string): Promise<LeaderboardResp> {
  return ogGet<LeaderboardResp>(`/league/${seg(leagueId)}/leaderboard`);
}

export function ogOwnerDetail(
  leagueId: string, userId: string,
): Promise<OwnerDetailResp> {
  return ogGet<OwnerDetailResp>(
    `/league/${seg(leagueId)}/owner/${seg(userId)}`,
  );
}

export function ogTradeDetail(
  leagueId: string, tradeId: string,
): Promise<TradeDetailResp> {
  return ogGet<TradeDetailResp>(
    `/league/${seg(leagueId)}/trade/${seg(tradeId)}`,
  );
}
