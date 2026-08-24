"use client";

/** The app's one segmented-control dialect: every single-select chip group —
 *  year and season filters, metric switches, view toggles. If something
 *  switches a single-select view it is this, not a bespoke pill.
 *
 *  A RUN, NOT A PILL IN A WELL. Furniture's first draft drew this as a sunk
 *  track with a stamp-filled pill riding in it, 44px of pill plus 3px of well
 *  each side. That is 50px of chrome per control, and controls arrive in
 *  PAIRS: the production chart spent 120px on two of them plus their whisper
 *  labels before drawing a single data point. The well and the pill are both
 *  gone. Options sit as a plain mono run and the active one takes full ink
 *  plus a 2px stamp underline.
 *
 *  THE UNDERLINE IS THE POINT. `.design`'s own note on this component says the
 *  active segment inverts "because a colour-only change does not read" — an
 *  underline satisfies that requirement without the 50px, because it is a
 *  change of SHAPE. Weight alone (bold among dim) does not, which is why the
 *  inactive options keep their dim tone rather than only losing bold.
 *
 *  THE TAP TARGET IS STILL 44px. The visible run is ~24px, but each button
 *  carries a transparent `before:` box at -11px/-8px, so the hit area clears
 *  the system's 44px floor at the same time as the ink stops claiming it.
 *  Shrinking the target along with the paint is the trap this avoids.
 *
 *  NO RADIUS ON THE UNDERLINE. Zero is the sanctioned radius for a rule, and
 *  the drift guard's `radius` rule bans an arbitrary `rounded-[2px]` outright.
 *
 *  It WRAPS rather than scrolling — horizontal scroll is banned by the drift
 *  guard, and without the well a wrapped run costs two 24px lines instead of
 *  two 50px rows, which is what makes a nine-season league affordable.
 *
 *  SIZE: `text-label` (8.5px) is the seven-step scale's floor and the category
 *  a mono uppercase label belongs to. The design system's own file hardcodes
 *  `fontSize: 10`, which is not on that scale; logged as an upstream
 *  discrepancy and not copied here. */
export function SegmentControl<T extends string | number>({
  options, value, onChange, "aria-label": ariaLabel, className = "",
}: {
  options: { key: T; label: React.ReactNode }[];
  value: T;
  onChange: (next: T) => void;
  "aria-label": string;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={`inline-flex flex-wrap items-center gap-x-4 gap-y-2 ${className}`}
    >
      {options.map((opt) => {
        const active = opt.key === value;
        return (
          <button
            key={String(opt.key)}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.key)}
            className={
              "relative py-[3px] font-mono text-label uppercase tracking-[0.08em] transition-colors " +
              // The 44px hit area, invisible. Kept off the active/inactive
              // branch below so it can never be dropped by a style change.
              "before:absolute before:-inset-x-[8px] before:-inset-y-[11px] before:content-[''] " +
              // The selection mark. Always present, transparent when inactive,
              // so switching does not reflow the run by a pixel.
              "after:absolute after:inset-x-0 after:-bottom-[3px] after:h-[2px] after:content-[''] " +
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ringfocus)] " +
              (active
                ? "font-bold text-ink after:bg-stamp"
                : "font-normal text-dim after:bg-transparent hover:text-ink")
            }
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
