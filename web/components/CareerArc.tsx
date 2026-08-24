import { SeasonArc } from "@/lib/types";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";

interface Props { arc: SeasonArc[] }

type LensKey =
  | "net_ktc" | "production_total" | "production_started"
  | "production_regular" | "production_playoff"
  | "production_toilet";

/**
 * Six metrics, in the app's fixed order, narrowing as it goes: the market
 * swing, everything the hauls scored, the part actually deployed, then that
 * part split by phase.
 *
 * `emptyNote` is what the chart says instead of drawing when a metric is zero
 * in EVERY season — see `MiniChart`. Toilet Bowl gets its own wording because
 * for a good franchise the absence is the compliment, not a gap in the data.
 */
const LENSES: {
  key: LensKey; label: string; signed: boolean; digits: number; emptyNote: string;
  /** Does this metric depend on games being PLAYED?
   *
   *  Trade Value does not: it is market value, real the moment the trade
   *  lands, and a franchise that traded in the current season has a genuine
   *  figure for it before a single snap. Everything else is points, which need
   *  a game. Only the production metrics get the unplayed-season treatment —
   *  hatching Trade Value hid a real 17,163 behind a "not played yet" mark. */
  production: boolean;
}[] = [
  { key: "net_ktc", label: "Trade Value", signed: true, digits: 0, production: false, emptyNote: "No value moved" },
  { key: "production_total", label: "Total Points", signed: true, digits: 1, production: true, emptyNote: "Nothing scored yet" },
  { key: "production_started", label: "Started Points", signed: true, digits: 1, production: true, emptyNote: "Nothing started yet" },
  { key: "production_regular", label: "Regular Season Points", signed: true, digits: 1, production: true, emptyNote: "Nothing scored yet" },
  { key: "production_playoff", label: "Playoff Points", signed: true, digits: 1, production: true, emptyNote: "Never made the bracket" },
  { key: "production_toilet", label: "Toilet Bowl Points", signed: true, digits: 1, production: true, emptyNote: "Never reached it" },
];

/** `production_started` is optional on the wire — a response served before the
 *  field existed omits it. Absent reads as 0 for charting, and the all-zero
 *  empty state below then states that plainly rather than drawing stubs. */
function valueOf(s: SeasonArc, key: LensKey): number {
  return (key === "production_started" ? s.production_started : s[key]) ?? 0;
}

function fmt(n: number, signed: boolean, digits: number): string {
  const v = digits ? n.toFixed(digits) : Math.round(n).toLocaleString();
  return signed && n > 0 ? `+${v}` : v;
}

/**
 * Is this the newest season, with nothing scored yet?
 *
 * NOT the same as "scored zero". The current season is 0.0 on every production
 * metric until games are played, so the most recent bar — the one the eye goes
 * to first — was a 2px stub through every offseason and preseason, on four of
 * the (now five) production charts. The app's rule everywhere else is *null is
 * not 0*: an unplayed thing renders as absent, never as a zero. This chart had
 * no way to say that.
 *
 * Keyed on being the LAST season in the arc, because that is the only one that
 * can be in progress. An older season that genuinely scored nothing keeps its
 * stub, which is the correct reading: it played and produced nothing.
 *
 * It does not need to know today's date. A season with trades on the books and
 * no points anywhere has not been played, and only the newest one can be in
 * that state.
 */
function unplayedSeasons(arc: SeasonArc[]): Set<number> {
  const last = arc[arc.length - 1];
  if (!last) return new Set();
  const scored = ["production_total", "production_started", "production_regular",
    "production_playoff", "production_toilet"] as const;
  const anyPoints = scored.some((k) => Math.abs(valueOf(last, k)) > 0);
  return anyPoints ? new Set() : new Set([last.season]);
}

