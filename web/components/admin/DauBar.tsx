import type { DailyPoint } from "@/lib/api";

const DAY_MS = 86_400_000;

function fmtDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** Zero-fill the sparse per-day series to a contiguous window ending today
 *  (UTC). The backend only emits days that had events, so without this the
 *  x-axis silently drops quiet days and 3 active days stretch to fill the
 *  whole 30-day width. */
function fillDays(daily: DailyPoint[], days: number): DailyPoint[] {
  const byDate = new Map(daily.map((d) => [d.date, d.count]));
  let endMs = Date.parse(`${new Date().toISOString().slice(0, 10)}T00:00:00Z`);
  // daily arrives sorted ascending; widen the window if data falls outside it
  // (older than 30d, or a "tomorrow" bucket from backend/web clock skew).
  const earliest = daily[0] ? Date.parse(`${daily[0].date}T00:00:00Z`) : NaN;
  const latest = daily.length
    ? Date.parse(`${daily[daily.length - 1].date}T00:00:00Z`)
    : NaN;
  if (!Number.isNaN(latest)) endMs = Math.max(endMs, latest);
  let startMs = endMs - (days - 1) * DAY_MS;
  if (!Number.isNaN(earliest)) startMs = Math.min(startMs, earliest);
  const out: DailyPoint[] = [];
  for (let t = startMs; t <= endMs; t += DAY_MS) {
    const date = new Date(t).toISOString().slice(0, 10);
    out.push({ date, count: byDate.get(date) ?? 0 });
  }
  return out;
}

/** Tiny CSS bar chart of a per-day count over the last ~30 days. Quiet days
 *  render as divider-colored stubs so the calendar reads honestly. */
export function DauBar({
  daily,
  label = "Daily active users",
}: {
  daily: DailyPoint[];
  label?: string;
}) {
  if (daily.length === 0) {
    return <p className="mt-2 text-prose text-dim">No activity recorded yet.</p>;
  }
  const series = fillDays(daily, 30);
  const max = Math.max(...series.map((d) => d.count), 1);
  return (
    <div className="mt-3">
      <div role="img" aria-label={label} className="flex h-24 items-end gap-[3px]">
        {series.map((d) => (
          /* Agate — a bar is ink, square, never colored (DESIGN.md § "Ink
             Bars"). A zero day stays a `--rule` stub so the calendar still
             reads honestly; the count lives in the tooltip and the peak
             figure. */
          <div
            key={d.date}
            title={`${fmtDay(d.date)} · ${d.count}`}
            className={`min-h-[2px] flex-1 ${d.count > 0 ? "bg-ink" : "bg-rule"}`}
            style={{ height: `${(d.count / max) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-1 flex items-baseline justify-between font-mono text-figure text-dim tabular">
        <span>{fmtDay(series[0].date)}</span>
        <span>peak {max}</span>
        <span>{fmtDay(series[series.length - 1].date)}</span>
      </div>
    </div>
  );
}
