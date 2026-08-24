import type { ReactNode } from "react";

/* ---------------------------------------------------------------------------
 * Figure — the port of `.design/components/data/Figure.jsx`.
 *
 * Every number in the product. Geist Mono, tabular, right-aligned by default so
 * columns line up digit-for-digit.
 *
 * COLOUR BELONGS TO SIGNED VALUES ONLY. An unsigned figure is always ink; zero
 * and absent are both `--dim`, absent as an em dash. `signed` is for a margin or
 * a delta — a rating, a record or a count is ink. The pair used here is
 * `--pos`/`--neg`, tuned for 10-13px mono on paper: a LARGE glyph needs
 * `--pos-strong`/`--neg-strong` (see `GradeLetter`), and a BAR needs
 * `--pos-bar`/`--neg-bar` (see `Bar`). Three pairs, not interchangeable.
 * ------------------------------------------------------------------------ */

/** U+2212 MINUS SIGN, never `toLocaleString`'s U+002D hyphen-minus: in a
 *  tabular-nums column the two differ in width and vertical position, and a
 *  card showing a hyphen headline above a true-minus meta line reads as two
 *  different kinds of number. This is the system's single source for the
 *  glyph — anything parsing these strings back must normalise it. */
const MINUS = "−";
const EM_DASH = "—";

/** `grouped` exists because this repo already ships two number dialects and
 *  they have to keep agreeing: `lib/trade-lens.ts::fmtLensValue` groups the
 *  Trade Value lens (`3,940`) and does NOT group the four points lenses
 *  (`1234.5`), and the side ledgers render every figure through it. A Figure
 *  that grouped unconditionally would print `1,234.5` in the scoreboard beside
 *  `1234.5` in the ledger for the same number — the same defect "figures
 *  reconcile" exists to prevent, one layer down in the formatting. */
function fmt(v: number, dp: number, grouped: boolean): string {
  const abs = Math.abs(v);
  const s = grouped
    ? abs.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })
    : abs.toFixed(dp);
  return v < 0 ? MINUS + s : s;
}

export interface FigureProps {
  value: number | null | undefined;
  /** A margin or a delta. Renders the `+` and takes `--pos`/`--neg`. */
  signed?: boolean;
  /** Decimal places. */
  dp?: number;
  /** Thousands separators. See the note on `fmt`. */
  grouped?: boolean;
  align?: "right" | "left";
  /** Force `--dim` — e.g. a figure that is present but not in scope. */
  dim?: boolean;
  suffix?: ReactNode;
  className?: string;
}

export function Figure({
  value,
  signed = false,
  dp = 0,
  grouped = true,
  align = "right",
  dim = false,
  suffix,
  className = "",
}: FigureProps) {
  const empty = value == null || Number.isNaN(value);
  const n = empty ? NaN : (value as number);
  const zero = n === 0;
  const tone =
    empty || zero || dim ? "text-dim" : signed ? (n > 0 ? "text-pos-strong" : "text-neg-strong") : "text-ink";
  const weight = signed && !empty && !zero ? "font-semibold" : "";
  return (
    <span
      className={`font-mono text-figure tabular whitespace-nowrap ${
        align === "right" ? "text-right" : "text-left"
      } ${tone} ${weight} ${className}`}
    >
      {empty ? EM_DASH : `${signed && n > 0 ? "+" : ""}${fmt(n, dp, grouped)}`}
      {suffix ? <span className="text-dim"> {suffix}</span> : null}
    </span>
  );
}
