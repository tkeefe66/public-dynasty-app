import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GenerationJob } from '../components/admin/GenerationJob';
import { GenerationRecords } from '../components/admin/GenerationRecords';
import { GenerationBulkReview } from '../components/admin/GenerationBulkReview';

const request = vi.fn();
vi.mock('@/lib/api', () => ({ generationRequest: (...args: unknown[]) => request(...args) }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const job = { id: 'job', kind: 'generation', feature: 'trade_story' as const, label: 'Example trade',
  league_id: 'synthetic', state: 'needs_attention', reason: 'execution_failed', generation: 2 };
const run = async (callback: () => Promise<unknown>) => { await callback(); };
const guidance = { action: 'support', title: 'Requires an app fix',
  explanation: 'Copy the issue details and paste them into your Codex chat.', cost: 'No new AI request.',
  report: 'Job: job; reason: execution_failed', related_jobs: [] };
const preview = { id: 'review', digest: 'exact', expires_at: 9999999999, max_calls: 2,
  items: [{ key: 'candidate', feature: 'trade_story', label: 'Example trade', league_id: 'synthetic',
    model: 'test-model', max_calls: 2, blocked_by: [], event: 'created' }] };

it('automatically diagnoses a stopped job and copies a useful report without purchasing writing', async () => {
  // Mutation: hide diagnosis behind Review problem or send a paid request during diagnosis.
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  request.mockResolvedValue({ job, attempts: [], resolution: guidance });
  render(<ul><GenerationJob row={job} leagues={[]} busy={false} run={run} review /></ul>);
  expect(await screen.findByText('Requires an app fix')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Copy issue details' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(guidance.report));
  expect(await screen.findByRole('status')).toHaveTextContent('Issue details copied');
  expect(request.mock.calls.every(call => call[1] === undefined)).toBe(true);
  expect(screen.queryByRole('button', { name: /Resume|replacement/i })).not.toBeInTheDocument();
});

it('offers cancellation directly and records a default reason without asking the owner to write one', async () => {
  // Mutation: cancellation remains buried in details or becomes unavailable without a typed audit note.
  request.mockResolvedValue({ job, attempts: [], resolution: guidance });
  render(<ul><GenerationJob row={job} leagues={[]} busy={false} run={run} review /></ul>);
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel this work' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm cancellation' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/jobs/job', expect.objectContaining({
    action: 'cancel', expected_generation: 2, expected_state: 'needs_attention', reason: expect.any(String),
  })));
});

it('keeps replacement preparation separate from the final paid approval', async () => {
  // Mutation: the replacement review button applies the campaign without the separate approval click.
  request.mockImplementation(async (path: string) => path.endsWith('/replacement') ? preview :
    { job, attempts: [], resolution: { ...guidance, action: 'replacement', title: 'A new writing attempt needs approval' } });
  render(<ul><GenerationJob row={job} leagues={[]} busy={false} run={run} review /></ul>);
  fireEvent.click(await screen.findByRole('button', { name: 'Review new writing attempt' }));
  expect(screen.getByText(/Cancel the stopped attempt/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel old attempt & review replacement' }));
  const approve = await screen.findByRole('button', { name: 'Approve & start writing' });
  expect(request.mock.calls.some(call => call[0] === '/campaigns/apply')).toBe(false);
  fireEvent.click(approve);
  await waitFor(() => expect(request).toHaveBeenCalledWith('/campaigns/apply', expect.objectContaining({
    preview_id: 'review', digest: 'exact',
  })));
});

it('makes selection, review, and final approval explicit without a required reason field', async () => {
  // Mutation: selection starts writing, or the final approval is never reachable from the primary action.
  request.mockImplementation(async (path: string) => path.startsWith('/records') ? { records: [
    { key: 'candidate', label: 'Example trade', feature: 'trade_story', availability: 'available', reviewable: true },
  ], next_offset: null } : path === '/campaigns/preview' ? preview : { jobs: ['new-job'] });
  render(<GenerationRecords leagues={[]} busy={false} run={run} version={0} initialKind="candidates" />);
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select Example trade' }));
  expect(screen.queryByLabelText('Reason for this approval')).not.toBeInTheDocument();
  expect(request.mock.calls.some(call => call[0].startsWith('/campaigns'))).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Review & approve 1 item' }));
  const review = await screen.findByRole('region', { name: 'Review writing request' });
  expect(review).toHaveFocus();
  expect(within(review).getByText('test-model')).toBeVisible();
  expect(request.mock.calls.some(call => call[0] === '/campaigns/apply')).toBe(false);
  fireEvent.click(within(review).getByRole('button', { name: 'Approve & start writing' }));
  expect(await screen.findByText(/Writing queued/)).toBeVisible();
});

it('groups only matching content attempts while keeping every cancellation reachable', async () => {
  // Mutation: group by display label, hiding a distinct week, or discard older attempts entirely.
  request.mockImplementation(async (path: string) => ({ job: { ...job, id: path.split('/').pop() }, attempts: [], resolution: guidance }));
  render(<GenerationBulkReview rows={[
    { ...job, id: 'latest', review_group: 'same-event', created_at: 200 },
    { ...job, id: 'older', review_group: 'same-event', created_at: 100 },
    { ...job, id: 'other-week', review_group: 'different-event', created_at: 50 },
  ]} leagues={[]} busy={false} run={run} version={0} />);
  const related = await screen.findByText('1 other stopped attempt for this content', { selector: 'summary' });
  const buttons = await screen.findAllByRole('button', { name: 'Cancel this work' });
  expect(buttons).toHaveLength(3);
  expect(buttons[1]).not.toBeVisible();
  fireEvent.click(related);
  await waitFor(() => expect(buttons[1]).toBeVisible());
});

it('provides a copyable report for publication-only failures without including saved content', async () => {
  // Mutation: succeeded writing with a failed delivery has no escalation path, or report copies raw content.
  const writeText = vi.fn().mockRejectedValue(new Error('Clipboard unavailable'));
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  request.mockResolvedValue({ records: [{ id: 'delivery', key: 'artifact:saved', feature: 'trade_story',
    label: 'Example trade', error: 'projection_failed', payload_json: 'private saved prose' }], next_offset: null });
  render(<GenerationRecords leagues={[]} busy={false} run={run} version={0} initialKind="outbox" reviewOnly />);
  fireEvent.click(await screen.findByRole('button', { name: 'Copy issue details' }));
  const fallback = await screen.findByRole('textbox');
  expect((fallback as HTMLTextAreaElement).value).toContain('delivery');
  expect((fallback as HTMLTextAreaElement).value).toContain('projection_failed');
  expect((fallback as HTMLTextAreaElement).value).not.toContain('private saved prose');
  expect(request.mock.calls.every(call => call[1] === undefined)).toBe(true);
});
