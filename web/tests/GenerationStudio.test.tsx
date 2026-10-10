import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { GenerationControl } from '../components/admin/GenerationControl';
import { FEATURE_LABELS } from '../lib/generation';

const request = vi.fn();
vi.mock('@/lib/api', () => ({ generationRequest: (...args: unknown[]) => request(...args) }));
const features = Object.fromEntries(Object.keys(FEATURE_LABELS).map(key => [key, { mode: 'manual', paused: false }]));
const effective = { policy: { paused: false, features }, sources: {}, blocked_by: [] };
beforeEach(() => {
  request.mockReset();
  request.mockImplementation(async (path = '') => {
    if (!path) return { control: { hold: '', provider_hold: '', breakers_json: '{}' }, effective, jobs: {}, known_cost_microusd: 0, unknown_cost_attempts: 0 };
    if (path.startsWith('/leagues')) return { records: [{ id: 'studio-league', name: 'Studio League', lifecycle: 'active', hold: '', effective, seasons: [] }], next_offset: null };
    if (path.startsWith('/policy')) return { value: {}, effective, revision: 1 };
    if (path.startsWith('/records/candidates')) return { records: [{ key: 'trade-one', label: 'Trade one', feature: 'trade_story', availability: 'available', reviewable: true }], next_offset: null };
    return { records: [], next_offset: null };
  });
});
afterEach(cleanup);

it('separates rules, spending, and content without buying writing during navigation', async () => {
  // Mutation: mount the old settings accordion with recap budgets inside writing rules.
  render(<GenerationControl />);
  const nav = await screen.findByRole('navigation', { name: 'AI writing views' });
  fireEvent.click(within(nav).getByRole('button', { name: 'Writing rules' }));
  expect(await screen.findByLabelText('Apply settings to')).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'Weekly Analyst recap limits' })).not.toBeInTheDocument();
  fireEvent.click(within(nav).getByRole('button', { name: 'Spend & limits' }));
  expect(await screen.findByLabelText('Recap limits for league')).toBeVisible();
  expect(screen.queryByLabelText('Trade stories mode')).not.toBeInTheDocument();
  expect(request.mock.calls.filter(call => call[1])).toHaveLength(0);
});

it('keeps selection across pages inside the selected content type and resets it when changing type', async () => {
  // Mutation: omit the content filter from Select all, or retain a paid preview after switching workspaces.
  render(<GenerationControl />);
  fireEvent.click(await screen.findByRole('button', { name: 'Trade stories workspace' }));
  fireEvent.click(screen.getByRole('button', { name: 'Approve writing' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Select all available content' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Select all available content' }));
  await screen.findByRole('button', { name: 'Preview 1 selected' });
  expect(request).toHaveBeenCalledWith('/records/candidates?limit=100&offset=0&view=review&feature=trade_story');
  fireEvent.click(screen.getByRole('button', { name: 'GM profiles workspace' }));
  await screen.findByRole('button', { name: 'Preview 0 selected' });
  expect(request).toHaveBeenCalledWith('/records/candidates?limit=25&offset=0&view=review&feature=gm_rating_blurb');
  expect(request.mock.calls.some(call => call[0] === '/campaigns/apply')).toBe(false);
});

it('keeps the studio league and older recap episode when opening its limits', async () => {
  // Mutation: keep an independent recap league picker, or discard the episode ID at the budget navigation boundary.
  const normal = request.getMockImplementation()!;
  request.mockImplementation(async (path = '', ...args) => {
    if (path.startsWith('/leagues')) return { records: ['studio-league', 'other-league'].map(id => ({ id, name: id, lifecycle: 'active', hold: '', effective, seasons: [] })), next_offset: null };
    if (path.startsWith('/recap-episodes?') && path.includes('other-league')) return { records: [{ episode_id: 'other-episode', season: 2026, week: 5 }] };
    if (path.startsWith('/recap-episodes?')) return { records: [{ episode_id: 'new-episode', season: 2026, week: 5 }, { episode_id: 'old-episode', season: 2026, week: 4 }] };
    if (path.startsWith('/recap-episodes/')) return { episode: {}, stage: null, attempts: [], qualification: { passed: 0, required: 3 }, reason: 'recap_budget_video_episode', actions: [] };
    if (path.startsWith('/recap-budgets')) return { caps: {}, balances: {}, month_key: '2026-10', app_limit: { balance: {} }, enforcement_state: { active: true } };
    return normal(path, ...args);
  });
  render(<GenerationControl />);
  fireEvent.change(await screen.findByLabelText('Content for league'), { target: { value: 'studio-league' } });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Weekly recap workspace' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Weekly recap workspace' }));
  expect(screen.queryByLabelText('Recap episode for league')).not.toBeInTheDocument();
  fireEvent.change(await screen.findByLabelText('Episode'), { target: { value: 'old-episode' } });
  await waitFor(() => expect(request).toHaveBeenCalledWith('/recap-episodes/old-episode'));
  fireEvent.click(await screen.findByRole('button', { name: 'Edit recap limits' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/recap-budgets/studio-league?episode_id=old-episode'));
  expect(screen.getByLabelText('Episode')).toHaveValue('old-episode');
  fireEvent.click(screen.getByRole('button', { name: 'Content' }));
  await waitFor(() => expect(screen.getByLabelText('Episode')).toHaveValue('old-episode'));
  fireEvent.change(screen.getByLabelText('Content for league'), { target: { value: 'other-league' } });
  await waitFor(() => expect(screen.getByLabelText('Episode')).toHaveValue('other-episode'));
  fireEvent.click(screen.getByRole('button', { name: 'Review spending limits' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/recap-budgets/other-league?episode_id=other-episode'));
  expect(screen.getByLabelText('Episode')).toHaveValue('other-episode');
  expect(request.mock.calls.filter(call => call[1])).toHaveLength(0);
});
