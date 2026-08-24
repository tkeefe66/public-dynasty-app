import {
  TradeDetailResp, OwnerDetailResp, DashboardResp, LeaderboardResp,
  LensMargins, LensWinners, TradeCall, TradeSideView,
} from "./types";
import {
  fmtLensMargin, LENS_LABEL, LENS_LABEL_LOWER, LENS_ORDER, realizedTotals,
  soleDecidedLens, StatTotals,
} from "./trade-lens";
import { PRODUCT_NAME } from "./brand";

/* ---------------------------------------------------------------------------
 * OG share cards — design_handoff_agate/CLAUDE_CODE.md § Commit 8, drawn in
 * `Agate System.dc.html` §08. "The Card Is The Ledger" (DESIGN.md): the same
 * system at twice the size — 52px rule pitch, real per-side totals (never
 * `snapshot_ktc_swing` shown on both sides — that double-counts one margin),
 * numeric rank (no 👑/🪣).
 *
 * This module builds pure data; `og-card.tsx` inlines the Agate light-ground
 * literals and does the rendering (next/og can't read CSS custom properties).
 * ------------------------------------------------------------------------ */

// Nameplate tiers, scaled for the card (README.md § "Nameplate tiers" is the
// 44/36/28/22 page scale; the card doubles the rule pitch so the ceiling
// tracks that — 80px for a league/owner headline that stands alone, 68px for
// the leaderboard card, which carries five-to-six ledger rows below it and
// has less vertical room to spend on the name).
const LARGE_TIERS = [80, 68, 54, 44];
const COMPACT_TIERS = [68, 58, 46, 38];
const LEN_BREAKS = [14, 24, 38, Infinity];

function nameplateSize(name: string, tiers: number[]): number {
  const i = LEN_BREAKS.findIndex((b) => name.length <= b);
  return tiers[i === -1 ? tiers.length - 1 : i];
}

/** Mirrors `ownerdeepdive/util.tsx::franchiseLetterTone`'s five-tier ramp —
 *  duplicated here (not imported) because that file returns Tailwind class
 *  names and this card needs literal hex (see `toneColor` in og-card.tsx). */
export type LetterTone = "pos" | "ink" | "ink_soft" | "neg_soft" | "neg";
function letterTone(letter: string): LetterTone {
  const head = letter.charAt(0).toUpperCase();
  if (head === "A") return "pos";
  if (head === "B") return "ink";
  if (head === "C") return "ink_soft";
  if (head === "D") return "neg_soft";
  return "neg";
}

/** The product name, from the single place that owns it (lib/brand.ts). */
const BRAND = PRODUCT_NAME;

const MONTHS_IN = new Set([9, 10, 11]);
function weekLabel(dateIso: string, week: number): string {
  return MONTHS_IN.has(Number(dateIso.slice(5, 7))) ? `Week ${week}` : "Offseason";
}

const LENS_TO_STAT: Record<keyof LensMargins, keyof StatTotals> = {
  value: "ktc", total: "total", regular: "regular", playoff: "playoff", toilet: "toilet",
};

// ---------------------------------------------------------------------------
// Trade card (Fig. 8.1)
// ---------------------------------------------------------------------------

export interface TradeLedgerRow {
  label: string;
  lens: keyof LensMargins;
  a: number;
  b: number;
}

export interface TradeCard {
  kind: "trade";
  eyebrow: string;
  headline: string;
  ruling: { badge: string; note: string };
  colA: string;
  colB: string;
  /** Which column reads in ink; null when the call is split/none — the card
   *  never invents a single winner (DESIGN.md § "The Ruling"). */
  winnerCol: "a" | "b" | null;
  rows: TradeLedgerRow[];
  footer: { left: string; right: string };
}

function ownerNameOf(sides: TradeSideView[], uid: string | null | undefined): string {
  return sides.find((s) => s.user_id === uid)?.owner_name ?? uid ?? "—";
}

/** Badge + one-line margin note + which column is the winner, read straight
 *  off the trade's per-lens verdict fields — never recomputed (DESIGN.md §
 *  "Figures Reconcile"). Mirrors TradeHero.tsx's RulingStamp language, kept
 *  to one decided lens instead of all of them (card space). */
