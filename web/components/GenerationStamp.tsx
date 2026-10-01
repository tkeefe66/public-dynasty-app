export type GenerationPeriod = { season?: number | null; week?: number | null };

export function GenerationStamp({ at, period }: { at?: string | null; period?: GenerationPeriod | null }) {
  const date = at ? new Date(at) : null;
  const written = date && !Number.isNaN(date.valueOf())
    ? `Written ${date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })}`
    : "Writing date unavailable";
  return <p className="mt-2 text-label text-dim">
    Saved writing · {written}
    {period?.season ? ` · Based on ${period.season} season${period.week ? `, through week ${period.week}` : ""}` : ""}
  </p>;
}
