"use client";

import { Fragment } from "react";
import { H2H, SeasonResult, TrackRecord } from "@/lib/types";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { Card, CardHead } from "./ui";
import { ordinal } from "./util";
import { SideBetsCard } from "./SideBetsCard";

/* ---------------------------------------------------------------------------
 * Agate — Track record (design_handoff_agate/DESIGN.md § "Two-rule entries";
 * CLAUDE_CODE.md § Commit 6; Agate System.dc.html Fig. 6.2). Season rows are
 * two rules (year + outcome, then the regular-season standing that set the
 * seed); head-to-head rows get a square split bar — ink for wins, empty for
 * losses, 1px ink outline, zero radius — plus the ledger and margin per game.
 * Opponent names render as plain Archivo text, not OwnerLabel's avatar +
 * name: the drawn page has no avatars anywhere (OwnerLabel's square-26px
 * rebuild is Commit 7's job), so this matches Fig. 6.2 exactly rather than
 * pulling an unported, rounded-avatar component onto a newly ruled page.
 * `SideBetsCard` renders inside this tab and is untouched (decision-3 scope
 * fence).
 * ------------------------------------------------------------------------ */

/** How the season actually ended — the headline verdict. Covers the winners
 *  bracket (champion → placement), the losers/toilet bracket, and missing the
 *  playoffs entirely, so the outcome is never silent about a toilet-bowl run.
 *  Only the champion's ink is toned pos — DESIGN.md § "The Signed Number"
 *  reserves color for signed values and grade letters; a championship is
 *  close enough to a grade (the season's own verdict) to earn it, but a
 *  runner-up or a made-playoffs finish stays plain ink. */
function outcomeLabel(s: SeasonResult): { text: string; tone: string } {
  if (s.champion) return { text: "🏆 Champion", tone: "text-pos-strong" };
  if (s.runner_up) return { text: "🥈 Runner-up", tone: "text-ink" };
  if (s.made_playoffs) {
    return {
      text: s.playoff_place ? `${ordinal(s.playoff_place)} in playoffs` : "Made playoffs",
      tone: "text-ink",
    };
  }
  if (s.made_toilet) {
    return {
      text: s.toilet_place ? `🚽 ${ordinal(s.toilet_place)} in Toilet Bowl` : "🚽 Toilet Bowl",
      tone: "text-dim",
    };
  }
  return { text: "Missed playoffs", tone: "text-dim" };
}

function SeasonRows({ s }: { s: SeasonResult }) {
  const o = outcomeLabel(s);
  const record = `${s.wins}-${s.losses}${s.ties ? `-${s.ties}` : ""}`;
  return (
    <>
      <Row className="grid-cols-[34px_minmax(0,1fr)] gap-2.5 ">
        <span className="font-mono text-figure font-semibold tabular text-dim">{`'${String(s.season).slice(2)}`}</span>
        <span className={`font-display text-figure font-bold tracking-[-0.02em] ${o.tone}`}>{o.text}</span>
      </Row>
      <Row className="grid-cols-[34px_minmax(0,1fr)] gap-2.5 ">
        <span />
        <span className="font-mono text-dim tabular">
          {ordinal(s.rank)} of {s.of} in reg. season · {record}
        </span>
      </Row>
    </>
  );
}

/** Square split bar: ink segment for wins, empty for losses — 1px ink
 *  outline, zero radius. */
function SplitBar({ winPct }: { winPct: number }) {
  return (
    <div className="hidden min-[701px]:flex h-2 border border-ink" aria-hidden="true">
      <div className="bg-ink" style={{ width: `${Math.round(winPct * 100)}%` }} />
      <div className="flex-1" />
    </div>
  );
}

function H2HRow({ h }: { h: H2H }) {
  const games = h.wins + h.losses + h.ties;
  const winPct = games ? h.wins / games : 0;
  const ledger = `${h.wins}-${h.losses}${h.ties ? `-${h.ties}` : ""}`;
  const up = h.wins > h.losses;
  const even = h.wins === h.losses;
  // Average scoring margin per meeting — surfaces how lopsided a rivalry is
  // beyond the win/loss ledger (a 6-6 split can still be a beatdown on points).
  const marginPg = games ? (h.points_for - h.points_against) / games : 0;
  const marginText = `${marginPg >= 0 ? "+" : "-"}${Math.abs(marginPg).toFixed(1)}`;
  return (
    <Row
      className="grid-cols-[minmax(0,1fr)_52px_60px] min-[701px]:grid-cols-[minmax(0,1fr)_84px_52px_60px] gap-3 items-center"
    >
      <span className="min-w-0 truncate font-display text-figure font-bold tracking-[-0.02em]">
        {h.opponent.owner_name}
      </span>
      <SplitBar winPct={winPct} />
      <span className={`text-right font-mono text-figure font-semibold tabular ${up ? "text-pos-strong" : even ? "text-dim" : "text-neg-strong"}`}>
        {ledger}
      </span>
      <span
        className={`text-right font-mono text-figure tabular ${marginPg > 0 ? "text-pos-strong" : marginPg < 0 ? "text-neg-strong" : "text-dim"}`}
        title="Average scoring margin per meeting"
      >
        {marginText}<span className="text-dim"> pg</span>
      </span>
    </Row>
  );
}

export function TrackRecordTab({
  trackRecord, headToHead, leagueId, userId,
}: { trackRecord?: TrackRecord; headToHead?: H2H[]; leagueId: string; userId: string }) {
  const tr = trackRecord;
  // Sort rivalries best-record-first (win rate, then sample size) so the rail
  // reads top-down from "owns this matchup" to "owned by it."
  const h2h = [...(headToHead ?? [])].sort((a, b) => {
    const ga = a.wins + a.losses + a.ties;
    const gb = b.wins + b.losses + b.ties;
    const pa = ga ? a.wins / ga : 0;
    const pb = gb ? b.wins / gb : 0;
    if (pb !== pa) return pb - pa;
    return gb - ga;
  });
  const seasons = tr ? [...tr.seasons].sort((a, b) => b.season - a.season) : [];

  return (
    <div>
      <Card>
        <CardHead
          title="Season by season"
          right={tr ? (
            <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
              {tr.titles > 0 ? `${tr.titles} 🏆 · ` : ""}{tr.playoff_appearances} playoff trips
            </span>
          ) : undefined}
        />
        {seasons.length === 0 ? (
          <p className="text-figure leading-relaxed text-body">
            Each finished season lands here with its record, seed, and finish.
          </p>
        ) : (
          <Panel>
            {seasons.map((s) => <Fragment key={s.season}><SeasonRows s={s} /></Fragment>)}
          </Panel>
        )}
      </Card>

      <Card>
        <CardHead title="Head to head" right={<span className="font-mono text-label uppercase tracking-[0.11em] text-dim">all-time reg. season · by win rate</span>} />
        {h2h.length === 0 ? (
          <p className="text-figure leading-relaxed text-body">
            The all-time record against every league-mate appears here after the first matchup.
          </p>
        ) : (
          <Panel>
            {h2h.map((h) => <H2HRow key={h.opponent.user_id} h={h} />)}
          </Panel>
        )}
      </Card>

      <SideBetsCard leagueId={leagueId} userId={userId} />
    </div>
  );
}
