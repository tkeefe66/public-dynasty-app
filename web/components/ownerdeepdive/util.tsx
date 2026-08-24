import { FranchiseRating, OwnerTradeRow } from "@/lib/types";

/** Text tone for the big Franchise Rating letter, a 5-tier ramp: A elite (pos),
 *  B strong (ink), C average (muted ink), D below the field (soft red), F the
 *  worst (full red — distinctly more severe than D). */
export function franchiseLetterTone(letter: string): string {
  const head = letter.charAt(0).toUpperCase();
  if (head === "A") return "text-pos-strong";
  if (head === "B") return "text-ink";
  if (head === "C") return "text-ink/70";
  if (head === "D") return "text-neg-strong/70";
  return "text-neg-strong";   // F — the worst, full red
}

/** Ordinal suffix (1st, 2nd, 3rd, 4th, … 11th, 21st, …) — the one shared
 *  implementation for HeroBand, TrackRecordTab, FutureDraftTab, and
 *  PastPicksTable, so the 11-13 exceptions are handled correctly everywhere. */
export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

export function signed(n: number, digits = 0): string {
  const v = digits ? n.toFixed(digits) : Math.round(n).toLocaleString();
  return n > 0 ? `+${v}` : v;
}

export function tone(n: number): string {
  return n > 0
    ? "text-pos-strong font-semibold"
    : n < 0 ? "text-neg-strong font-semibold" : "text-dim";
}

/** Maps a stable owner key (`user_id`) to one of the six franchise-identity
 *  slots (`--id-1`..`--id-6`, `.design/tokens/colors.css`). A deterministic
 *  string hash, not array index or render order — the same owner must land
 *  on the same colour across the dashboard, the owners rail, and this hero,
 *  regardless of how the league happens to be sorted or paginated. FNV-1a:
 *  simple, stable across JS engines (no reliance on string→number coercion
 *  quirks), and well distributed enough for a 6-way bucket. */
export function ownerIdentitySlot(userId: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < userId.length; i++) {
    hash ^= userId.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0) % 6 + 1;
}

export function whenLabel(t: OwnerTradeRow): string {
  const yr = `'${String(t.season).slice(2)}`;
  return t.week ? `${yr} W${t.week}` : yr;
}

/** Display names for rating-breakdown signal keys — shared by the Overview
 *  contribution bars, the hero driver/drag line, and receipts. The live path
 *  (`fr.pillars`) only ever carries the six v2 keys below (`engine/gm_rating
 *  .py::V2_SIGNAL_WEIGHTS`); the rest are retired v1 signal keys, kept here —
 *  harmlessly, since this is a label lookup with a `?? k` fallback, not a
 *  filter — so an old cached response or a historical screenshot still
 *  resolves a name instead of a raw key. */
export const SIGNAL_LABELS: Record<string, string> = {
  // v2 — live.
  expected_wins: "Expected Wins", playoff_success: "Playoff Success",
  luck: "Close Games", roster_value_share: "Roster Value",
  young_core_share: "Young Core", draft_capital: "Draft Capital",
  // Retired (pre-v2 Results/Skill/Outlook tree).
  championships: "Championships", playoff_depth: "Playoff Depth",
  made_playoffs: "Made Playoffs", final_seed: "Final Seed",
  points_for_rank: "Points-For Rank",
  trade_value: "Trade Value", trade_production: "Trade Production",
  lineup_skill: "Lineup Skill",
  playoff: "Playoff Points", regular: "Regular Season",
  value: "Trade Value", toilet: "Toilet Bowl",
  roster_value: "Roster Value",
  draft_skill: "Draft Skill", youth: "Youth",
};

/** The single loudest positive and negative signal across every pillar —
 *  same ±1-point noise floor the Overview bars use. Either half is null
 *  when nothing crosses the floor on that side. */
export function ratingDrivers(fr: FranchiseRating): { driver: string | null; drag: string | null } {
  let top: { label: string; points: number } | null = null;
  let bottom: { label: string; points: number } | null = null;
  for (const p of Object.values(fr.pillars)) {
    for (const [k, s] of Object.entries(p.signals)) {
      if (Math.abs(s.contribution) < 1) continue;
      const entry = { label: SIGNAL_LABELS[k] ?? k, points: s.contribution };
      if (entry.points > 0 && (!top || entry.points > top.points)) top = entry;
      if (entry.points < 0 && (!bottom || entry.points < bottom.points)) bottom = entry;
    }
  }
  return { driver: top?.label ?? null, drag: bottom?.label ?? null };
}
