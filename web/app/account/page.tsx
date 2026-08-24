"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { signOut } from "next-auth/react";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { Button } from "@/components/furniture/Button";
import { IndeterminateBar } from "@/components/furniture/IndeterminateBar";
import { StateMessage } from "@/components/furniture/StateMessage";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";
import {
  getMe,
  linkSleeper,
  myLeagues,
  removeLeague,
  unlinkSleeper,
  type MeProfile,
  type MyLeague,
} from "@/lib/api";

export default function AccountPage() {
  const [me, setMe] = useState<MeProfile | null>(null);
  const [leagues, setLeagues] = useState<MyLeague[]>([]);
  const [username, setUsername] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [m, l] = await Promise.all([getMe(), myLeagues()]);
      setMe(m);
      setLeagues(l);
      setUsername(m.sleeper_username ?? "");
    } catch {
      setError("Failed to load your account.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function link(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setMe(await linkSleeper(username.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't link Sleeper.");
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    setBusy(true);
    setError(null);
    try {
      setMe(await unlinkSleeper());
      setUsername("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't unlink.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(leagueId: string) {
    try {
      await removeLeague(leagueId);
      setLeagues((cur) => cur.filter((l) => l.league_id !== leagueId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't remove league.");
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
        <h1 className="mt-3 font-display text-lead font-extrabold tracking-[-0.03em]">Account</h1>

        {error && (
          <StateMessage className="mt-6" tone="negative" kicker="Account error" headline={error} />
        )}
        {loading && <IndeterminateBar className="mt-6 max-w-[220px]" label="Loading account" />}

        {!loading && me && (
          <>
            <Card className="mt-6">
              <CardHead title="Profile" />
              <Panel>
                <Row cols="minmax(0,1fr) auto">
                  <span className="text-label uppercase tracking-[0.1em]">
                    Signed in as
                  </span>
                  <span className="truncate">{me.email}</span>
                </Row>
              </Panel>
            </Card>

            <Card>
              <CardHead title="Sleeper account" />
              {me.sleeper_username ? (
                <Panel>
                  <Row cols="minmax(0,1fr) auto">
                    <span className="truncate">
                      <span className="text-label uppercase tracking-[0.1em]">
                        Linked to{" "}
                      </span>
                      <span>{me.sleeper_username}</span>
                    </span>
                    <button
                      type="button"
                      onClick={unlink}
                      disabled={busy}
                      className="text-label uppercase tracking-[0.1em] hover:text-ink disabled:text-rule"
                    >
                      Unlink
                    </button>
                  </Row>
                </Panel>
              ) : (
                <form onSubmit={link} className="flex items-end gap-3">
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
                    disabled={busy || !username.trim()}
                    className="px-4 py-2 disabled:bg-rule disabled:text-dim"
                  >
                    {busy ? "Linking…" : "Link"}
                  </Button>
                </form>
              )}
              <p className="mt-2 max-w-[52ch] text-prose leading-relaxed text-body">
                Linking lets us prefill your leagues and mark which roster is yours. It&apos;s for
                personalization only.
              </p>
            </Card>

            <Card>
              <CardHead title="Your leagues" />
              {leagues.length === 0 ? (
                <p className="text-prose leading-relaxed text-body">
                  Leagues you add show up here.{" "}
                  <Link href="/leagues/add" className="underline hover:text-ink">
                    Add one
                  </Link>
                  .
                </p>
              ) : (
                <Panel>
                  {leagues.map((l) => (
                    <Row
                      key={l.league_id}
                      cols="minmax(0,1fr) 60px"
                    >
                      <Link
                        href={`/league/${l.league_id}`}
                        className="truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink hover:underline"
                      >
                        {l.name ?? `League ${l.league_id}`}
                      </Link>
                      <button
                        type="button"
                        onClick={() => remove(l.league_id)}
                        className="text-right text-label uppercase tracking-[0.1em] hover:text-neg-strong"
                      >
                        Remove
                      </button>
                    </Row>
                  ))}
                </Panel>
              )}
            </Card>

            <button
              type="button"
              onClick={() => signOut({ callbackUrl: "/login" })}
              className="mt-2 border-t border-rule pt-2 font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink"
            >
              Sign out
            </button>
          </>
        )}
      </section>
    </Shell>
  );
}
