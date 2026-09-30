"use client";

import { useId, useState } from "react";
import type { ScoringResp, ScoringRosterPlayer } from "@/lib/scoring";
import { SegmentControl } from "./SegmentControl";
import { Panel } from "./furniture/Panel";
import { StateMessage } from "./furniture/StateMessage";

const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"];
const POSITION_NAMES: Record<string, string> = {
  QB: "Quarterbacks", RB: "Running backs", WR: "Wide receivers", TE: "Tight ends", K: "Kickers", DEF: "Defenses",
};
const points = (value: number | null) => value === null ? "—" : value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const byPoints = (a: ScoringRosterPlayer, b: ScoringRosterPlayer) =>
  (b.points ?? -Infinity) - (a.points ?? -Infinity) || a.name.localeCompare(b.name);

function ScoringCard({ title, subtitle, players, ties, ownership, expandLabel, emptyLabel }: {
  title: string; subtitle: string; players: ScoringRosterPlayer[];
  ties: Map<string, number>; ownership?: Map<string, string>; expandLabel: string; emptyLabel: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  return <Panel role="region" aria-labelledby={`${id}-heading`} className="min-w-0 self-start">
    <div className="px-4 py-4">
      <h2 id={`${id}-heading`} className="break-words font-display text-section font-bold leading-tight text-ink">{title}</h2>
      <p className="mt-1 break-words font-mono text-label text-dim">{subtitle}</p>
    </div>
    <ul id={`${id}-players`} className="divide-y divide-rule border-t border-rule">
      {(expanded ? players : players.slice(0, 5)).map(player => {
        const rank = `${player.position}${player.rank}`;
        const tied = player.rank !== null && (player.tied ?? (ties.get(rank) ?? 0) > 1);
        return <li key={player.player_id} className="grid grid-cols-[3.25rem_minmax(0,1fr)_auto] items-start gap-x-2 px-3.5 py-3.5">
          <span className="pt-0.5 font-mono text-figure tabular-nums text-ink">
            {player.rank === null ? <span aria-label={`${player.position}, unranked`}>{player.position} —</span> : `${rank}${tied ? " · tied" : ""}`}
          </span>
          <div className="min-w-0">
            <p className="break-words text-prose font-semibold leading-snug text-ink">{player.name}</p>
            <p className="mt-1 break-words font-mono text-label leading-relaxed text-dim">
              {player.team || "No NFL team"} · {player.games} {player.games === 1 ? "game" : "games"}
              {player.rank === null && <span className="block">No games recorded</span>}
              {ownership && <span className="block">{ownership.get(player.player_id) || "Free agent"}</span>}
            </p>
          </div>
          <div className="text-right font-mono tabular-nums">
            <p className="text-prose font-semibold text-ink"><span className="sr-only">Total points </span>{points(player.points)}</p>
            {player.points_per_game !== null && <p className="mt-1 text-label text-dim">{points(player.points_per_game)} / gm</p>}
          </div>
        </li>;
      })}
    </ul>
    {players.length === 0 && <p className="px-4 py-5 text-prose text-dim">{emptyLabel}</p>}
    {players.length > 5 && <button type="button" aria-expanded={expanded} aria-controls={`${id}-players`}
      onClick={() => setExpanded(!expanded)}
      className="min-h-tap w-full border-t border-rule px-4 py-3 text-left text-prose font-medium text-ink hover:bg-surface-sunk focus-visible:outline-offset-[-4px]">
      {expanded ? "Show top five" : expandLabel}
    </button>}
  </Panel>;
}

export function ScoringLeaders({ data }: { data: ScoringResp }) {
  const [view, setView] = useState<"positions" | "franchises">("positions");
  const [position, setPosition] = useState("all");
  const [franchise, setFranchise] = useState("all");
  const [search, setSearch] = useState("");
  // Keep Positions readable during an API/Web rolling deployment.
  const franchises = data.franchises ?? [];
  const positionPool = view === "positions" ? data.players : franchises.flatMap(f => f.players);
  const positions = Array.from(new Set(positionPool.map(p => p.position))).sort((a, b) => {
    const index = (p: string) => POSITIONS.includes(p) ? POSITIONS.indexOf(p) : POSITIONS.length;
    return index(a) - index(b) || a.localeCompare(b);
  });
  const ownership = new Map<string, string>();
  const rosterIds = new Map<string, number>();
  franchises.forEach(f => f.players.forEach(p => {
    ownership.set(p.player_id, f.name);
    rosterIds.set(p.player_id, f.roster_id);
  }));
  const ties = new Map<string, number>();
  data.players.forEach(p => {
    const key = `${p.position}${p.rank}`;
    ties.set(key, (ties.get(key) ?? 0) + 1);
  });
  const query = search.trim().toLowerCase();
  const matches = (p: ScoringRosterPlayer) => (position === "all" || p.position === position) && p.name.toLowerCase().includes(query);
  const positionPlayers = data.players.filter(p => matches(p) && (franchise === "all" || String(rosterIds.get(p.player_id)) === franchise)).sort(byPoints);
  const teams = franchises.filter(f => franchise === "all" || String(f.roster_id) === franchise)
    .map(f => ({ ...f, filtered: f.players.filter(matches).sort(byPoints) }))
    .filter(f => !query || f.filtered.length > 0);
  const empty = view === "positions" ? positionPlayers.length === 0 : teams.length === 0;
  const reset = () => { setPosition("all"); setFranchise("all"); setSearch(""); };
  const changeView = (next: "positions" | "franchises") => {
    const pool = next === "positions" ? data.players : franchises.flatMap(f => f.players);
    if (!pool.some(p => p.position === position)) setPosition("all");
    setView(next);
  };
  const controlClass = "min-h-tap min-w-0 w-full rounded-sm border border-rule-strong bg-surface px-3 text-prose text-ink";

  return <section>
    <div className="mb-7 flex flex-wrap items-end justify-between gap-x-8 gap-y-6">
      <div>
        <h1 className="font-display text-lead font-extrabold text-ink">Scoring</h1>
        <p className="mt-2 text-prose text-dim">{data.league_name} · {data.season}{data.through_week > 0 && ` · Through Week ${data.through_week}`}</p>
      </div>
      <SegmentControl aria-label="Scoring view" value={view} onChange={changeView}
        options={[{ key: "positions", label: "Positions" }, { key: "franchises", label: "Franchises" }]}
        className="mb-2 [&_button]:font-sans [&_button]:text-prose [&_button]:normal-case [&_button]:tracking-normal" />
    </div>
    <div className="mb-6 flex flex-col gap-5 min-[900px]:flex-row min-[900px]:items-center min-[900px]:justify-between">
      <SegmentControl aria-label="Player position" value={position} onChange={setPosition}
        options={[{ key: "all", label: "All" }, ...positions.map(key => ({ key, label: key }))]} className="my-2" />
      <div className="grid min-w-0 grid-cols-1 gap-3 min-[480px]:grid-cols-2 min-[900px]:w-1/2">
        <select aria-label="Franchise" value={franchise} onChange={e => setFranchise(e.target.value)} className={controlClass}>
          <option value="all">All franchises</option>
          {franchises.map(f => <option key={f.roster_id} value={String(f.roster_id)}>{f.name}</option>)}
        </select>
        <input type="search" aria-label="Find a player" placeholder="Find a player" value={search}
          onChange={e => setSearch(e.target.value)} className={`${controlClass} placeholder:text-dim`} />
      </div>
    </div>
    <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
      <p className="text-prose text-body">{view === "positions" ? "Compare the leaders across positions." : "Compare each franchise’s highest-scoring players."}</p>
      <span className="font-mono text-label text-dim">Total points · Pts / game</span>
    </div>
    {view === "positions" && data.through_week === 0 ? <StateMessage kicker="Season ahead" headline="Scoring starts after Week 1."
      body="Current rosters are available in Franchises. Points and positional ranks appear once the first week is complete." />
    : view === "franchises" && !data.franchises ? <StateMessage kicker="Roster data" headline="Franchise rosters are unavailable."
      body="Reload to try again." />
    : empty ? <div>
      <StateMessage kicker="Player search" headline="No players match these filters." body="Try another name, position, or franchise." />
      <button type="button" onClick={reset} className="mt-3 min-h-tap text-prose text-ink underline underline-offset-4">Clear filters</button>
    </div> : <div data-testid="scoring-board" className="grid grid-cols-1 items-start gap-4 min-[701px]:grid-cols-2 min-[1100px]:grid-cols-3">
      {view === "positions" ? positions.map(pos => {
        const players = positionPlayers.filter(p => p.position === pos);
        return players.length > 0 && <ScoringCard key={`position-${pos}`} title={POSITION_NAMES[pos] || pos}
          subtitle={`${players.length} players · ${pos}`} players={players} ties={ties}
          ownership={data.franchises ? ownership : undefined} expandLabel={`Explore ${pos} rankings`} emptyLabel="" />;
      }) : teams.map(f => <ScoringCard key={`franchise-${f.roster_id}`} title={f.name}
        subtitle={`${f.owner_name || (f.owner_id ? "Unknown owner" : "Unclaimed franchise")} · ${f.players.length} players`}
        players={f.filtered} ties={ties} expandLabel={`View all ${f.filtered.length} players`}
        emptyLabel={f.players.length ? `No ${position === "all" ? "matching" : position} players on this roster.` : "No players on this roster."} />)}
    </div>}
    <p className="mt-6 text-prose leading-relaxed text-dim">
      Your league’s scoring. Ranks compare all players at each position, including free agents; ties share a rank.
      {view === "franchises" && " Current rosters; points cover the full season, including games before a player joined this franchise."}
      {" "}The current week is excluded. Points per game counts recorded games, including zero and negative scores.
    </p>
    <p className="mt-2 text-prose text-dim">Reload to pick up roster changes, newly completed weeks, and stat corrections.</p>
  </section>;
}