/* ---------------------------------------------------------------------------
 * Ported from Agate — was "Ink Bars (DESIGN.md § Ink Bars), the vertical case",
 * every bar `--ink` because under Agate a coloured pixel could only ever mean a
 * signed figure. Furniture replaced `InkBar` with `Bar` to lift exactly that,
 * so the bars carry `--pos-bar`/`--neg-bar` — the weight-matched pair, never the
 * `--pos`/`--neg` figure pair, so neither hue reads as "more" at equal length.
 *
 * Sign still rides POSITION as well as hue: a zero axis with columns above and
 * below it. Colour is never the only carrier (`.design/SKILL.md` rule 3), and
 * on the phone rows below — which have no axis — that is the reason the figure
 * travels with every row.
 *
 * Each lens is normalised to its own max magnitude so six different units stay
 * independently readable.
 * ------------------------------------------------------------------------ */

const CHART_H = 72; // px; explicit so bar heights don't collapse against an auto parent
const HALF = CHART_H / 2;

/** A season that has not been played: hatched, not a stub. Reads as "no data
 *  here" rather than "this measured zero", which is the distinction the whole
 *  `unplayedSeasons` idea exists to draw. */
const HATCH = {
  backgroundImage:
    "repeating-linear-gradient(45deg, var(--rule-strong) 0 2px, transparent 2px 5px)",
};

