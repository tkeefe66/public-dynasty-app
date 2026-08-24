import { OwnerRef } from "@/lib/types";

interface Props {
  owner: OwnerRef;
  variant?: "full" | "compact";
  // "lg" enlarges avatar + name for page heroes (e.g. the owner detail header).
  // Ignored for the compact variant.
  size?: "md" | "lg";
  // Heading tag for the name text node. Defaults to "span" (no semantic
  // heading) — pass "h1" for a page-hero usage so screen-reader users land on
  // exactly one h1. Every other call site is unaffected by default.
  nameAs?: React.ElementType;
}

export function OwnerLabel({ owner, variant = "full", size = "md", nameAs: NameTag = "span" }: Props) {
  const initial = (owner.owner_name || "?").charAt(0).toUpperCase();
  const compact = variant === "compact";
  const lg = !compact && size === "lg";
  // Agate — Avatars Come From Sleeper (DESIGN.md § "Named rules";
  // `Agate System.dc.html` §09): square, 26px — one rule tall — because a
  // circle would be the only radius in the system. That's the default
  // ("md") full-variant size, matched exactly here. The dense inline
  // "compact" chip variant (trade-party lists running in text) stays
  // smaller by necessity — 26px would overpower the surrounding copy — and
  // "lg" (page heroes) scales up proportionally. No generated mark: the
  // fallback is the owner's initial in Geist Mono on a `--rule` fill.
  const px = compact ? 18 : lg ? 48 : 26;
  const avatarSize = compact
    ? "h-[18px] w-[18px] text-label"
    : lg ? "h-12 w-12 text-section" : "h-[26px] w-[26px] text-figure";
  const nameSize = compact
    ? "font-sans font-medium"
    : lg
      ? "font-display text-section font-extrabold tracking-[var(--track-name)]"
      : "font-display text-name font-bold tracking-[var(--track-name)]";
  return (
    <span className={
      compact ? "inline-flex items-center gap-1.5 min-w-0"
        : lg ? "flex items-center gap-3 min-w-0"
        : "flex items-center gap-2.5 min-w-0"
    }>
      {owner.avatar_url ? (
        // Plain <img> (not next/image): Sleeper avatar hosts vary and aren't worth
        // an allowlist. Explicit width/height + lazy load avoid layout shift.
        // alt="" is intentional — the owner name is in the adjacent text node.
        //
        // The rule is disabled rather than left as a standing warning: these are
        // 26-52px thumbnails, so next/image's optimizer would add a Railway
        // round-trip per avatar for no visual gain, and it needs a remotePatterns
        // allowlist that a second platform's avatar host would silently break.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={owner.avatar_url}
          alt=""
          width={px}
          height={px}
          loading="lazy"
          className={`${avatarSize} object-cover bg-rule shrink-0`}
        />
      ) : (
        <span
          className={`${avatarSize} bg-rule text-dim grid place-items-center font-mono font-semibold shrink-0`}
        >
          {initial}
        </span>
      )}
      {/* Owner name only. The Sleeper team name lives in exactly one place —
          the two dashboard ledgers' Franchise column (StandingsTable) — where
          the franchise is the subject. Everywhere OwnerLabel appears the
          subject is the person, and a second grey name under the first only
          competed with it. */}
      <span className="min-w-0">
        <NameTag className={`block ${nameSize} text-ink leading-tight truncate`}>
          {owner.owner_name}
        </NameTag>
      </span>
    </span>
  );
}
