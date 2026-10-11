import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { BackupStatus, LeagueReport, UserReport } from '../components/admin/AdminReports';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('keeps UTC report dates identical during server rendering and browser hydration', () => {
  // Mutation: omit the explicit UTC zone after moving reports into a client component.
  const format = Date.prototype.toLocaleDateString;
  vi.spyOn(Date.prototype, 'toLocaleDateString').mockImplementation(function (this: Date, locale, options) {
    return format.call(this, locale, { timeZone: 'America/Denver', ...options });
  });
  const timestamp = '2026-10-08T01:00:00Z';
  render(<>
    <BackupStatus backups={{ enabled: true, last_ok_at: timestamp, last_run_id: 'sample', last_error: null }} />
    <LeagueReport leagues={[{ league_id: 'sample', name: 'Sample', season: 2026, format: 'dynasty', member_count: 1, warm: true, active_users: 1, spend_mtd_usd: 0, last_activity: timestamp }]} />
    <UserReport users={[{ id: 'sample', name: 'Sample', email: 'sample@example.test', is_admin: false, league_count: 0, leagues: [], active_days: 1, last_active_at: timestamp, created_at: timestamp }]} activeUsers={{ d1: 1, d7: 1, d30: 1, daily: [] }} memberships={0} />
  </>);
  expect(screen.getByText('Last successful backup: Oct 8, 2026')).toBeInTheDocument();
  expect(screen.getByText('Last seen Oct 8, 2026')).toBeVisible();
  expect(screen.getAllByText('Oct 8, 2026')).toHaveLength(3);
  expect(screen.queryByText(/Oct 7, 2026/)).not.toBeInTheDocument();
});
