import { afterEach, expect, it, vi } from 'vitest';
import { GET } from '@/app/api/recap-monitor-health/route';

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it('accepts only the dedicated probe and forwards only read-only health without cookies', async () => {
  // Mutation: reuse worker/admin credentials, forward cookies, or proxy arbitrary paths.
  const token = 'synthetic-monitor-probe-'.repeat(3);
  vi.stubEnv('RECAP_MONITOR_PROBE_TOKEN', token);
  vi.stubEnv('API_URL', 'http://api.internal:8000');
  const fetcher = vi.fn().mockResolvedValue(Response.json({healthy:true, reason:'', checked_at:1000, heartbeat_at:999, secret:'omit'}));
  vi.stubGlobal('fetch', fetcher);
  expect((await GET(new Request('https://example.test/api/recap-monitor-health'))).status).toBe(403);
  expect(fetcher).not.toHaveBeenCalled();
  const response = await GET(new Request('https://example.test/api/recap-monitor-health', {
    headers: {authorization:`Bearer ${token}`, cookie:'session=private'},
  }));
  expect(await response.json()).toEqual({healthy:true, reason:'', checked_at:1000, heartbeat_at:999});
  expect(response.headers.get('cache-control')).toContain('no-store');
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe('http://api.internal:8000/api/internal/media/recap-monitor-health');
  expect(options.headers).toEqual({authorization:`Bearer ${token}`});
  expect(options.redirect).toBe('error');
});

it('returns failure when Railway API is down rather than a cached healthy response', async () => {
  // Mutation: convert upstream errors into healthy HTTP 200 responses.
  const token = 'synthetic-monitor-probe-'.repeat(3);
  vi.stubEnv('RECAP_MONITOR_PROBE_TOKEN', token);
  vi.stubEnv('API_URL', 'http://api.internal:8000');
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
  const result = await GET(new Request('https://example.test/api/recap-monitor-health', {headers:{authorization:`Bearer ${token}`}}));
  expect(result.status).toBe(503);
  expect((await result.json()).healthy).toBe(false);
});
