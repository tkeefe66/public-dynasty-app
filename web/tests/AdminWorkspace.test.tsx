import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import AdminPage from '../app/admin/page';
import { adminOverview, getMe } from '../lib/api';

vi.mock('@/components/TopBar', () => ({ TopBar: () => null }));
vi.mock('@/components/admin/GenerationControl', () => ({ GenerationControl: ({ adminSection, budgetContent }: { adminSection: string; budgetContent: React.ReactNode }) => <><p hidden={adminSection === 'budget'}>Writing workspace</p>{adminSection === 'budget' && budgetContent}</> }));
vi.mock('@/components/LlmCostPanel', () => ({ LlmCostPanel: () => <p>Cost breakdown</p> }));
vi.mock('@/lib/api', () => ({
  ApiError: class extends Error { constructor(public status: number, message: string) { super(message); } },
  getMe: vi.fn(async () => ({ is_admin: true })),
  adminOverview: vi.fn(async () => ({ users: 1, leagues: 1, memberships: 1, budget: { monthly_budget_usd: 0, month_to_date_usd: 5.74, budget_remaining_usd: null } })),
  adminLeagues: async () => [{ league_id: 'sample-league', name: 'Sample League', member_count: 1, warm: true, active_users: 1, spend_mtd_usd: 5.74 }],
  adminUsers: async () => [{ id: 'sample-user', email: 'sample@example.test', leagues: [{ league_id: 'sample-league', name: 'Sample League' }], active_days: 3 }],
  adminActiveUsers: async () => ({ d1: 1, d7: 1, d30: 1, daily: [] }),
  adminBackups: async () => ({ enabled: true, last_ok_at: null, last_run_id: null, last_error: 'Backup failed' }),
}));
afterEach(() => { cleanup(); window.history.replaceState(null, '', '/admin'); });

it('separates Admin reports, usage, and monthly spending into four accessible tabs', async () => {
  // Mutation: remove hidden from report panels, exposing every report below AI writing.
  render(await AdminPage());
  const tabs = screen.getByRole('tablist', { name: 'Admin sections' });
  expect(within(tabs).getAllByRole('tab')).toHaveLength(4);
  expect(screen.getByText('Writing workspace')).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'Usage' })).not.toBeInTheDocument();
  fireEvent.click(within(tabs).getByRole('tab', { name: /Leagues/ }));
  expect(screen.getByRole('searchbox', { name: 'Search leagues' })).toBeVisible();
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'missing' } });
  expect(screen.getByText('No leagues match your search.')).toBeVisible();
  fireEvent.click(within(tabs).getByRole('tab', { name: /Users/ }));
  expect(screen.getByRole('heading', { name: 'Usage' })).toBeVisible();
  expect(screen.getByRole('searchbox', { name: 'Search users' })).toBeVisible();
  fireEvent.click(within(tabs).getByRole('tab', { name: 'Monthly LLM budget' }));
  expect(screen.getByLabelText('Monthly budget in dollars')).toBeVisible();
  expect(screen.getByText('Cost breakdown')).toBeVisible();
  expect(screen.getByText('Writing workspace')).not.toBeVisible();
  expect(window.location.search).toBe('?tab=budget');
});

it('keeps the Admin tabs available during a report outage without inventing counts', async () => {
  // Mutation: bypass the authenticated report fallback and lose AI controls.
  vi.mocked(adminOverview).mockRejectedValueOnce(new Error('Reports offline'));
  render(await AdminPage());
  expect(screen.getByText('Writing workspace')).toBeVisible();
  fireEvent.click(screen.getByRole('tab', { name: 'Leagues' }));
  expect(within(screen.getByRole('tabpanel')).getByText('This report is unavailable.')).toBeVisible();
  expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
});

it('does not fetch or render Admin data for a non-owner', async () => {
  // Mutation: remove the getMe admin check before fetching reports.
  vi.mocked(getMe).mockResolvedValueOnce({ is_admin: false } as Awaited<ReturnType<typeof getMe>>);
  vi.mocked(adminOverview).mockClear();
  render(await AdminPage());
  expect(screen.getByText('This area is for app owners.')).toBeVisible();
  expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
  expect(adminOverview).not.toHaveBeenCalled();
});

it('supports direct links, keyboard tabs, and browser history without losing backup errors', async () => {
  // Mutation: ignore the tab query or omit popstate handling.
  window.history.replaceState(null, '', '/admin?tab=users');
  render(await AdminPage());
  const users = screen.getByRole('tab', { name: /Users/ });
  expect(users).toHaveAttribute('aria-selected', 'true');
  fireEvent.keyDown(users, { key: 'Home' });
  expect(screen.getByRole('tab', { name: 'AI writing' })).toHaveFocus();
  window.history.replaceState(null, '', '/admin?tab=leagues');
  fireEvent.popState(window);
  expect(screen.getByRole('tab', { name: /Leagues/ })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByText('Backup failed')).toBeInTheDocument();
});
