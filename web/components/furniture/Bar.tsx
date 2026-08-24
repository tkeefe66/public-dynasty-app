/* ---------------------------------------------------------------------------
 * Bar — the port of `.design/components/data/Bar.jsx`. A magnitude bar in a
 * sunk track; replaces Agate's `InkBar`.
 *
 * COLOUR IS CORRECT HERE. Agate's rule was absolute — "a bar is not a number,
 * so a bar is never coloured" — because in a system whose only colour was a
 * signed figure, a coloured pixel could mean nothing else. Furniture lifts
 * that: a margin IS a signed value, and the tokens ship a THIRD pair for it,
 * `--pos-bar`/`--neg-bar`, weight-matched so neither hue reads as "more" at
 * equal length. They are deliberately NOT `--pos`/`--neg`: a bar is a large
 * solid area, and the figure pair is tuned for 10-13px type where `--neg` runs
 * hotter and would pull red forward.
 *
 * A negative bar is SOLID and grows leftward from the centre line. A hollow
 * outline was tried and abandoned upstream: at real magnitudes many bars are
 * 3-8px wide, where a 1.5px ring on each side leaves no interior at all.
 *
 * `aria-hidden`: a bar never carries information that is not also in the figure
 * beside it, so it is decoration to a screen reader by construction.
 *
 * TWO DELIBERATE DIVERGENCES FROM THE SOURCE, both recorded so a future diff
 * does not read them as sloppiness:
 *
 * 1. RADIUS. `Bar.jsx` hardcodes `borderRadius: 3` — a fourth radius on a
 *    system that says "no fourth". `rounded-pill` is used instead. This is not
 *    a visual change: with all four corners equal, CSS clamps the rendered
 *    radius to `min(R, w/2, h/2)`, so at `h-[5px]` both `3` and `--radius-pill`
 *    resolve to 2.5px — identical at every width the bar can take, including
 *    the 3-8px cases the source's own docblock worries about. They would only
 *    diverge at height ≥ 7. Porting the literal was not an option anyway: the
 *    drift guard rejects `rounded-[3px]`, and the inline-style form is worse
 *    because the guard cannot see it at all. Logged upstream.
 *
 * 2. NO `height` PROP, and no `px()` coercion. `px()` exists upstream because
 *    DC templates pass `size="78"` as a string attribute; `BarProps` is typed,
 *    so `tsc` makes that unreachable. The `height` prop has one call site at
 *    one height. NOTE the escape hatch is imperfect: `className` is
 *    concatenated, not merged, so a caller passing `h-2` yields `h-[5px] h-2`
 *    and Tailwind resolves it by stylesheet order, not attribute order. If a
 *    second height is ever needed, restore a typed prop or route through
 *    `mergeClasses` (see `Button.tsx`'s note and `tests/row-merge.test.ts`) —
 *    do not rely on the className override.
 * ------------------------------------------------------------------------ */

export interface BarProps {
  value: number;
  /** The full track. A non-positive `max` draws an empty track rather than
   *  dividing by zero — an unscored lens has nothing to scale against. */
  max: number;
  signed?: boolean;
  className?: string;
}

export function Bar({ value, max, signed = false, className = "" }: BarProps) {
  const pct = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  const neg = value < 0;
  const fill = signed ? (neg ? "bg-neg-bar" : "bg-pos-bar") : "bg-ink";

  if (!signed) {
    return (
      <span
        aria-hidden="true"
        className={`block h-[5px] overflow-hidden rounded-pill bg-rule ${className}`}
      >
        <span className={`block h-full rounded-pill ${fill}`} style={{ width: `${pct}%` }} />
      </span>
    );
  }

  return (
    <span aria-hidden="true" className={`relative block h-[5px] rounded-pill bg-rule ${className}`}>
      <span className="absolute -top-px -bottom-px left-1/2 w-px bg-rule-strong" />
      {pct > 0 && (
        <span
          className={`absolute top-0 bottom-0 rounded-pill ${fill}`}
          style={neg ? { right: "50%", width: `${pct / 2}%` } : { left: "50%", width: `${pct / 2}%` }}
        />
      )}
    </span>
  );
}
