/**
 * The product's name, in one place.
 *
 * The app had been carrying THREE at once: "dynasty.report" in the chrome
 * strip, the login page and the share cards; "FFB Dynasty" in the browser tab;
 * and "Fantasy Analyzer" in the design system, which is the one that is right.
 * `.design/SKILL.md`'s frontmatter, `.design/readme.md`'s opening line (which
 * names `dynasty.tomkeefe.ai` explicitly, so it is describing this app rather
 * than borrowing a placeholder) and `assets/logo/mark.svg`'s `aria-label` all
 * agree on it.
 *
 * A PLAIN MODULE, not the component. `lib/og-card-data.ts` must stay pure data
 * with no JSX so its tests can run without Satori in the loop; importing the
 * lockup component for a string would have pulled React into that path.
 * `components/furniture/Wordmark.tsx` reads from here too, so the drawn lockup
 * and every string surface can never disagree.
 */
export const PRODUCT_NAME = "Fantasy Analyzer";
