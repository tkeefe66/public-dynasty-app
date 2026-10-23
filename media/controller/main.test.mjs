import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

test('daily quota exits successfully with waiting status and next eligible time', async () => {
  // Mutation: throwing on daily_limit makes the real entrypoint exit 1 instead of waiting.
  const dir = await mkdtemp(join(tmpdir(), 'recap-main-'));
  try {
    const preload = join(dir, 'preload.mjs');
    await writeFile(preload, `
      import { registerHooks } from 'node:module';
      Date.now = () => 5000_000;
      globalThis.fetch = async () => ({ ok: true, json: async () => ({ needed: true }) });
      registerHooks({ load(url, context, next) {
        if (url.endsWith('/store.mjs')) return { format: 'module', shortCircuit: true,
          source: 'export const fileStore = () => ({read: async () => ({phase:"idle",launches:[2000,1000]}),write: async () => {throw Error("unexpected write")}});' };
        if (url.endsWith('/cloud.mjs')) return { format: 'module', shortCircuit: true,
          source: 'export const cloudAdapter = () => new Proxy({}, {get() {throw Error("unexpected cloud call")}});' };
        return next(url, context);
      }});
    `);
    const env = Object.fromEntries(['RAILWAY_TOKEN', 'RAILWAY_ENVIRONMENT_ID',
      'RECAP_WORKER_CHECKPOINT', 'RECAP_WORKER_IMAGE', 'MEDIA_API_URL',
      'MEDIA_WORKER_TOKEN', 'ELEVENLABS_API_KEY'].map(key => [key, 'test-only']));
    const result = spawnSync(process.execPath, ['--import', preload, fileURLToPath(new URL('./main.mjs', import.meta.url))], {
      env: { ...process.env, ...env, MEDIA_CONTROL_API_URL: 'https://example.test' },
      encoding: 'utf8', timeout: 5000,
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stderr, '');
    const event = JSON.parse(result.stdout.trim());
    assert.equal(event.status, 'waiting_daily_limit');
    assert.equal(event.launches_used, 2);
    assert.equal(event.launch_limit, 2);
    assert.equal(event.next_eligible_at, new Date(87400_000).toISOString());
    assert.match(event.message, /next scheduled run/i);
  } finally { await rm(dir, { recursive: true, force: true }); }
});