function tradeRuling(
  sides: TradeSideView[], winnersByLens: LensWinners, marginsByLens: LensMargins,
  call: TradeCall, lensTally: string, lopsidedness: number,
): { badge: string; note: string; winnerCol: "a" | "b" | null } {
  // One decided lens is not a sweep — same rule as TradeHero's RulingStamp,
  // and it must be checked FIRST because `call` is "unanimous" whenever every
  // DECIDED lens went to one side, including when only one could be decided
  // (the normal state of a trade nobody has played: all four production lenses
  // sit at 0 for both sides and are unscored). A share card is the surface most
  // likely to be read without any of the page's context, so overclaiming here
  // is the most expensive place to do it.
  const sole = soleDecidedLens(winnersByLens);
  if (sole) {
    const uid = winnersByLens[sole]!;
    return {
      badge: `${LENS_LABEL_LOWER[sole]} only`,
      note: `${ownerNameOf(sides, uid)} ahead by ${fmtLensMargin(sole, marginsByLens[sole])} ${LENS_LABEL_LOWER[sole]}. No points on the board yet.`,
      winnerCol: sides[0]?.user_id === uid ? "a" : sides[1]?.user_id === uid ? "b" : null,
    };
  }
  if (call === "unanimous") {
    const winnerUid = LENS_ORDER.map((l) => winnersByLens[l]).find((v): v is string => !!v) ?? null;
    const decided = LENS_ORDER.filter((l) => winnersByLens[l] === winnerUid && marginsByLens[l] != null);
    const lens = decided[0];
    const badge = lopsidedness >= 0.6 ? "Lopsided" : "Edge";
    const note = lens
      ? `${ownerNameOf(sides, winnerUid)}, by ${fmtLensMargin(lens, marginsByLens[lens])} ${LENS_LABEL_LOWER[lens]}`
      : ownerNameOf(sides, winnerUid);
    const winnerCol: "a" | "b" | null =
      sides[0]?.user_id === winnerUid ? "a" : sides[1]?.user_id === winnerUid ? "b" : null;
    return { badge, note, winnerCol };
  }
  if (call === "split") {
    return { badge: `Split · ${lensTally}`, note: "The lenses disagree. Nobody gets the headline.", winnerCol: null };
  }
  return { badge: "Too close", note: "No lens decided it — every scored lens tied, or nothing scored.", winnerCol: null };
}

export function tradeCard(d: TradeDetailResp): TradeCard {
  const [A, B] = d.sides;
  const winnersByLens: LensWinners = d.winners_by_lens
    ?? { value: null, total: null, regular: null, playoff: null, toilet: null };
  const marginsByLens: LensMargins = d.margins_by_lens
    ?? { value: null, total: null, regular: null, playoff: null, toilet: null };
  const call: TradeCall = d.call ?? "none";
  const lensTally = d.lens_tally ?? "0-0";
  const lopsidedness = d.lopsidedness ?? 0;

  const ruling = tradeRuling(d.sides, winnersByLens, marginsByLens, call, lensTally, lopsidedness);

  // Each side's REALIZED total — a kept asset's own line plus a flipped
  // asset's became — the same reading the trade page's "Total realized" rows
  // use (TradeStatTable.realizedTotals, now shared via lib/trade-lens.ts).
  // Never `snapshot_ktc_swing`: that's one zero-sum margin, and showing it on
  // both sides double-counts the same number instead of reconciling against
  // the page the card links to.
  const totalsA = realizedTotals(A.breakdown);
  const totalsB = realizedTotals(B.breakdown);

  const rows: TradeLedgerRow[] = LENS_ORDER.map((lens) => ({
    label: LENS_LABEL[lens],
    lens,
    a: totalsA[LENS_TO_STAT[lens]],
    b: totalsB[LENS_TO_STAT[lens]],
  }));

  return {
    kind: "trade",
    eyebrow: `${d.league_name} · ${d.season} · ${weekLabel(d.date, d.week)}`,
    headline: d.story?.verdict ? d.story.verdict : `${A.owner_name} vs ${B.owner_name}`,
    ruling: { badge: ruling.badge, note: ruling.note },
    colA: A.owner_name, colB: B.owner_name, winnerCol: ruling.winnerCol,
    rows,
    footer: { left: BRAND, right: fmtDateShortForCard(d.date) },
  };
}

// Local copy of the app's fmtDateShort (web/lib/format-date.ts) — not
// imported to avoid this pure data module depending on a component-tree
// convention; the format itself ("Sep 24, 2025") is the same one TradeHero
// uses so the card's date reads identically to the page it links to.
const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
function fmtDateShortForCard(d: string | null | undefined): string {
  if (!d) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  if (!m) return d;
  const [, y, mo, day] = m;
  const month = MONTHS_SHORT[Number(mo) - 1];
  return month ? `${month} ${Number(day)}, ${y}` : d;
}

// ---------------------------------------------------------------------------
// Owner card (Fig. 8.4)
// ---------------------------------------------------------------------------

export interface OwnerCardRow {
  label: string;
  value: number;
  kind: "signed_int" | "signed_dec" | "plain";
}

export interface OwnerCard {
  kind: "owner";
  eyebrow: string;
  name: string;
  nameplateSize: number;
  /** Franchise Rating hero (CLAUDE.md § "Franchise Rating" — the platform
   *  verdict); null when the cache predates the field — the card omits the
   *  block rather than inventing a grade. */
  rating: { letter: string; tone: LetterTone; rank: number; of: number; value: number } | null;
  rows: OwnerCardRow[];
  footer: { left: string; right: string };
}

