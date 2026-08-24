// ─────────────────────────────────────────────────────────────────────────
// THE VOICE.  Every bit of trash-talk copy on the dashboard routes through
// this file. Retune the league's personality by editing the strings here;
// no component hardcodes a verdict. Per-owner names/rivalries/roasts come from
// the editable owner profiles (see lib/api getProfiles); the strings below are
// the league-wide "sharp but clean" defaults that wrap them.
// ─────────────────────────────────────────────────────────────────────────

import { Lens, ProfilesMap } from "./types";


/** The verb that fits what each lens actually measures, so verdicts stay true. */
const WIN_VERB: Record<Lens, string> = {
  ktc: "fleeced",
  production: "out-scored",
};

/** What the lens's number is denominated in, for the headline. */
const VALUE_NOUN: Record<Lens, string> = {
  ktc: "in trade value",
  production: "in points",
};

/** Strip the API's leading +/− and re-group thousands for prose. */
function magnitude(value: string): string {
  const cleaned = value.replace(/^[+−-]/, "").replace(/,/g, "").trim();
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return cleaned;
  return n.toLocaleString(undefined, {
    maximumFractionDigits: Number.isInteger(n) ? 0 : 1,
  });
}

// ── Profile-aware name resolution ──────────────────────────────────────────

function pick(name: string | undefined | null, fallback: string): string {
  const n = name?.trim();
  return n ? n : fallback;
}

/** Name to show for an owner who came out ahead (their `win_name`). */
export function winName(
  uid: string | undefined, fallback: string, profiles: ProfilesMap,
): string {
  return pick(uid ? profiles[uid]?.win_name : undefined, fallback);
}

/** Name to show for an owner who got beat (their `loss_name`). */
export function lossName(
  uid: string | undefined, fallback: string, profiles: ProfilesMap,
): string {
  return pick(uid ? profiles[uid]?.loss_name : undefined, fallback);
}

/** True when either owner lists the other as a rival. */
export function areRivals(
  a: string | undefined, b: string | undefined, profiles: ProfilesMap,
): boolean {
  if (!a || !b) return false;
  return (
    (profiles[a]?.rivals ?? []).includes(b) ||
    (profiles[b]?.rivals ?? []).includes(a)
  );
}

/** An owner's archetype label, if set ("The Loaded One"). */
export function archetypeOf(
  uid: string | undefined, profiles: ProfilesMap,
): string {
  return pick(uid ? profiles[uid]?.archetype : undefined, "");
}

/** An owner's signature roast, if set ("bought, not built"). */
export function roastOf(
  uid: string | undefined, profiles: ProfilesMap,
): string {
  return pick(uid ? profiles[uid]?.roast : undefined, "");
}

// ── Headlines ───────────────────────────────────────────────────────────────

/** One trade's two sides plus the profile map — the input to every headline.
 *  The winner slot is whoever came out ahead; the loser slot got beat. Names
 *  are the API display fallbacks used when no profile name is set. */
export interface Matchup {
  winnerUid?: string;
  winnerName: string;
  loserUid?: string;
  loserName: string;
  lens: Lens;
  profiles: ProfilesMap;
}

function resolve(m: Matchup) {
  return {
    winner: winName(m.winnerUid, m.winnerName, m.profiles),
    loser: lossName(m.loserUid, m.loserName, m.profiles),
    rivals: areRivals(m.winnerUid, m.loserUid, m.profiles),
  };
}

/** The big headline: who did what to whom, for how much. Rivals get spice. */
export function verdict(m: Matchup, value: string): string {
  const { winner, loser, rivals } = resolve(m);
  const target = rivals ? `his rival ${loser}` : loser;
  return `${winner} ${WIN_VERB[m.lens]} ${target} for ${magnitude(value)} ${VALUE_NOUN[m.lens]}.`;
}

/** Heist card name line ("Mike fleeced rival Jory"). */
export function winnerLine(m: Matchup): string {
  const { winner, loser, rivals } = resolve(m);
  return `${winner} ${WIN_VERB[m.lens]} ${rivals ? "rival " : ""}${loser}`;
}

/** Got-Robbed card name line, phrased from the loser's side. The Matchup's
 *  winner slot here is the robber (the counterparty who came out ahead). */
export function robbedLine(m: Matchup): string {
  const { winner, loser } = resolve(m);
  return `${loser} handed it to ${winner}`;
}

/** Per-owner one-word read, keyed off their letter grade. */
const GRADE_VERDICT: Record<string, string> = {
  A: "Robber baron",
  B: "Holds his own",
  C: "Donating value",
  D: "League charity",
};

export function gradeVerdict(grade: string): string {
  return GRADE_VERDICT[grade.charAt(0).toUpperCase()] ?? "";
}

/** Hall of Fame & Shame — attitude labels for the records panel rows. */
export const RECORD_LABEL = {
  biggest_value_swing: "Biggest heist",
  biggest_production: "Most points stolen",
  biggest_playoff: "Most playoff points",
  most_trades: "Wheeler-dealer",
} as const;

/** Loading-screen line, because even the wait should have a mouth. */
export const LOADING_GRADING = "Deciding who got robbed";
