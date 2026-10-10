"use client";
import Link from 'next/link';
import { useState } from 'react';
import { Panel } from '@/components/furniture/Panel';
import { Row } from '@/components/furniture/Row';
import { DauBar } from './DauBar';
import type { AdminLeague, AdminUser, AdminActiveUsers, AdminBackupStatus } from '@/lib/api';
import styles from './AdminWorkspace.module.css';
function usd(n: number) {
  return n < 0.01 ? `$${n.toFixed(5)}` : `$${n.toFixed(2)}`;
}

function lastSeen(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function leagueType(format: string | null) {
  if (!format) return "—";
  return format.charAt(0).toUpperCase() + format.slice(1);
}

function leagueLink(lg: { league_id: string; name: string | null }) {
  return (
    <Link
      href={`/league/${lg.league_id}`}
      className="text-ink hover:underline"
    >
      {lg.name ?? `League ${lg.league_id}`}
    </Link>
  );
}

// `grid-template-columns` values, passed verbatim to `Row`'s `cols` prop —
// not Tailwind `grid-cols-[...]` classes (Row supplies `grid` itself).
const LEAGUE_COLS = "minmax(0,1fr) 68px 66px 54px 54px 86px 78px";
const USER_COLS = "minmax(0,1.4fr) minmax(0,1fr) 50px 86px 52px";

/** One labelled figure inside a wrapped phone entry. */
function AdminCell({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="flex min-w-0 items-baseline gap-1.5">
      <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-label uppercase tracking-[0.1em] text-dim">
        {label}
      </span>
      <span className="flex-none whitespace-nowrap">{value}</span>
    </span>
  );
}

/** Shared labelled-figure strip (overview + usage). Three bare columns of
 *  whisper label over a mono figure — no tiles, no boxes. */
function StatGrid({
  stats,
  className = "",
}: {
  stats: { label: string; value: number }[];
  className?: string;
}) {
  return (
    <div className={`grid grid-cols-3 gap-5 ${className}`}>
      {stats.map((s) => (
        <div key={s.label}>
          <div className="font-mono text-label uppercase tracking-[0.1em] text-dim">{s.label}</div>
          <div className="font-mono text-lead font-semibold tabular tracking-[-0.02em]">
            {s.value}
          </div>
        </div>
      ))}
    </div>
  );
}


export function BackupStatus({ backups }: { backups: AdminBackupStatus | null }) {
  return <details className={styles.backups}>
    <summary>Backups {backups ? (backups.last_error ? '· error' : backups.enabled ? '· on' : '· off') : '· unavailable'}</summary>
    <div><p>Last successful backup: {lastSeen(backups?.last_ok_at ?? null)}</p><p className={styles.run}>Run: {backups?.last_run_id ?? '—'}</p>{backups?.last_error && <p className="text-neg-strong">{backups.last_error}</p>}</div>
  </details>;
}
export function LeagueReport({ leagues: allLeagues }: { leagues: AdminLeague[] }) {
  const [query, setQuery] = useState('');
  const leagues = allLeagues.filter(league => [league.name, league.league_id, league.format, league.season].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  return <><div className={styles.reportHead}><div><h2>Leagues</h2><p>Membership, activity, and monthly spend.</p></div><label>Search leagues<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Name, season, or type" /></label></div>
        {leagues.length === 0 ? (
          <p className="mt-2 font-mono text-label uppercase tracking-[0.1em] text-dim">
            {query ? "No leagues match your search." : "No leagues imported yet"}
          </p>
        ) : (
          <div className="mt-3">
            {/* Desktop — six columns on one rule. */}
            <div className="hidden min-[701px]:block">
              <Panel>
                <Row cols={LEAGUE_COLS} variant="head">
                  <div>League</div>
                  <div className="text-right">Type</div>
                  <div className="text-right">Members</div>
                  <div className="text-right">Cache</div>
                  <div className="text-right">Active</div>
                  <div className="text-right">Last seen</div>
                  <div className="text-right">Spend (mo)</div>
                </Row>
                {leagues.map((lg) => (
                  <Row key={lg.league_id} cols={LEAGUE_COLS}>
                    <div className="min-w-0 truncate">
                      <Link href={`/league/${lg.league_id}`} className="hover:underline">
                        {lg.name ?? `League ${lg.league_id}`}
                      </Link>
                      {lg.season ? <span className="text-dim"> · {lg.season}</span> : null}
                    </div>
                    <div className="text-right text-label uppercase tracking-[0.1em] text-dim">
                      {leagueType(lg.format)}
                    </div>
                    <div className="text-right">{lg.member_count}</div>
                    <div className="text-right text-label uppercase tracking-[0.1em] text-dim">
                      {lg.warm ? "warm" : "cold"}
                    </div>
                    <div className="text-right">{lg.active_users}</div>
                    <div className="whitespace-nowrap text-right text-dim">{lastSeen(lg.last_activity)}</div>
                    <div className="text-right">{usd(lg.spend_mtd_usd)}</div>
                  </Row>
                ))}
              </Panel>
            </div>
            {/* Phone — each league is its own ledger card. Every column stays. */}
            <div className="min-[701px]:hidden space-y-2.5">
              {leagues.map((lg) => (
                <Panel key={lg.league_id}>
                  <Row cols="minmax(0,1fr) auto">
                    <Link href={`/league/${lg.league_id}`} className="min-w-0 truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink hover:underline">
                      {lg.name ?? `League ${lg.league_id}`}
                    </Link>
                    <span className="text-label uppercase tracking-[0.1em] text-dim">
                      {lg.warm ? "warm" : "cold"}
                    </span>
                  </Row>
                  <Row cols="repeat(2, minmax(0,1fr))">
                    <AdminCell label="Type" value={leagueType(lg.format)} />
                    <AdminCell label="Members" value={lg.member_count} />
                  </Row>
                  <Row cols="repeat(2, minmax(0,1fr))">
                    <AdminCell label="Active" value={lg.active_users} />
                    <AdminCell label="Last seen" value={lastSeen(lg.last_activity)} />
                  </Row>
                  <Row cols="minmax(0,1fr)">
                    <AdminCell label="Spend" value={usd(lg.spend_mtd_usd)} />
                  </Row>
                </Panel>
              ))}
            </div>
          </div>
        )}

</>;
}
export function UserReport({ users: allUsers, activeUsers, memberships }: { users: AdminUser[]; activeUsers: AdminActiveUsers; memberships: number }) {
  const [query, setQuery] = useState('');
  const users = allUsers.filter(user => [user.name, user.email, ...user.leagues.map(league => league.name)].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  return <><div className={styles.reportHead}><div><h2>Users</h2><p>{allUsers.length} users · {memberships} memberships across your leagues.</p></div><label>Search users<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Name, email, or league" /></label></div>
  {!users.length && <p className="py-6 text-prose text-dim">{query ? 'No users match your search.' : 'No users yet.'}</p>}
        <div className="mt-3 hidden min-[701px]:block">
          <Panel>
            <Row cols={USER_COLS} variant="head">
              <div>Email</div>
              <div>League</div>
              <div className="text-right">Days</div>
              <div className="text-right">Last seen</div>
              <div className="text-right">Admin</div>
            </Row>
            {users.map((u) => {
              const first = u.leagues[0];
              const extra = u.leagues.slice(1);
              return (
                <div key={u.id}>
                  <Row cols={USER_COLS}>
                    <div className="min-w-0 truncate">
                      <Link href={`/admin/user/${u.id}`} className="hover:underline">
                        {u.email}
                      </Link>
                      {u.name ? <span className="text-dim"> · {u.name}</span> : null}
                    </div>
                    <div className="min-w-0 truncate">
                      {first ? leagueLink(first) : <span className="text-dim">—</span>}
                    </div>
                    <div className="text-right">{u.active_days}</div>
                    <div className="whitespace-nowrap text-right text-dim">{lastSeen(u.last_active_at)}</div>
                    <div className="text-right text-dim">
                      {u.is_admin ? <span title="App owner">✓</span> : ""}
                    </div>
                  </Row>
                  {extra.map((lg) => (
                    <Row key={lg.league_id} cols={USER_COLS}>
                      <div />
                      <div className="min-w-0 truncate text-dim">{leagueLink(lg)}</div>
                      <div />
                      <div />
                      <div />
                    </Row>
                  ))}
                </div>
              );
            })}
          </Panel>
        </div>


  <div className="min-[701px]:hidden space-y-3">{users.map(user => <Panel key={user.id}><div className="p-4 space-y-3"><Link href={`/admin/user/${user.id}`} className={styles.userLink}>{user.name || user.email}</Link>{user.name && <p className={styles.email}>{user.email}</p>}<p className="text-prose text-dim">{user.is_admin ? 'App owner' : 'Member'} · {user.active_days} active days</p><p className="text-prose text-dim">Last seen {lastSeen(user.last_active_at)}</p><div className="flex flex-col gap-2 text-prose">{user.leagues.length ? user.leagues.map(league => <span key={league.league_id}>{leagueLink(league)}</span>) : <span>No leagues</span>}</div></div></Panel>)}</div>
  <section className={styles.usage} aria-labelledby="usage-title"><h2 id="usage-title">Usage</h2><StatGrid stats={[{label:'Active today',value:activeUsers.d1},{label:'Active 7d',value:activeUsers.d7},{label:'Active 30d',value:activeUsers.d30}]} className="mt-4" /><DauBar daily={activeUsers.daily} /></section>
  </>;
}
