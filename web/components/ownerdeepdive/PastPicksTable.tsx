"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import type { DraftPickResult } from "@/lib/types";
import { InfoTooltip } from "@/components/InfoTooltip";
import { SegmentControl } from "@/components/SegmentControl";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { Stat } from "./ui";
import { flattenAllTime, columnTotals, ALL_TIME } from "./pastPicks";
import { ordinal } from "./util";
import { startPct } from "@/lib/start-rate";

/* ---------------------------------------------------------------------------
 * Agate — how past picks panned out (DESIGN.md § "Nothing Is Fixed" +
 * § "The Ledger Is The Layout").
 *
 * The frozen Player column, its scroll-edge paint mask, the `scrolled` state
 * that drove it, the horizontal scroll region, and the "swipe →" hint are all
 * retired. Every applicable column ships in full: one rule per pick at
 * ≥1024px, and below that each pick wraps onto labelled rules of three — the
 * pattern TradesTab already uses for its mobile entries. Nothing is dropped and
 * nothing scrolls sideways.
 *
 * Two column groups are conditional, per the redraft-Outlook precedent
 * ("omit, don't blank" — an all-zero or all-null column reads as data, not
 * absence):
 *   - The value-arc columns (Current/Lowest/Highest/vs Slot) render for
 *     DYNASTY only. This is a question about the league, so it asks the
 *     league: `format`, off the response. The old zero-value heuristic
 *     assumed redraft had no player values, and it does — grader_io fetches
 *     FantasyCalc's redraft set, most of a 180-pick class matches, and the
 *     columns rendered with a "Today's dynasty market value" tooltip over
 *     Lowest/Highest read out of a `snapshots-redraft/` namespace days old
 *     at best. Keeper is out for the same reason the design matrix omits it.
 *   - The ADP / ADP +/- columns show only when at least one row carries a
 *     non-null `adp` — an unmatched pick is *ungraded* on this baseline, not
 *     a zero, so a null value renders "—" and is never coerced.
 * ------------------------------------------------------------------------ */

const val = (n: number): string => Math.round(n).toLocaleString();
const pts = (n: number): string => n.toFixed(1);

function Delta({ n }: { n: number }) {
  const r = Math.round(n);
  const tone = r > 0 ? "text-pos-strong" : r < 0 ? "text-neg-strong" : "text-dim";
  const sign = r > 0 ? "+" : "";
  return <span className={tone}>{`${sign}${r.toLocaleString()}`}</span>;
}

/** Null survives as "—", never coerced to 0 — an unmatched pick is ungraded
 *  on the ADP baseline, not a zero. */
