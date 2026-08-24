import { OwnerDetailResp, TradeDetailResp } from "@/lib/types";
import { TabKey } from "@/components/ownerdeepdive/OverviewTab";
import { ordinal, ratingDrivers, signed } from "@/components/ownerdeepdive/util";
import { fmtLensMargin } from "@/lib/trade-lens";

/** Group-chat receipt builders. Deterministic, numbers-first, no hedging.
 *  Vocabulary rule: the string "KTC" never appears — it is "Trade Value". */

function deals(n: number): string {
  return `${n} deal${n === 1 ? "" : "s"}`;
}

export function ownerReceipt(
  detail: OwnerDetailResp, tab: TabKey, tradesYear: number | "all",
): string {
  const name = detail.owner.owner_name;
  const fr = detail.franchise_rating;
  switch (tab) {
    case "trades": {
      const rows = tradesYear === "all"
        ? detail.trades
        : detail.trades.filter((t) => t.season === tradesYear);
      const value = rows.reduce((s, t) => s + t.swing_ktc, 0);
      const scope = tradesYear === "all" ? `${name}'s trades` : `${name}'s ${tradesYear} trades`;
      return `${scope}: ${signed(value)} Trade Value across ${deals(rows.length)}`;
    }
    case "record": {
      const tr = detail.track_record;
      if (!tr) break;
      const rec = `${tr.career_wins}-${tr.career_losses}${tr.career_ties ? `-${tr.career_ties}` : ""}`;
      const best = tr.best_finish != null ? `, best finish ${ordinal(tr.best_finish)}` : "";
      return `${name} all-time: ${tr.titles} title${tr.titles === 1 ? "" : "s"}, ${rec}${best}`;
    }
    case "outlook": {
      const o = detail.outlook;
      if (!o) break;
      const rank = detail.roster_rank ? `, roster #${detail.roster_rank.rank} of ${detail.roster_rank.of}` : "";
      return `${name}'s outlook: ${o.window}${rank}`;
    }
  }
  // Overview + every fallback path.
  if (fr) {
    const { driver } = ratingDrivers(fr);
    const carried = driver ? ` — carried by ${driver}` : "";
    return `${name}: ${fr.letter} franchise, ${ordinal(fr.rank)} of ${fr.of}${carried}`;
  }
  return `${name} — franchise receipts`;
}

/** Canonical owner-page path — mirrors OwnerDeepDive.syncQuery's rules
 *  (omit defaults so the link matches the address bar). */
export function ownerPath(
  leagueId: string, uid: string, tab: TabKey, tradesYear: number | "all",
): string {
  const sp = new URLSearchParams();
  if (tab !== "overview") sp.set("tab", tab);
  if (tab === "trades" && tradesYear !== "all") sp.set("year", String(tradesYear));
  const qs = sp.toString();
  return `/league/${leagueId}/owner/${uid}${qs ? `?${qs}` : ""}`;
}

export function tradeReceipt(data: TradeDetailResp): string {
  const when = `'${String(data.season).slice(2)}${data.week ? ` W${data.week}` : ""}`;
  if (data.sides.length < 2) return when;
  const names = data.owner_names ?? {};
  const [a, b] = data.sides;
  const nameOf = (uid: string) => names[uid] ?? "—";
  const ptsPair = (x: typeof a, y: typeof b) =>
    `${Math.round(x.production_started)}-${Math.round(y.production_started)} started pts`;
  const winner = data.winner_user_id ? data.sides.find((s) => s.user_id === data.winner_user_id) : undefined;
  const loser = winner ? data.sides.find((s) => s.user_id !== winner.user_id) : undefined;
  if (winner && loser) {
    const base = `${when} — ${nameOf(winner.user_id)} beat ${nameOf(loser.user_id)}: ${ptsPair(winner, loser)}`;
    // The value-lens margin, straight from the same `margins_by_lens` field
    // the ruling stamp/scoreboard read — never recomputed from received_ktc,
    // which can disagree with the stamp once a flip moves value between
    // sides. Only attach it when the value lens actually named this side the
    // winner; otherwise degrade honestly and drop the clause rather than
    // mislabel another side's margin as this winner's.
    const valueMargin = data.winners_by_lens?.value === winner.user_id && data.margins_by_lens?.value != null
      ? fmtLensMargin("value", data.margins_by_lens.value)
      : null;
    return valueMargin ? `${base}, ${valueMargin} Trade Value` : base;
  }
  return `${when} — ${nameOf(a.user_id)} vs ${nameOf(b.user_id)}: ${ptsPair(a, b)}`;
}
