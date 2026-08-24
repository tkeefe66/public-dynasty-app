import { TradeProductionSeries, TradeSideView } from "@/lib/types";
import { realizedTotals } from "@/lib/trade-lens";

/** Deterministic "what decided it" stats — the receipts behind the grade, no
 *  LLM. Extracted from the old TradeHero.tsx (pre-Agate) so the Agate
 *  FINDINGS section (design_handoff_agate/CLAUDE_CODE.md § Commit 4) can
 *  render the same derived facts without the component needing to know how
 *  they're computed. Built ONLY from data the trade response already
 *  provides — see the file-level comment on `buildInsights` for the exact
 *  library of comparisons. */

export function fmtInt(n: number): string {
  return Math.round(n).toLocaleString();
}

interface Driver {
  label: string;
  owner: string;
  isWinner: boolean;
  started: number;
  total: number;
  dropped: boolean;
}

// Deterministic "what decided it": the realized players each side ended up
// with (a flipped asset contributes what it became), ranked by started
// points — the receipts behind the grade, no LLM.
export function collectDrivers(sides: TradeSideView[], winnerId: string | null): Driver[] {
  const out: Driver[] = [];
  for (const side of sides) {
    const isWinner = side.user_id === winnerId;
    for (const r of side.breakdown ?? []) {
      const realized = r.flip?.became?.length ? r.flip.became : [r];
      for (const a of realized) {
        if (a.kind === "pick") continue; // unresolved future pick — no production
        out.push({
          label: a.label,
          owner: side.owner_name,
          isWinner,
          started: a.production_started ?? 0,
          total: a.production_total ?? 0,
          dropped: a.terminal_state === "dropped",
        });
      }
    }
  }
  return out.sort((a, b) => b.started - a.started);
}

export interface Insight {
  stat: string;
  text: string;
  tone: "pos" | "neg";
}

interface SideAgg {
  ktc: number;
  total: number;
  started: number;
  playoff: number;
}

// Realized aggregates per side (a flipped asset contributes what it became) —
// matches the receipts' Total-realized rollup, so the insights and the tables
// agree. `total`/`playoff` come straight from `realizedTotals` (trade-lens.ts)
// instead of a second flip→became walk — picks always carry zero production
// (engine/trade_grader.py::build_asset_breakdown), so including them in the
// shared sum doesn't change the result. `production_started` isn't one of
// the five reconciled StatTotals metrics (it's a lineup question, not a
// trade-value one), so it still needs its own walk.
function startedTotal(side: TradeSideView): number {
  let started = 0;
  for (const r of side.breakdown ?? []) {
    const realized = r.flip?.became?.length ? r.flip.became : [r];
    for (const a of realized) {
      if (a.kind === "pick") continue;
      started += a.production_started ?? 0;
    }
  }
  return started;
}

function realizedAgg(side: TradeSideView): SideAgg {
  const t = realizedTotals(side.breakdown ?? []);
  return { ktc: t.ktc, total: t.total, started: startedTotal(side), playoff: t.playoff };
}

// A pick-derived player carries `from_pick` (the pick was drafted into them).
// Report a bust (became a player who got cut for nothing) or a winner's steal.
function pickOutcome(winner: TradeSideView, loser: TradeSideView): Insight | null {
  const fromPick = (side: TradeSideView, isWinner: boolean) => {
    const rows: {
      label: string;
      owner: string;
      started: number;
      dropped: boolean;
      isWinner: boolean;
    }[] = [];
    for (const r of side.breakdown ?? []) {
      const realized = r.flip?.became?.length ? r.flip.became : [r];
      for (const a of realized) {
        if (a.kind === "pick" || !a.from_pick) continue;
        rows.push({
          label: a.label,
          owner: side.owner_name,
          started: a.production_started ?? 0,
          dropped: a.terminal_state === "dropped",
          isWinner,
        });
      }
    }
    return rows;
  };
  const all = [...fromPick(winner, true), ...fromPick(loser, false)];
  const bust = all.find((p) => p.dropped && p.started < 10);
  if (bust) {
    return {
      stat: "Bust",
      text: `${bust.owner}'s pick became ${bust.label}, then got cut for nothing`,
      tone: "neg",
    };
  }
  const steal = all.filter((p) => p.isWinner).sort((a, b) => b.started - a.started)[0];
  if (steal && steal.started >= 150) {
    return {
      stat: `${fmtInt(steal.started)}`,
      text: `${steal.owner}'s pick turned into ${steal.label}, ${fmtInt(steal.started)} started points`,
      tone: "pos",
    };
  }
  return null;
}