function Adp({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-dim">—</span>;
  return <span>{value.toFixed(1)}</span>;
}

function AdpDelta({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-dim">—</span>;
  const tone = value > 0 ? "text-pos-strong" : value < 0 ? "text-neg-strong" : "text-dim";
  const sign = value > 0 ? "+" : "";
  return <span className={tone}>{`${sign}${value.toFixed(1)}`}</span>;
}

/** Share of Total Points that came from the starting lineup. Em-dash when
 *  there's nothing sound to divide — a zero OR NEGATIVE total (a K/DEF pick
 *  can score negative in a started week). Shared with `DraftBoard.tsx`'s
 *  `StartPct` and `DraftPicksMobile.tsx` via `web/lib/start-rate.ts`,
 *  mirroring `start_rate.py`'s `total > 0` gate — the previous per-file
 *  `!total` gate let a negative total slip through. */
function StartPct({ started, total }: { started?: number; total?: number }) {
  const pct = startPct(started, total);
  if (pct == null) return <span className="text-dim">—</span>;
  return <span>{pct}</span>;
}

/** A pick's current standing for the drafting owner. Mono uppercase text — a
 *  category is not a bordered chip, and the tone rides the word only because
 *  the word *is* the status here (rostered/dropped is a verdict, not a label
 *  on a figure). A kept pick appends a dim "Keeper" marker on the same line —
 *  never a second line, which would paint outside the 26px ruled row. */
const STATUS_META: Record<DraftPickResult["roster_status"], { label: string; cls: string }> = {
  rostered: { label: "Rostered", cls: "text-pos-strong" },
  traded: { label: "Traded", cls: "text-dim" },
  dropped: { label: "Dropped", cls: "text-neg-strong" },
};

function Status({ status, isKeeper }: { status: DraftPickResult["roster_status"]; isKeeper?: boolean }) {
  const m = STATUS_META[status] ?? STATUS_META.dropped;
  return (
    <span className="whitespace-nowrap">
      <span className={`font-mono text-label uppercase tracking-[0.11em] ${m.cls}`}>{m.label}</span>
      {isKeeper && (
        <span className="ml-1 font-mono text-label uppercase tracking-[0.11em] text-dim">· Keeper</span>
      )}
    </span>
  );
}

/** Hit/Average/Bust as coloured mono text, never a chip — the same licence
 *  `Status` above runs on: the word carries the meaning, the colour only
 *  restates it. An em-dash for a pick that carries no verdict (unranked,
 *  keeper, auction, or too-thin a cohort cell), even on a season where the
 *  column itself is showing — a blank verdict is never a guess. */
const VERDICT_META: Record<string, { label: string; cls: string }> = {
  hit: { label: "Hit", cls: "text-pos-strong" },
  average: { label: "Average", cls: "text-dim" },
  bust: { label: "Bust", cls: "text-neg-strong" },
};

function Verdict({ value }: { value?: string }) {
  const m = value ? VERDICT_META[value] : undefined;
  if (!m) return <span className="text-dim">—</span>;
  return <span className={`font-mono text-label uppercase tracking-[0.11em] ${m.cls}`}>{m.label}</span>;
}

// Head (always) + value-arc (conditional) + adp (conditional) + verdict
// (conditional) + tail (always). Eight literal grid templates — one per
// combination of the three independent gates — so Tailwind's static scan can
// find each complete arbitrary-value class in source text; an interpolated
// template silently loses its columns in a production build while every test
// passes. Verdict sits right after vs Slot/ADP +/- and before Total, matching
// `DraftBoard.tsx`'s column order (baseline, its delta, Verdict, Total
// Points). Tail is Total, Start %, Reg, Playoff, Toilet, GS — the same order
// the board uses.
//
// The Player track is capped (`minmax(150px,360px)`, not `minmax(0,1fr)`) —
// the same fix `DraftBoard.tsx`'s Picks/Owners tables carry, for the same
// reason: an uncapped `fr` track absorbs every px of row slack, and at a wide
// viewport (this table lives in the same `Shell`-wrapped page, so it hits the
// identical ~1116px panel width at 1405px) that stranded the value-arc/ADP/
// production columns several hundred px from the player name. Capped, slack
// collects at the row's right edge instead. 360px (vs. the board's 420px) —
// this table carries more fixed columns at its own narrower `lg:` (1024px)
// gate, so the ceiling is tighter; the floor (150px) still clears a real
// drafted player's name + position comfortably.
const GRID_MIN =
  "grid-cols-[minmax(150px,360px)_30px_58px_80px_50px_46px_46px_52px_50px_28px]";
const GRID_VALUE_ONLY =
  "grid-cols-[minmax(150px,360px)_30px_58px_80px_54px_50px_50px_56px_50px_46px_46px_52px_50px_28px]";
const GRID_ADP_ONLY =
  "grid-cols-[minmax(150px,360px)_30px_58px_80px_44px_46px_50px_46px_46px_52px_50px_28px]";
const GRID_BOTH =
  "grid-cols-[minmax(150px,360px)_30px_58px_80px_54px_50px_50px_56px_44px_46px_50px_46px_46px_52px_50px_28px]";
const GRID_VERDICT_ONLY =
  "grid-cols-[minmax(150px,360px)_30px_58px_80px_66px_50px_46px_46px_52px_50px_28px]";
const GRID_VALUE_VERDICT =
  "grid-cols-[minmax(150px,360px)_30px_58px_80px_54px_50px_50px_56px_66px_50px_46px_46px_52px_50px_28px]";
const GRID_ADP_VERDICT =
  "grid-cols-[minmax(150px,360px)_30px_58px_80px_44px_46px_66px_50px_46px_46px_52px_50px_28px]";
const GRID_ALL =
  "grid-cols-[minmax(150px,360px)_30px_58px_80px_54px_50px_50px_56px_44px_46px_66px_50px_46px_46px_52px_50px_28px]";

function gridFor(showValueArc: boolean, hasAdp: boolean, hasVerdicts: boolean): string {
  if (showValueArc && hasAdp && hasVerdicts) return GRID_ALL;
  if (showValueArc && hasAdp) return GRID_BOTH;
  if (showValueArc && hasVerdicts) return GRID_VALUE_VERDICT;
  if (showValueArc) return GRID_VALUE_ONLY;
  if (hasAdp && hasVerdicts) return GRID_ADP_VERDICT;
  if (hasAdp) return GRID_ADP_ONLY;
  if (hasVerdicts) return GRID_VERDICT_ONLY;
  return GRID_MIN;
}

/** Candid counting sentence, leading with the actual tally: hits (beat slot
 *  avg) vs misses across all picks. Third person — this page is almost always
 *  someone reading about a league-mate's franchise, not their own. Reads over
 *  every season regardless of which one the table below is currently showing
 *  — it summarizes the owner's whole draft history, not just the active tab,
 *  so it stays put (does not flicker) as the season selector changes. Moved
 *  here verbatim from the old FutureDraftTab home — same wording, same tests. */
function verdictSentence(bySeason: Record<string, DraftPickResult[]>, ownerName: string): string {
  const all = Object.values(bySeason).flat();
  if (all.length === 0) return "Not enough draft history yet to judge.";
  const hits = all.filter((p) => p.current_value - p.avg_slot_value > 0).length;
  const misses = all.length - hits;
  let bestSeason = "";
  let bestHits = -1;
  for (const [s, rows] of Object.entries(bySeason)) {
    const h = rows.filter((p) => p.current_value - p.avg_slot_value > 0).length;
    if (h > bestHits) { bestHits = h; bestSeason = s; }
  }
  const tail = bestHits > 0 ? ` ${bestSeason} was the strongest class.` : "";
  if (hits > misses) {
    return `${hits} of ${ownerName}'s ${all.length} picks beat their draft slot.${tail}`;
  }
  if (misses > hits) {
    return `${misses} of ${ownerName}'s ${all.length} picks missed their draft slot.${tail}`;
  }
  return `${ownerName}'s picks are split ${hits}-${misses} between beating and missing their draft slot.${tail}`;
}

/** Chunk a flat list of labelled mobile stats into rows of three. The last
 *  row is padded with empty cells so `grid-cols-3` stays aligned. */
function chunk3<T>(items: T[]): (T | null)[][] {
  const out: (T | null)[][] = [];
  for (let i = 0; i < items.length; i += 3) {
    const group: (T | null)[] = items.slice(i, i + 3);
    while (group.length < 3) group.push(null);
    out.push(group);
  }
  return out;
}

export function PastPicksTable({
  bySeason, ownerName, format, leagueId,
}: {
  bySeason: Record<string, DraftPickResult[]>;
  /** Third-person label for the GS / Total Pts tooltips. Falls back to
   *  "the owner" when the caller doesn't have a name in scope. */
  ownerName?: string;
  /** League format ("dynasty" | "keeper" | "redraft"). Only dynasty has the
   *  price history the value-arc columns describe. Defaults to dynasty, which
   *  is what a pre-capabilities cache reads back as. */
  format?: string;
  /** Enables the link out to the league-wide board for the selected season.
   *  Omitted when the caller has no league in scope. */
  leagueId?: string;
}) {
  const who = ownerName ?? "the owner";
  // verdictSentence's own third-person fallback — kept distinct from `who`
  // above (used for tooltip prose) to preserve its original exact wording.
  const verdictWho = ownerName ?? "This owner";
  const seasons = Object.keys(bySeason).sort().reverse(); // most recent first

  // Opens on All-Time: the question this table answers is "can this owner
  // draft", which is a career question, and a single class is the drill-down.
  // (The year run leads with All-Time too, matching the dashboard's year line
  // rather than the ratings board's ascending one.)
  const [active, setActive] = useState<string>(ALL_TIME);

  if (seasons.length === 0) {
    return (
      <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">
        No completed drafts yet
      </div>
    );
  }

  const tabs = [ALL_TIME, ...seasons];
  const rows = active === ALL_TIME ? flattenAllTime(bySeason) : (bySeason[active] ?? []);
  const totals = columnTotals(rows);
  const showValueArc = (format ?? "dynasty") === "dynasty";
  const hasAdp = rows.some((r) => r.adp != null);
  const hasVerdicts = rows.some((r) => r.verdict);
  const GRID = gridFor(showValueArc, hasAdp, hasVerdicts);

  type MobileEntry = { label: string; value: ReactNode };
  const pickEntries = (r: DraftPickResult): MobileEntry[] => [
    { label: "Rnd", value: ordinal(r.round) },
    { label: "Via", value: r.acquired_via_trade ? "Trade" : "Draft" },
    { label: "Now", value: <Status status={r.roster_status} isKeeper={r.is_keeper} /> },
    ...(showValueArc
      ? [
          { label: "Low", value: val(r.lowest_value) },
          { label: "High", value: val(r.highest_value) },
          { label: "vs Slot", value: <Delta n={r.current_value - r.avg_slot_value} /> },
        ]
      : []),
    ...(hasAdp
      ? [
          { label: "ADP", value: <Adp value={r.adp} /> },
          { label: "ADP +/-", value: <AdpDelta value={r.adp_delta} /> },
        ]
      : []),
    ...(hasVerdicts ? [{ label: "Verdict", value: <Verdict value={r.verdict} /> }] : []),
    // When there's no value arc, the headline figure already is Total Points —
    // don't repeat it in the wrapped cells below.
    ...(showValueArc ? [{ label: "Total", value: pts(r.production_total) }] : []),
    { label: "Start %", value: <StartPct started={r.production_started} total={r.production_total} /> },
    { label: "Reg", value: pts(r.production_regular) },
    { label: "Playoff", value: pts(r.production_playoff) },
    { label: "Toilet", value: pts(r.production_toilet) },
    { label: "GS", value: r.games_started },
  ];
  const totalEntries: MobileEntry[] = [
    ...(showValueArc
      ? [
          { label: "Low", value: val(totals.lowest_value) },
          { label: "High", value: val(totals.highest_value) },
          { label: "vs Slot", value: <Delta n={totals.deltaSum} /> },
          { label: "Total", value: pts(totals.production_total) },
        ]
      : []),
    { label: "Start %", value: <StartPct started={totals.production_started} total={totals.production_total} /> },
    { label: "Reg", value: pts(totals.production_regular) },
    { label: "Playoff", value: pts(totals.production_playoff) },
    { label: "Toilet", value: pts(totals.production_toilet) },
    { label: "GS", value: totals.games_started },
  ];

  return (
    <div>
      <p className="mb-3 max-w-[68ch] text-prose leading-relaxed text-body">
        {verdictSentence(bySeason, verdictWho)}
      </p>
      <div className="mb-3 flex flex-wrap items-center gap-1">
        <SegmentControl<string>
          aria-label="Filter picks by draft season"
          options={tabs.map((s) => ({ key: s, label: s === ALL_TIME ? "All-Time" : s }))}
          value={active}
          onChange={setActive}
        />
        {/* Out to the whole class. This owner's rows only answer "how did MY
            picks do" — the board answers "how did everyone's". Plain mono
            link, the same affordance the draft page's own back link uses; no
            second button fill. All-Time spans classes and has no one board. */}
        {leagueId && active !== ALL_TIME && (
          <Link
            href={`/league/${leagueId}/draft/${active}`}
            className="ml-auto font-mono text-figure uppercase tracking-[0.1em] text-dim underline hover:text-ink"
          >
            {active} draft board →
          </Link>
        )}
      </div>

      {/* Desktop — every applicable column on one rule per pick. */}
      <div className="hidden lg:block">
        <Panel role="table" aria-label="Past picks">
          <Row
            role="row"
            className={`${GRID} gap-2 font-mono text-label uppercase tracking-[0.11em] text-dim`}
          >
            <div role="columnheader">Player</div>
            <div role="columnheader">Rnd</div>
            <div role="columnheader">Acquired</div>
            <div role="columnheader">Status</div>
            {showValueArc && (
              <>
                <div role="columnheader" className="text-right">
                  Current <InfoTooltip title="Current Value" body="Today's dynasty market value." align="right" />
                </div>
                <div role="columnheader" className="text-right">
                  Lowest <InfoTooltip title="Lowest Value" body="Lowest value this player has hit since we began tracking (May 2026). Shows where the arc bottomed out." align="right" />
                </div>
                <div role="columnheader" className="text-right">
                  Highest <InfoTooltip title="Highest Value" body="Highest value this player has hit since we began tracking (May 2026). Shows the arc's peak." align="right" />
                </div>
                <div role="columnheader" className="text-right">
                  vs Slot <InfoTooltip title="vs Slot" body="How this pick's current value compares to what a typical player taken at this slot is worth. Positive means it outperformed its draft position." align="right" />
                </div>
              </>
            )}
            {hasAdp && (
              <>
                <div role="columnheader" className="text-right">
                  ADP <InfoTooltip title="ADP" body="Average draft position at the time of this draft. Blank when this player has no matched ADP." align="right" />
                </div>
                <div role="columnheader" className="text-right">
                  ADP +/- <InfoTooltip title="ADP +/-" body="Draft slot minus ADP. Positive means the pick was taken later than the market had him (value); negative means a reach." align="right" />
                </div>
              </>
            )}
            {hasVerdicts && (
              <div role="columnheader" className="text-right">
                Verdict <InfoTooltip title="Verdict" body="Hit, Average, or Bust — this pick's production measured against what players ranked the same actually scored. Blank when the pick has no rookie-consensus baseline to judge it against, or too few comparable picks to judge from." align="right" />
              </div>
            )}
            <div role="columnheader" className="text-right">
              Total <InfoTooltip title="Total Points" body={`Every point this player scored while on this roster — bench included, all weeks. Full production, whether or not ${who} started them.`} align="right" />
            </div>
            <div role="columnheader" className="text-right">
              Start % <InfoTooltip title="Start %" body={`Share of Total Points that ${who} actually started, across every week. Not the sum of Regular + Playoff + Toilet — a bye or placement week belongs to no phase.`} align="right" />
            </div>
            <div role="columnheader" className="text-right">
              Reg <InfoTooltip title="Regular Season Points" body="Started points in regular-season weeks while on this roster." align="right" />
            </div>
            <div role="columnheader" className="text-right">
              Playoff <InfoTooltip title="Playoff Points" body="Started points in real title-bracket games only." align="right" />
            </div>
            <div role="columnheader" className="text-right">
              Toilet <InfoTooltip title="Toilet Bowl Points" body="Started points in losers-bracket (consolation) games." align="right" />
            </div>
            <div role="columnheader" className="text-right">
              GS <InfoTooltip title="Games Started" body={`Number of weeks ${who} started this player while on the roster — all started weeks across every phase, including placement and consolation games that don't count toward the Playoff/Toilet point columns.`} align="right" />
            </div>
          </Row>

          {rows.map((r) => (
            <Row
              key={r.player_id}
              role="row"
              className={`${GRID} items-center gap-2 font-mono text-figure tabular`}
            >
              <div role="cell" className="min-w-0 truncate">
                <span className="font-display text-figure font-bold tracking-[-0.02em]">
                  {r.full_name}
                </span>
                <span className="ml-1.5 font-mono text-label uppercase tracking-[0.11em] text-dim">
                  {r.position}
                </span>
              </div>
              <div role="cell" className="text-figure text-dim">{ordinal(r.round)}</div>
              <div role="cell" className="text-label uppercase tracking-[0.11em] text-dim">
                {r.acquired_via_trade ? "Via Trade" : "Drafted"}
              </div>
              <div role="cell">
                <Status status={r.roster_status} isKeeper={r.is_keeper} />
              </div>
              {showValueArc && (
                <>
                  <div role="cell" className="text-right font-semibold">{val(r.current_value)}</div>
                  <div role="cell" className="text-right text-dim">{val(r.lowest_value)}</div>
                  <div role="cell" className="text-right text-dim">{val(r.highest_value)}</div>
                  <div role="cell" className="text-right">
                    <Delta n={r.current_value - r.avg_slot_value} />
                  </div>
                </>
              )}
              {hasAdp && (
                <>
                  <div role="cell" className="text-right"><Adp value={r.adp} /></div>
                  <div role="cell" className="text-right"><AdpDelta value={r.adp_delta} /></div>
                </>
              )}
              {hasVerdicts && (
                <div role="cell" className="text-right"><Verdict value={r.verdict} /></div>
              )}
              <div role="cell" className="text-right font-semibold">{pts(r.production_total)}</div>
              <div role="cell" className="text-right">
                <StartPct started={r.production_started} total={r.production_total} />
              </div>
              <div role="cell" className="text-right">{pts(r.production_regular)}</div>
              <div role="cell" className="text-right">{pts(r.production_playoff)}</div>
              <div role="cell" className="text-right">{pts(r.production_toilet)}</div>
              <div role="cell" className="text-right">{r.games_started}</div>
            </Row>
          ))}

          {/* The totals rule opens with a 2px ink rule — the band-closing
              counterpart to a band-opening one, and the only weight change.
              ADP has no meaningful roll-up, so its cells stay blank here —
              same treatment Rnd/Acquired/Status already get. */}
          <Row
            role="row"
            className={`${GRID} items-center gap-2 border-t-2 border-ink font-mono text-figure font-semibold tabular`}
          >
            <div role="cell" className="font-mono text-label uppercase tracking-[0.11em]">Total</div>
            <div role="cell" />
            <div role="cell" />
            <div role="cell" />
            {showValueArc && (
              <>
                <div role="cell" className="text-right">{val(totals.current_value)}</div>
                <div role="cell" className="text-right text-dim">{val(totals.lowest_value)}</div>
                <div role="cell" className="text-right text-dim">{val(totals.highest_value)}</div>
                <div role="cell" className="text-right">
                  <Delta n={totals.deltaSum} />
                </div>
              </>
            )}
            {hasAdp && (
              <>
                <div role="cell" />
                <div role="cell" />
              </>
            )}
            {hasVerdicts && <div role="cell" />}
            <div role="cell" className="text-right">{pts(totals.production_total)}</div>
            <div role="cell" className="text-right">
              <StartPct started={totals.production_started} total={totals.production_total} />
            </div>
            <div role="cell" className="text-right">{pts(totals.production_regular)}</div>
            <div role="cell" className="text-right">{pts(totals.production_playoff)}</div>
            <div role="cell" className="text-right">{pts(totals.production_toilet)}</div>
            <div role="cell" className="text-right">{totals.games_started}</div>
          </Row>
        </Panel>
      </div>

      {/* Below 1024px — each pick wraps onto labelled rules of three cells.
          Every applicable column above survives here; nothing scrolls
          sideways. */}
      <div className="lg:hidden">
        {rows.map((r) => (
          <div key={r.player_id} className="border-t border-rule">
            <Row className="grid-cols-[minmax(0,1fr)_72px] items-center gap-2 ">
              <span className="min-w-0 truncate">
                <span className="font-display text-figure font-bold tracking-[-0.02em]">
                  {r.full_name}
                </span>
                <span className="ml-1.5 font-mono text-label uppercase tracking-[0.11em] text-dim">
                  {r.position}
                </span>
              </span>
              <span className="text-right font-mono text-figure font-semibold tabular">
                {showValueArc ? val(r.current_value) : pts(r.production_total)}
              </span>
            </Row>
            {chunk3(pickEntries(r)).map((group, i) => (
              <Row key={i} className="grid-cols-3 items-center gap-x-3 ">
                {group.map((e, j) => (e ? <Stat key={j} label={e.label} value={e.value} /> : <div key={j} />))}
              </Row>
            ))}
          </div>
        ))}

        <div className="border-t border-rule">
          <Row className="grid-cols-[minmax(0,1fr)_72px] items-center gap-2 border-t-2 border-ink ">
            <span className="font-mono text-label font-bold uppercase tracking-[0.1em]">Total</span>
            <span className="text-right font-mono text-figure font-semibold tabular">
              {showValueArc ? val(totals.current_value) : pts(totals.production_total)}
            </span>
          </Row>
          {chunk3(totalEntries).map((group, i) => (
            <Row key={i} className="grid-cols-3 items-center gap-x-3 ">
              {group.map((e, j) => (e ? <Stat key={j} label={e.label} value={e.value} /> : <div key={j} />))}
            </Row>
          ))}
        </div>
      </div>
    </div>
  );
}
