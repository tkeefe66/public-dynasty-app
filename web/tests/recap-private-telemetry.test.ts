import { expect, it } from 'vitest';
import { redactOAuthEvent } from '@/lib/oauth-telemetry';

it.each(['/share/analyst/private-token?token=private-token',
  '%252Fapi%252Fpublic%252Fanalyst%252Fprivate-token%253Fnext%253Dprivate'])('redacts nested exception and breadcrumb credentials: %s', (path) => {
  // Mutation: redact only request.url, leaving encoded exception/breadcrumb data.
  const result = redactOAuthEvent({ type: undefined, message: 'Failure: '+path,
    exception: { values: [{ value: path }] }, request: { url: 'https://example.test/other', query_string: 'next='+path },
    breadcrumbs: [{ message: 'Failure: '+path }, { message: 'safe operational error' }] });
  expect(JSON.stringify(result)).not.toContain('private-token');
  expect(JSON.stringify(result)).toContain('safe operational error');
});
