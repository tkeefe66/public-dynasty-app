"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { Button } from "@/components/furniture/Button";
import { StateMessage } from "@/components/furniture/StateMessage";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { Name } from "@/components/furniture/Name";
import { addLeague, getMe, sleeperLeagues, type SleeperLeague } from "@/lib/api";

/**
 * Add a league. An input is a rule you type on, not a box: no fill, no
 * border, no radius, just `border-b border-rule` that goes to `--ink` on
 * focus. The results are a ledger on a solid `Panel` — one `Row` per league,
 * the row's own action as mono uppercase text (the stamp fill belongs to the
 * page's one primary button, not to twelve row buttons).
 */
export default function AddLeaguePage() {
  const router = useRouter();
  const [username, setUsername] = useState("");

  // Prefill from the linked Sleeper account, if any.
  useEffect(() => {
    getMe()
      .then((me) => {
        if (me.sleeper_username) setUsername(me.sleeper_username);
      })
      .catch(() => {});
  }, []);
  const [results, setResults] = useState<SleeperLeague[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    const u = username.trim();
    if (!u) return;
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      setResults(await sleeperLeagues(u));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setLoading(false);
    }
  }

  async function add(lg: SleeperLeague) {
    setAdding(lg.league_id);
    setError(null);
    try {
      await addLeague(lg.league_id, { name: lg.name });
      // The league cold-starts its refresh on first view (existing 409 → SSE flow).
      router.push(`/league/${lg.league_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add league");
      setAdding(null);
    }
  }

  return (
    <Shell>
      <TopBar />
      <section className="mt-8 max-w-2xl">
        <Link
          href="/"
          className="font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink"
        >
          ← My Leagues
        </Link>
        <h1 className="mt-3 font-display text-lead font-extrabold tracking-[-0.03em]">Add a league</h1>
        <p className="mt-2 max-w-[52ch] text-prose leading-relaxed text-body">
          Enter your Sleeper username to find your leagues.
        </p>

        <form onSubmit={search} className="mt-6 flex items-end gap-3">
          <label className="flex-1">
            <span className="block font-mono text-label uppercase tracking-[0.1em] text-dim">
              Sleeper username
            </span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="username"
              className="w-full border-b border-rule bg-transparent py-1.5 text-sm text-ink placeholder:text-dim focus:border-ink focus:outline-none"
            />
          </label>
          <Button
            as="button"
            type="submit"
            disabled={loading || !username.trim()}
            className="px-4 py-2 disabled:bg-rule disabled:text-dim"
          >
            {loading ? "Searching…" : "Find leagues"}
          </Button>
        </form>

        {error && (
          <StateMessage
            className="mt-8"
            tone="negative"
            kicker="Lookup failed"
            headline={error}
            body="Not you — us, unless the username is misspelled. Try it again."
          />
        )}

        {results && results.length === 0 && (
          <StateMessage
            className="mt-8"
            kicker="No leagues found"
            headline="No leagues on that username this season."
            body="Sleeper only returns leagues for the current season. Check the spelling, or try the username that owns the league."
          />
        )}

        {results && results.length > 0 && (
          <div className="mt-6">
            <Panel>
              <Row variant="head" cols="minmax(0,1fr) 70px 74px 60px">
                <div>League</div>
                <div className="text-right">Format</div>
                <div className="text-right">Teams</div>
                <div className="text-right">Add</div>
              </Row>
              {results.map((lg) => (
                <Row
                  key={lg.league_id}
                  cols="minmax(0,1fr) 70px 74px 60px"
                >
                  <span className="min-w-0 truncate">
                    <Name>
                      {lg.name}
                    </Name>
                    <span className="ml-1.5">{lg.season}</span>
                  </span>
                  <span className="text-right uppercase tracking-wide">
                    {lg.format}
                  </span>
                  <span className="text-right">
                    {lg.total_rosters}
                  </span>
                  {lg.already_imported ? (
                    <Link
                      href={`/league/${lg.league_id}`}
                      className="text-right text-label uppercase tracking-[0.1em] hover:text-ink"
                    >
                      Open →
                    </Link>
                  ) : (
                    <button
                      type="button"
                      onClick={() => add(lg)}
                      disabled={adding !== null}
                      className="text-right text-label font-bold uppercase tracking-[0.1em] hover:text-ink disabled:text-dim"
                    >
                      {adding === lg.league_id ? "Adding…" : "Add"}
                    </button>
                  )}
                </Row>
              ))}
            </Panel>
          </div>
        )}
      </section>
    </Shell>
  );
}
