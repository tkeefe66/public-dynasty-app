/** Resolve the redirect target for the single-league landing page.
 *  Returns "/league/<id>" when LEAGUE_ID is configured, else null. */
export function leagueRedirectTarget(leagueId: string | undefined): string | null {
  const id = (leagueId ?? "").trim();
  return id ? `/league/${id}` : null;
}
