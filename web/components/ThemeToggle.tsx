"use client";

import { Mark as Icon } from "./furniture/Mark";
import { useTheme } from "./ThemeProvider";

const OPTIONS: { key: "light" | "dark"; label: string }[] = [
  { key: "light", label: "Light" },
  { key: "dark", label: "Dark" },
];

/**
 * The theme control. `light`/`dark` draw as a sun and a moon (Furniture's
 * stroked `Mark` set has curves; Agate's ring-and-square stood in only
 * because that system forbade them).
 *
 * ICON-ONLY. The words "LIGHT"/"DARK" are gone: the two marks already say
 * which ground each cell selects, and at 8.5px mono the labels were the widest
 * thing in the right-hand group — a caption on a picture of itself. The names
 * survive on `aria-label`, so the control is still spoken as "Light theme" /
 * "Dark theme", and `aria-pressed` still carries which one is on.
 *
 * Deliberately its own control, not a SegmentControl: a BORDERED pill
 * (`--rule-strong` hairline, `overflow-hidden`), not a sunk well, and the
 * active fill is `--ink` — not the stamp — because dark is a first-class
 * ground, not an inversion.
 *
 * SIZE IS NOT A TAP-TARGET VIOLATION. `.design/components/controls/
 * ThemeToggle.prompt.md` is explicit: "This is the one control at 30px rather
 * than 44px: it sits in a 44px chrome strip where a 44px pill would define the
 * strip's height." 31px square cells are that sanctioned exception, and the
 * utility control beside it matches so the pair reads as one group.
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div
      role="group"
      aria-label="Theme"
      className="inline-flex items-stretch overflow-hidden rounded-pill border border-rule-strong"
    >
      {OPTIONS.map((opt) => {
        const active = theme === opt.key;
        return (
          <button
            key={opt.key}
            type="button"
            onClick={() => setTheme(opt.key)}
            aria-pressed={active}
            aria-label={`${opt.label} theme`}
            className={`flex h-[31px] w-[31px] items-center justify-center transition-colors ${
              active ? "bg-ink text-bg" : "text-dim hover:text-ink"
            }`}
          >
            <Icon name={opt.key} size={14} />
          </button>
        );
      })}
    </div>
  );
}
