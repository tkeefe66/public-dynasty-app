"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/furniture/Button";
import { addLeague, disconnectYahoo, yahooLeagues, yahooStatus, type SleeperLeague, type YahooStatus } from "@/lib/api";

export function YahooLeaguePicker() {
  const router = useRouter();
  const [connection, setConnection] = useState<YahooStatus | null>(null);
  const [leagues, setLeagues] = useState<SleeperLeague[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setLeagues([]);
    try {
      const status = await yahooStatus();
      setConnection(status);
      if (status.status === "connected") setLeagues(await yahooLeagues());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Yahoo leagues could not be loaded. Try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function add(league: SleeperLeague) {
    setAdding(league.league_id);
    setError(null);
    try {
      await addLeague(league.league_id, { name: league.name });
      router.push(`/league/${league.league_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The league could not be added. Try again.");
      setAdding(null);
    }
  }

  async function disconnect() {
    setLoading(true);
    setError(null);
    try {
      await disconnectYahoo();
      setConnection({ configured: true, status: "disconnected" });
      setLeagues([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Yahoo could not be disconnected. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-6">
      <p className="max-w-[52ch] text-prose leading-relaxed text-body">
        Connect your Yahoo account to find your football leagues. Access is read-only; your rosters and league settings stay under your control.
      </p>
      {loading && <p className="mt-6 text-body" role="status">Loading Yahoo leagues…</p>}
      {error && <p role="alert" className="mt-5 text-body">{error}</p>}
      {!loading && connection?.configured === false && (
        <p className="mt-6 text-body">Yahoo connection is being set up. Please try again after the app owner enables it.</p>
      )}
      {!loading && connection?.configured && (
        <div className="mt-6 flex flex-wrap items-center gap-5">
          {connection.status === "connected" && !error && <span className="font-mono text-label uppercase tracking-[0.1em] text-pos-strong">Yahoo connected</span>}
          <form action="/api/yahoo/connect" method="post">
            {connection.status === "connected" && !error ? <button type="submit" className="min-h-tap font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink">Change Yahoo account</button> : <Button as="button" type="submit" className="px-4 py-2">
              {connection.status === "disconnected" ? "Connect Yahoo" : "Reconnect Yahoo"}
            </Button>}
          </form>
          {connection.status === "connected" && (
            <>
              <button type="button" onClick={() => void load()} className="min-h-tap font-mono text-label uppercase tracking-[0.1em] hover:text-ink">Refresh leagues</button>
              <button type="button" onClick={() => void disconnect()} className="min-h-tap font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink">Disconnect</button>
            </>
          )}
        </div>
      )}
      {!loading && !connection && <button type="button" onClick={() => void load()} className="mt-5 underline">Try again</button>}
      {!loading && connection?.status === "reconnect" && <p className="mt-4 text-body">Your Yahoo authorization needs to be renewed. Reconnect to load your leagues.</p>}
      {!loading && !error && connection?.status === "connected" && leagues.length === 0 && (
        <p className="mt-8 text-body">No football leagues found for the current season. If you use another Yahoo account, reconnect with that account.</p>
      )}
      {!loading && leagues.length > 0 && (
        <ul className="mt-8 divide-y divide-rule border-y border-rule" aria-label="Yahoo leagues">
          {leagues.map((league) => (
            <li key={league.league_id} className="flex items-center justify-between gap-4 py-5">
              <div className="min-w-0">
                <p className="break-words font-display text-base font-bold text-ink">{league.name}</p>
                <p className="mt-1 font-mono text-label text-dim">{league.season} · {league.total_rosters} teams · {league.format === "keeper" ? "Keeper" : "Redraft"}</p>
              </div>
              {league.already_imported ? (
                <Link href={`/league/${league.league_id}`} aria-label={`Open ${league.name}`} className="inline-flex min-h-tap shrink-0 items-center py-3 font-mono text-label uppercase tracking-[0.1em] hover:text-ink">Open →</Link>
              ) : (
                <button type="button" aria-label={`Add ${league.name}`} disabled={adding !== null} onClick={() => void add(league)} className="min-h-tap shrink-0 py-3 font-mono text-label font-bold uppercase tracking-[0.1em] hover:text-ink disabled:text-dim">
                  {adding === league.league_id ? "Adding…" : "Add"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
