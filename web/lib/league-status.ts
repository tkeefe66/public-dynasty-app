import type { MyLeague } from "./api";

/** Availability alone must never claim that a refresh is running. */
export function leagueStatus(league: Pick<MyLeague, "warm" | "refresh_job">): string {
  switch (league.refresh_job?.state) {
    case "queued": return league.warm ? "Update queued" : "Queued";
    case "running": return league.warm ? "Updating" : "Building";
    case "held": return "Paused";
    case "needs_attention":
    case "failed": return "Needs attention";
    case "cancelled":
    case "superseded": return league.warm ? "Ready" : "Stopped";
    case "succeeded": return league.warm ? "Ready" : "Needs refresh";
    default: return league.refresh_job ? "Check status" : league.warm ? "Ready" : "Not built";
  }
}

export function refreshErrorMessage(reason?: string, state?: string): string {
  if (reason === "yahoo_rate_limited") {
    return "Yahoo is limiting API access right now. Please wait before retrying. Your league is saved, and completed seasons will be reused.";
  }
  if (state === "held") {
    return "This refresh is paused. Your league is saved; the administrator can resume it.";
  }
  if (state === "cancelled" || state === "superseded") {
    return "This refresh was stopped. Your league is saved; you can start a new refresh.";
  }
  return "The refresh needs attention. Your saved data is retained; the administrator can inspect its job.";
}