// A library of derived comparisons that justify the grade — NOT a restatement
// of the per-player table. Each fires only when its threshold is met, so
// different trades surface different "aha" stats; the caller takes the
// strongest `limit` (FINDINGS shows three; design_handoff_agate/CLAUDE_CODE.md
// § Commit 4 — "three derived stats, mono figure + one-line sentence").
export function buildInsights(
  winner: TradeSideView,
  loser: TradeSideView,
  winnerDrivers: Driver[],
  series?: TradeProductionSeries,
  limit = 3,
): Insight[] {
  const w = realizedAgg(winner);
  const l = realizedAgg(loser);
  const wTop = winnerDrivers[0];
  const out: Insight[] = [];

  // 1. The winner's single best piece outscored the loser's WHOLE return.
  if (wTop && l.started > 0 && wTop.started > l.started) {
    out.push({
      stat: `${fmtInt(wTop.started)} vs ${fmtInt(l.started)}`,
      text: `${wTop.label} alone outscored ${loser.owner_name}'s entire return on started points`,
      tone: "pos",
    });
  }

  // Drop regret — a player the loser cut who then piled up NFL points.
  let regret: { label: string; after: number } | null = null;
  for (const r of loser.breakdown ?? []) {
    const realized = r.flip?.became?.length ? r.flip.became : [r];
    for (const a of realized) {
      const after = a.production_after_drop ?? 0;
      if (a.terminal_state === "dropped" && after >= 60) {
        if (!regret || after > regret.after) regret = { label: a.label, after };
      }
    }
  }
  if (regret) {
    out.push({
      stat: `${fmtInt(regret.after)} pts`,
      text: `${loser.owner_name} dropped ${regret.label}, who put up ${fmtInt(regret.after)} over the next 10 weeks`,
      tone: "neg",
    });
  }

  // 3. Time to overtake: the week the winner matched the loser's WHOLE return.
  const wSeries = series?.[winner.user_id]?.started ?? [];
  const lSeries = series?.[loser.user_id]?.started ?? [];
  if (wSeries.length > 2 && lSeries.length) {
    const loserFinal = lSeries[lSeries.length - 1]?.value ?? 0;
    if (loserFinal > 0) {
      const idx = wSeries.findIndex((p) => p.value >= loserFinal);
      if (idx > 0 && idx < wSeries.length - 2) {
        const p = wSeries[idx];
        out.push({
          stat: `Wk ${p.week}`,
          text: `${winner.owner_name} matched ${loser.owner_name}'s entire return by Week ${p.week}, ${p.season}`,
          tone: "pos",
        });
      }
    }
  }

  // 3. Playoff swing — the points that actually decide titles.
  if (w.playoff > 0 && w.playoff - l.playoff >= 20) {
    out.push({
      stat: `${fmtInt(w.playoff)} vs ${fmtInt(l.playoff)}`,
      text: `${winner.owner_name} buried ${loser.owner_name} on playoff points, the games that decide titles`,
      tone: "pos",
    });
  }

  // 4. Value multiple today — realized (flip-aware), matching the Value
  // column each side actually shows on the ledger, not the raw as-traded haul.
  if (l.ktc > 0) {
    const mult = w.ktc / l.ktc;
    if (mult >= 1.3) {
      out.push({
        stat: `${mult.toFixed(1)}×`,
        text: `${winner.owner_name}'s haul is worth ${mult.toFixed(1)} times ${loser.owner_name}'s today`,
        tone: "pos",
      });
    }
  }

  // 5. Deployment waste — production that never reached the lineup.
  if (l.total > 0) {
    const wasted = Math.round((1 - l.started / l.total) * 100);
    if (wasted >= 15) {
      out.push({
        stat: `${wasted}%`,
        text: `of ${loser.owner_name}'s points never reached the starting lineup`,
        tone: "neg",
      });
    }
  }

  // 6. Pick payoff / bust.
  const pick = pickOutcome(winner, loser);
  if (pick) out.push(pick);

  // 7. Clean sweep — won every column (capstone, shows when specifics don't
  // fill). Realized (flip-aware) value, matching the ledger's Value column.
  if (
    w.ktc > l.ktc &&
    w.total > l.total &&
    w.started > l.started &&
    w.playoff > l.playoff
  ) {
    out.push({
      stat: "Sweep",
      text: `${winner.owner_name} won every column: value, total, started, and playoff points`,
      tone: "pos",
    });
  }

  return out.slice(0, limit);
}