export function ownerCard(d: OwnerDetailResp, leagueName: string): OwnerCard {
  const trades = d.career_arc.reduce((n, s) => n + (s.trades || 0), 0);
  const fr = d.franchise_rating;
  const tr = d.track_record;
  return {
    kind: "owner",
    eyebrow: `${leagueName} · career`,
    name: d.owner.owner_name,
    nameplateSize: nameplateSize(d.owner.owner_name, LARGE_TIERS),
    rating: fr
      ? { letter: fr.letter, tone: letterTone(fr.letter), rank: fr.rank, of: fr.of, value: fr.rating }
      : null,
    rows: [
      { label: "Net trade value", value: d.totals_by_lens.ktc, kind: "signed_int" },
      { label: "Regular season points", value: d.totals_by_lens.regular, kind: "signed_dec" },
      { label: "Playoff points", value: d.totals_by_lens.playoff, kind: "signed_dec" },
      { label: "Trades", value: trades, kind: "plain" },
    ],
    footer: {
      left: BRAND,
      right: tr
        ? `${tr.titles} title${tr.titles === 1 ? "" : "s"} · ${tr.playoff_appearances} playoff trip${tr.playoff_appearances === 1 ? "" : "s"}`
        : `${trades} trade${trades === 1 ? "" : "s"}`,
    },
  };
}

// ---------------------------------------------------------------------------
// League card (Fig. 8.2) — dashboard standings, ranked by Trade Value
// ---------------------------------------------------------------------------

export interface LeagueStandRow { rank: number; name: string; value: number; }

export interface LeagueCard {
  kind: "league";
  eyebrow: string;
  name: string;
  nameplateSize: number;
  subhead: string;
  rows: LeagueStandRow[];
  footer: { left: string; right: string };
}

export function leagueCard(d: DashboardResp): LeagueCard {
  const top = [...d.standings].sort((x, y) => y.net_ktc - x.net_ktc).slice(0, 3);
  return {
    kind: "league",
    eyebrow: "DyNASTY · trade grader",
    name: d.league.name,
    nameplateSize: nameplateSize(d.league.name, LARGE_TIERS),
    subhead: `${d.league.total_rosters} managers · ${d.standings.reduce((n, r) => n + r.trades, 0)} trades graded`,
    rows: top.map((r, i) => ({ rank: i + 1, name: r.owner.owner_name, value: r.net_ktc })),
    footer: { left: BRAND, right: `Season ${d.league.season}` },
  };
}

// ---------------------------------------------------------------------------
// Leaderboard card (Fig. 8.3) — Franchise Ratings, /gm route
// ---------------------------------------------------------------------------

export interface GmStandRow {
  rank: number; name: string; rating: number; letter: string; tone: LetterTone; last: boolean;
}

export interface LeaderboardCard {
  kind: "leaderboard";
  eyebrow: string;
  name: string;
  nameplateSize: number;
  rows: GmStandRow[];
  footer: { left: string; right: string };
}

/** Franchise Ratings share card: the top GMs by rating + the last-place row,
 *  set apart by its own ink rule (DESIGN.md § "Rank is a number" — no 🪣). */
export function leaderboardCard(
  resp: LeaderboardResp, leagueName: string, weekLabelStr?: string,
): LeaderboardCard {
  const rows = [...resp.rows].sort((a, b) => a.rank - b.rank);
  const top = rows.slice(0, 5).map((r) => ({
    rank: r.rank, name: r.owner.owner_name, rating: r.rating, letter: r.letter,
  }));
  const last = rows[rows.length - 1];
  const standings = (
    last && !top.some((t) => t.rank === last.rank)
      ? [...top, { rank: last.rank, name: last.owner.owner_name, rating: last.rating, letter: last.letter }]
      : top
  ).map((t) => ({ ...t, tone: letterTone(t.letter), last: last ? t.rank === last.rank : false }));
  const scope = resp.scope === "all" ? "all-time" : resp.scope;
  return {
    kind: "leaderboard",
    eyebrow: `Franchise ratings · ${scope}`,
    name: leagueName,
    nameplateSize: nameplateSize(leagueName, COMPACT_TIERS),
    rows: standings,
    footer: { left: BRAND, right: weekLabelStr ? `as of ${weekLabelStr}` : scope },
  };
}

// ---------------------------------------------------------------------------

export interface FallbackCard { kind: "fallback"; eyebrow: string; title: string; }

export function fallbackCard(leagueName?: string): FallbackCard {
  return { kind: "fallback", eyebrow: BRAND, title: leagueName || "DyNASTY trade grader" };
}

export type AnyCard = TradeCard | OwnerCard | LeagueCard | LeaderboardCard | FallbackCard;
