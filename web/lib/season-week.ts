// Dynasty in-season trading happens only Sep-Nov (deadline ~week 11).
// Mirror of the engine's IN_SEASON_MONTHS so labels match the story packet.
const IN_SEASON_MONTHS = new Set([9, 10, 11]);

/** Human label for when a trade happened. In-season trades read "Week N";
 *  offseason trades name the adjacent season so it's unambiguous which side of
 *  the season they fall on — spring/summer deals land *before* that year's
 *  season, December deals land *after* it. */
export function seasonWeekLabel(dateIso: string, week: number): string {
  const year = Number(dateIso.slice(0, 4)); // "YYYY-MM-DD"
  const month = Number(dateIso.slice(5, 7));
  if (IN_SEASON_MONTHS.has(month)) return `Week ${week}`;
  return month === 12 ? `After ${year} season` : `Before ${year} season`;
}