function MiniChart(
  { arc, lens, unplayed }: {
    arc: SeasonArc[]; lens: typeof LENSES[number]; unplayed: Set<number>;
  },
) {
  const values = arc.map((s) => valueOf(s, lens.key));
  const allZero = values.every((v) => v === 0);
  const max = Math.max(...values.map(Math.abs), 1);
  const summary = arc
    .map((s) => `${s.season}: ${fmt(valueOf(s, lens.key), lens.signed, lens.digits)}`)
    .join(", ");

  return (
    <div>
      <div className="mb-2 font-mono text-label uppercase tracking-widest text-dim">
        {lens.label}
      </div>

      {/* AN ALL-ZERO METRIC STATES ITSELF. Toilet Bowl is 0.0 in every season
          for any franchise that never reached the consolation bracket — normal,
          and a good sign. Drawing it as four 2px stubs on an axis read as a
          chart that had failed to load. Hiding it would be wrong too: the
          absence is the compliment, so it is said out loud. */}
      {allZero ? (
        <div
          className="flex items-center justify-center rounded-sm border border-dashed border-rule-strong font-mono text-label uppercase tracking-[0.11em] text-dim"
          style={{ height: CHART_H }}
        >
          {lens.emptyNote}
        </div>
      ) : (
        <>
          <p className="sr-only">{lens.label} by season — {summary}</p>
          <div className="relative" style={{ height: CHART_H }} aria-hidden="true">
            <span className="absolute inset-x-0 h-px bg-rule-strong" style={{ top: HALF }} />
            <div className="flex h-full items-stretch gap-1.5">
              {arc.map((s) => {
                const val = valueOf(s, lens.key);
                const notPlayed = lens.production && unplayed.has(s.season);
                const px = notPlayed ? HALF : Math.max(2, Math.round((Math.abs(val) / max) * HALF));
                const positive = val >= 0;
                return (
                  <div key={s.season} className="relative min-w-0 flex-1">
                    <span
                      className={`absolute inset-x-0 rounded-sm ${
                        notPlayed ? "" : positive ? "bg-pos-bar" : "bg-neg-bar"
                      }`}
                      style={
                        notPlayed
                          ? { ...HATCH, bottom: HALF, height: px }
                          : positive
                            ? { bottom: HALF, height: px }
                            : { top: HALF, height: px }
                      }
                      title={
                        notPlayed
                          ? `${s.season}: not played yet`
                          : `${s.season}: ${fmt(val, lens.signed, lens.digits)}`
                      }
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      <div className="mt-1.5 flex gap-1.5">
        {arc.map((s) => (
          <div
            key={s.season}
            className="min-w-0 flex-1 text-center font-mono text-figure tabular text-dim"
          >
            {`'${String(s.season).slice(2)}`}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * The phone form: one row per metric — label, sparkline, latest figure.
 *
 * A 2-up grid needed three rows for six metrics and gave each chart ~170px of
 * width. Stacked rows put all six on one screen AND align the shapes season
 * over season, so comparing ACROSS metrics gets easier rather than harder.
 *
 * NO ZERO AXIS here, which is why every row carries its latest figure: sign has
 * to survive without the axis, and colour alone may never carry it. A negative
 * latest value shows its sign in the figure and its bar in `--neg-bar`; the
 * figure is the part that does not depend on hue.
 */
function SparkRow({ arc, lens, unplayed }: {
  arc: SeasonArc[]; lens: typeof LENSES[number]; unplayed: Set<number>;
}) {
  const values = arc.map((s) => valueOf(s, lens.key));
  const allZero = values.every((v) => v === 0);
  const max = Math.max(...values.map(Math.abs), 1);
  const lastSeason = arc[arc.length - 1];
  // "Latest" must not report a zero for a season that has not been played —
  // that is the same "null is not 0" violation the hatch exists to prevent,
  // and it was worse here: the sparkline drew "no data" while the figure
  // beside it asserted 0.0.
  const latestUnknown = lens.production && !!lastSeason && unplayed.has(lastSeason.season);
  const latest = values[values.length - 1] ?? 0;

  return (
    <div className="flex min-h-tap items-center gap-3 border-t border-rule px-0.5">
      <span className="w-[86px] shrink-0 font-mono text-label uppercase tracking-[0.1em] text-dim">
        {lens.label.replace(" Points", "")}
      </span>
      {allZero ? (
        <span className="flex-1 font-mono text-label uppercase tracking-[0.11em] text-dim">
          {lens.emptyNote}
        </span>
      ) : (
        <span className="flex h-[22px] flex-1 items-end gap-1" aria-hidden="true">
          {arc.map((s) => {
            const v = valueOf(s, lens.key);
            const notPlayed = lens.production && unplayed.has(s.season);
            return (
              <span
                key={s.season}
                className={`flex-1 rounded-sm ${
                  notPlayed ? "" : v < 0 ? "bg-neg-bar" : "bg-pos-bar"
                }`}
                style={
                  notPlayed
                    ? { ...HATCH, height: 22 }
                    : { height: Math.max(2, Math.round((Math.abs(v) / max) * 22)) }
                }
              />
            );
          })}
        </span>
      )}
      <span className="w-[72px] shrink-0 text-right font-mono text-figure tabular text-ink">
        {allZero || latestUnknown ? "—" : fmt(latest, lens.signed, lens.digits)}
      </span>
    </div>
  );
}

export function CareerArc({ arc }: Props) {
  if (arc.length === 0) {
    return (
      <Card>
        <CardHead title="Career arc" />
        <p className="text-prose leading-relaxed text-body">
          Season-by-season bars appear here once this franchise has made a trade.
        </p>
      </Card>
    );
  }
  const unplayed = unplayedSeasons(arc);
  return (
    <Card>
      <CardHead title="Career arc by season" />

      {/* Desktop — six small multiples. */}
      <div className="hidden min-[701px]:grid grid-cols-3 gap-x-6 gap-y-5 lg:grid-cols-6">
        {LENSES.map((lens) => (
          <MiniChart key={lens.key} arc={arc} lens={lens} unplayed={unplayed} />
        ))}
      </div>

      {/* Phone — stacked sparkline rows. */}
      <div className="min-[701px]:hidden" data-testid="career-arc-rows">
        <div className="mb-1 flex items-baseline justify-between font-mono text-label uppercase tracking-[0.11em] text-dim">
          <span>{`'${String(arc[0].season).slice(2)} → '${String(arc[arc.length - 1].season).slice(2)}`}</span>
          <span>Latest</span>
        </div>
        {LENSES.map((lens) => (
          <SparkRow key={lens.key} arc={arc} lens={lens} unplayed={unplayed} />
        ))}
      </div>
    </Card>
  );
}
