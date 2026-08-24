/** Date display helpers. Dates travel over the API as YYYY-MM-DD (ISO 8601),
 *  which sorts and compares cleanly — keep that on the wire. Convert to a
 *  readable "Month D, YYYY" form only at render time, here. */

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** Render a YYYY-MM-DD (or full ISO) date string as "May 5, 2025" for display.
 *  Returns "" for null/empty and passes through anything unparseable. */
export function fmtDate(d: string | null | undefined): string {
  if (!d) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  if (!m) return d;
  const [, y, mo, day] = m;
  const month = MONTHS[Number(mo) - 1];
  if (!month) return d;
  return `${month} ${Number(day)}, ${y}`;
}

/** Render a YYYY-MM-DD (or full ISO) date string as "Sep 24, 2025" — the
 *  Agate trade-hero kicker (design_handoff_agate: date only, abbreviated
 *  month). Returns "" for null/empty and passes through anything unparseable. */
export function fmtDateShort(d: string | null | undefined): string {
  if (!d) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  if (!m) return d;
  const [, y, mo, day] = m;
  const month = MONTHS_SHORT[Number(mo) - 1];
  if (!month) return d;
  return `${month} ${Number(day)}, ${y}`;
}
