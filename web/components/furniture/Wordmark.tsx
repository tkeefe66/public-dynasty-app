import { useId } from "react";
import { PRODUCT_NAME } from "@/lib/brand";

/**
 * The brand lockup: the drawn mark, then the product name.
 *
 * THE NAME IS "FANTASY ANALYZER". The design system names this product in three
 * places — `SKILL.md`'s frontmatter, `readme.md`'s opening line (which ties it
 * to `dynasty.tomkeefe.ai`, so it is this app and not a placeholder from
 * another project), and the mark's own `aria-label`. The app had been carrying
 * three different names at once: "dynasty.report" in the strip, the login page
 * and the share cards, and "FFB Dynasty" in the browser tab.
 *
 * THE MARK MUST BE INLINED, never `<img src>`. `.design/SKILL.md`: an `<img>`
 * is its own document, so `currentColor` resolves against nothing and the mark
 * renders black instead of taking the colour of the type beside it. That is
 * also why this is hand-ported JSX rather than a file import.
 *
 * `favicon.svg` is a deliberately DIFFERENT drawing — the seam smudges below
 * ~24px — so do not swap one for the other.
 *
 * The mask needs a document-unique id: two lockups on one page (a header and a
 * footer, say) would otherwise share one `<mask id>` and the second would
 * resolve against the first. `useId` makes that structurally impossible rather
 * than a thing to remember.
 */
export function Wordmark({
  size = 22,
  className = "",
  showName = true,
}: {
  size?: number;
  className?: string;
  showName?: boolean;
}) {
  const maskId = useId();
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <svg
        viewBox="0 0 512 512"
        width={size}
        height={size}
        fill="currentColor"
        role="img"
        aria-label="Fantasy Analyzer"
        className="shrink-0 text-stamp"
      >
        <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512">
          <rect width="512" height="512" fill="#000" />
          <g transform="rotate(-25 256 256)">
            <path
              d="M47,256C145.23,96.04 366.77,96.04 465,256C366.77,415.96 145.23,415.96 47,256Z"
              fill="#fff"
            />
            <path
              d="M72.08,256C157.77,241 354.23,241 439.92,256"
              fill="none"
              stroke="#000"
              strokeWidth="13"
              strokeLinecap="round"
            />
            {[184, 232, 280, 328].map((x) => (
              <line
                key={x}
                x1={x}
                y1="217"
                x2={x}
                y2="295"
                stroke="#000"
                strokeWidth="23.2"
                strokeLinecap="round"
              />
            ))}
          </g>
        </mask>
        <rect width="512" height="512" mask={`url(#${maskId})`} />
      </svg>
      {showName && (
        <span className="font-display text-name font-extrabold normal-case tracking-[-0.03em] text-ink">
          {PRODUCT_NAME}
        </span>
      )}
    </span>
  );
}
