/**
 * Deterministic class merging for Furniture primitives.
 *
 * WHY THIS EXISTS: two Tailwind utilities of the same family have identical
 * specificity, so which one wins is decided by their order in the GENERATED
 * STYLESHEET, not by their order in the className string. `gap-4` beating
 * `gap-2.5` is an accident of where they sit in the spacing scale, and it
 * silently reverses if either value changes. Any primitive that ships its own
 * layout classes AND accepts a caller `className` must merge rather than
 * concatenate, or every override is a coin flip.
 *
 * Extracted from Row so Button can share it — an adversarial review of Button
 * caught it concatenating instead, safe today only because all seven callers
 * that overlap a family happen to pass the identical value already in the base.
 */

/** Families a caller may override. Anything not listed simply accumulates. */
const OVERRIDABLE = [
  // `grid-cols` MUST be listed separately from `grid`, and the lookup tries
  // longest-first for exactly this reason: a caller passing
  // `grid-cols-[20px_1fr]` is specifying TRACKS, not overriding `display:grid`.
  // Collapsing the two drops `grid` from the base and turns every row with
  // explicit columns into a block — which is most of them.
  "grid-cols", "grid-rows",
  "grid", "items", "gap", "gap-x", "gap-y",
  "px", "py", "p", "pl", "pr",
  "font", "text", "tracking", "min-h", "bg", "border",
];

/** Family of a utility: everything before the final value segment. */
function family(token: string): string {
  const bare = token.replace(/^[a-z-]+:/, ""); // strip a variant prefix
  for (const f of [...OVERRIDABLE].sort((a, b) => b.length - a.length)) {
    if (bare === f || bare.startsWith(`${f}-`)) return f;
  }
  return bare;
}

export function mergeClasses(base: string, override: string): string {
  const overrides = override.split(/\s+/).filter(Boolean);
  // A variant-prefixed override (`min-[701px]:px-2`) is conditional, so it must
  // NOT drop the unconditional base — the element still needs padding below
  // that breakpoint. Only unprefixed overrides displace a base class.
  const displaced = new Set(
    overrides.filter((t) => !/^[a-z-]+:/.test(t)).map(family)
  );
  const kept = base.split(/\s+/).filter(Boolean).filter((t) => !displaced.has(family(t)));
  return [...kept, ...overrides].join(" ");
}
