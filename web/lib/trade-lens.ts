import { AssetLine, LensMargins, LensWinners } from "@/lib/types";

/** The five-metric taxonomy (project CLAUDE.md), fixed order, everywhere a
 *  trade shows lenses side by side: the ruling stamp's margin sentence, the
 *  scoreboard, and the side ledgers' columns all import from here so the
 *  three views cannot drift out of the same order or the same number
 *  formatting (design_handoff_agate/DESIGN.md § "Figures Reconcile"). */
export const LENS_ORDER: (keyof LensMargins)[] = ["value", "total", "regular", "playoff", "toilet"];

/** The lenses that were actually decided — a winner was named.
 *
 *  `_lens_verdict` (api/app/services/trade_view.py) leaves a lens null when
 *  every side is 0 (unscored) or when leaders tie. So this is "how much of the
 *  five-lens vocabulary this trade could actually be judged on". */
export function decidedLenses(winners: LensWinners): (keyof LensMargins)[] {
  return LENS_ORDER.filter((l) => winners[l] != null);
}

/** The single lens carrying the whole verdict, or null when 0 or 2+ decided.
 *
 *  WHY THIS EXISTS. `call` is "unanimous" whenever every DECIDED lens went to
 *  one side — including when exactly one lens was decided. Before anyone plays,
 *  all four production lenses are 0 for both sides and therefore unscored, so a
 *  fresh trade produces `call: "unanimous"` off Trade Value alone. The UI then
 *  rendered the full-verdict language — "Prevailed" / "Lost", "won it by …" —
 *  for a trade nobody had played a snap in.
 *
 *  Callers use this to say what was actually won instead of claiming a sweep.
 *  Deliberately NOT phrased as "not yet played": all-zero production also
 *  happens when the assets simply never scored, and the payload cannot tell the
 *  two apart. "Only this lens is decided" is true either way. */
export function soleDecidedLens(winners: LensWinners): keyof LensMargins | null {
  const decided = decidedLenses(winners);
  return decided.length === 1 ? decided[0] : null;
}

/** Column/scoreboard header labels — the drawn short forms. */
export const LENS_LABEL: Record<keyof LensMargins, string> = {
  value: "Value",
  total: "Total",
  regular: "Reg",
  playoff: "Playoff",
  toilet: "Toilet",
};

/** The FIXED VOCABULARY, in full. `LENS_LABEL` above is an abbreviation that
 *  exists only for genuinely narrow metric columns — `TradeStatTable` fits five
 *  of them at 56-60px each. Anywhere the column can hold the real name, use
 *  this: the five metrics are a fixed vocabulary in a fixed order, and "Value"
 *  in particular drops the word the system is most protective of.
 *
 *  Do not abbreviate in a flexible column. The trade scoreboard shipped
 *  `LENS_LABEL` in a `minmax(0,1fr)` track (~830px at template width) with a
 *  docstring claiming it was preserving column width — there was no width to
 *  preserve. */
export const LENS_LABEL_FULL: Record<keyof LensMargins, string> = {
  value: "Trade Value",
  total: "Total Points",
  regular: "Regular Season Points",
  playoff: "Playoff Points",
  toilet: "Toilet Bowl Points",
};

/** Lowercase form for inline prose (the ruling stamp's margin sentence). */
export const LENS_LABEL_LOWER: Record<keyof LensMargins, string> = {
  value: "value",
  total: "total",
  regular: "reg",
  playoff: "playoff",
  toilet: "toilet",
};

/** Format one lens's own figure — value is an integer with thousands
 *  separators (today's dynasty market value); the four production lenses are
 *  points to one decimal, matching every points column elsewhere in the app. */
export function fmtLensValue(lens: keyof LensMargins, v: number): string {
  return lens === "value" ? Math.round(v).toLocaleString() : v.toFixed(1);
}

/** Format a signed margin: the sign is always rendered (DESIGN.md § "The
 *  Signed Number"); null/absent (unscored or tied) renders "—" and is left to
 *  the caller to color `--dim`. */
export function fmtLensMargin(lens: keyof LensMargins, v: number | null | undefined): string {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${fmtLensValue(lens, Math.abs(v))}`;
}

// ---------------------------------------------------------------------------
// realizedTotals — what a side actually ended up with. Moved here (out of
// TradeStatTable.tsx, which re-exports it for its existing importers) so the
// OG share card (web/lib/og-card-data.ts, a non-React module the nodejs-
// runtime image routes import) can read the exact same reconciled totals the
// trade page renders, without importing a .tsx component into lib/.
// ---------------------------------------------------------------------------

export interface StatTotals {
  ktc: number;
  total: number;
  regular: number;
  playoff: number;
  toilet: number;
  /** Starters-only across every week. NOT one of the five lenses — the lens
   *  taxonomy and `margins_by_lens` are unchanged — just an extra accumulated
   *  figure so a card can lead with what was actually deployed. */
  started: number;
}

export function sumBecame(b: AssetLine[]): StatTotals {
  const k = (f: (a: AssetLine) => number) => b.reduce((s, a) => s + f(a), 0);
  return {
    ktc: k((a) => a.ktc),
    total: k((a) => a.production_total),
    regular: k((a) => a.production_regular),
    playoff: k((a) => a.production_playoff),
    toilet: k((a) => a.production_toilet),
    started: k((a) => a.production_started),
  };
}

/** What a side actually ended up with: a kept asset contributes its own line;
 *  a flipped asset contributes what it became (the realized outcome). Mirrors
 *  the backend's `_realized_lens_totals` row-for-row so this figure and the
 *  API's `margins_by_lens` can never drift apart — and the OG trade card's two
 *  columns and the trade page's "Total realized" rows always agree. */
export function realizedTotals(rows: AssetLine[]): StatTotals {
  const acc: StatTotals = { ktc: 0, total: 0, regular: 0, playoff: 0, toilet: 0, started: 0 };
  for (const r of rows) {
    const v = r.flip && r.flip.became.length > 0 ? sumBecame(r.flip.became) : {
      ktc: r.ktc, total: r.production_total, regular: r.production_regular,
      playoff: r.production_playoff, toilet: r.production_toilet,
      started: r.production_started,
    };
    acc.ktc += v.ktc; acc.total += v.total; acc.regular += v.regular;
    acc.playoff += v.playoff; acc.toilet += v.toilet; acc.started += v.started;
  }
  return acc;
}
