import { expect, it } from 'vitest';
import { redactOAuthEvent } from '@/lib/oauth-telemetry';

it.each(['/share/analyst/private-token?token=private-token',
  'https://app.test/share%2Fanalyst%2Fprivate-token?bad=%',
  'bad=%FF /share%2Fanalyst%2Fprivate-token',
  'bad=% %252Fshare%252Fanalyst%252Fprivate-token?bad=%E0%A4',
  '%252Fapi%252Fpublic%252Fanalyst%252Fprivate-token%253Fnext%253Dprivate'])('redacts nested exception and breadcrumb credentials: %s', (path) => {
  // Mutation: redact only request.url, leaving encoded exception/breadcrumb data.
  const result = redactOAuthEvent({ type: undefined, message: 'Failure: '+path,
    exception: { values: [{ value: path }] }, request: { url: 'https://example.test/other', query_string: 'next='+path },
    breadcrumbs: [{ message: 'Failure: '+path }, { message: 'safe operational error' }] });
  expect(JSON.stringify(result)).not.toContain('private-token');
  expect(JSON.stringify(result)).toContain('safe operational error');
});

it.each(['bad=% /api%2Fauth%2Fcallback%2Fyahoo?code=secret',
  '/api%252Fme%252Fyahoo?bad=%FF',
  '/share%2Fanalyst%2Fprivate-token?bad=%'])('suppresses encoded credential requests and breadcrumbs: %s', (path) => {
  expect(redactOAuthEvent({ type: undefined, request: { url: path } })).toBeNull();
  expect(redactOAuthEvent({ type: undefined, breadcrumbs: [{ data: { url: path } },
    { message: 'useful unrelated failure: bad=%FF' }] })?.breadcrumbs)
    .toEqual([{ message: 'useful unrelated failure: bad=%FF' }]);
});

it('preserves unrelated malformed diagnostic text', () => {
  const event = { type: undefined, message: 'Database failed: bad=%FF and progress=50%' };
  expect(redactOAuthEvent(event)).toEqual(event);
});
