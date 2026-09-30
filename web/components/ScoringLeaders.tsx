"use client";

import { useState } from "react";
import type { ScoringPlayer, ScoringResp } from "@/lib/scoring";
import { SegmentControl } from "./SegmentControl";
import { CardList, EntryCard, Meta, MetaLine } from "./furniture/EntryCard";
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";
import { StateMessage } from "./furniture/StateMessage";

const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"];
const COLS = "minmax(0, .7fr) minmax(0, 3fr) repeat(3, minmax(0, 1fr))";
const points = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function ScoringLeaders({ data }: { data: ScoringResp }) {
  const [position, setPosition] = useState(data.players.some(p => p.position === "WR") ? "WR" : "all");
  const [search, setSearch] = useState("");
  const positions = Array.from(new Set(data.players.map(p => p.position))).sort((a, b) => {
    const index = (p: string) => POSITIONS.includes(p) ? POSITIONS.indexOf(p) : POSITIONS.length;
    return index(a) - index(b) || a.localeCompare(b);
  });
  const ties = new Map<string, number>();
  data.players.forEach(p => {
    const key = `${p.position}${p.rank}`;
    ties.set(key, (ties.get(key) ?? 0) + 1);
  });
  const rankLabel = (p: ScoringPlayer) => {
    const rank = `${p.position}${p.rank}`;
    return `${rank}${(ties.get(rank) ?? 0) > 1 ? " · tied" : ""}`;
  };
  const rows = data.players.filter(p => (position === "all" || p.position === position)
    && p.name.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((a, b) => b.points - a.points || a.name.localeCompare(b.name));

  return <section>
    <div className="mb-5">
      <p className="font-mono text-label uppercase tracking-[0.1em] text-dim">{data.league_name} · {data.season}</p>
      <h1 className="mt-2 font-display text-lead font-extrabold text-ink">Scoring leaders</h1>
      {data.through_week > 0 && <p className="mt-2 text-prose text-body">
        Season scoring through Week {data.through_week} · Your league’s scoring
      </p>}
    </div>
    {data.through_week === 0 ? <StateMessage kicker="Season ahead" headline="Scoring starts after Week 1."
      body="Once the first week is complete, every player’s points and positional rank will appear here." /> : <>
      <div className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-5">
        <SegmentControl aria-label="Player position" value={position} onChange={setPosition}
          options={[{ key: "all", label: "All" }, ...positions.map(key => ({ key, label: key }))]} />
        <input type="search" aria-label="Find a player" placeholder="Find a player" value={search}
          onChange={e => setSearch(e.target.value)}
          className="min-h-tap min-w-0 max-w-full rounded-sm border border-rule-strong bg-surface px-3 text-prose text-ink" />
      </div>
      <p className="mb-4 text-prose text-dim">
        All players at your league’s positions, including bench players and free agents. Ranked by total points; ties share a rank.
      </p>
      {rows.length === 0 ? <StateMessage kicker="Player search" headline="Try another player or position."
        body="Players with a recorded game in the completed weeks appear here." /> : <>
        <Panel role="table" aria-label="Player scoring leaders" data-testid="scoring-table" className="hidden min-[701px]:block">
          <Row role="row" variant="head" cols={COLS}>
            <span role="columnheader">Rank</span><span role="columnheader">Player</span>
            <span role="columnheader" className="text-right">Total points</span>
            <span role="columnheader" className="text-right">Games</span>
            <span role="columnheader" className="text-right">Pts / game</span>
          </Row>
          {rows.map(p => <Row role="row" key={p.player_id} cols={COLS} className="py-2">
            <span role="cell" className="text-ink">{rankLabel(p)}</span>
            <span role="cell" className="min-w-0">
              <span className="block font-sans text-prose font-semibold text-ink">{p.name}</span>
              <span className="text-label">{p.team || "—"} · {p.position}</span>
            </span>
            <span role="cell" className="text-right font-semibold text-ink">{points(p.points)}</span>
            <span role="cell" className="text-right">{p.games}</span>
            <span role="cell" className="text-right">{points(p.points_per_game)}</span>
          </Row>)}
        </Panel>
        <CardList data-testid="scoring-cards" className="min-[701px]:hidden">
          {rows.map(p => <EntryCard key={p.player_id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-mono text-label text-dim">{rankLabel(p)}</p>
                <p className="mt-1 font-display text-body font-bold text-ink">{p.name}</p>
                <p className="mt-1 font-mono text-label text-dim">{p.team || "—"} · {p.position}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="font-mono text-section tabular-nums text-ink">{points(p.points)}</p>
                <p className="font-mono text-label uppercase text-dim">Total points</p>
              </div>
            </div>
            <MetaLine><Meta label="Games">{p.games}</Meta><Meta label="Pts / game">{points(p.points_per_game)}</Meta></MetaLine>
          </EntryCard>)}
        </CardList>
        <p className="mt-4 font-mono text-label text-dim">{rows.length} players · Points per game counts recorded games, including zero and negative scores.</p>
      </>}
      <p className="mt-4 text-prose text-dim">The current week is excluded until Sleeper advances to the next week. Reload to pick up newly completed weeks and stat corrections.</p>
    </>}
  </section>;
}
