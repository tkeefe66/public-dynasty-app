import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkWatchdog } from './watchdog.mjs';

function fixture() {
  let saved = null;
  const sent = [];
  return { sent, store: { read: async () => structuredClone(saved), write: async s => { saved = structuredClone(s); } },
    send: async (key, payload) => { sent.push({ key, payload }); }, recipient: 'owner@example.test', sender: 'recaps@example.test' };
}

test('API outage alerts once after grace across restarted checks; recovery silently rearms', async () => {
  // Mutation: require the API to send its own outage alert, reset grace each run, or alert on success.
  const f = fixture();
  const down = async () => { throw Error('offline'); };
  for (const now of [1000, 1300, 1599]) await checkWatchdog({ ...f, probe: down, now });
  assert.equal(f.sent.length, 0);
  await checkWatchdog({ ...f, probe: down, now: 1900 });
  await checkWatchdog({ ...f, probe: down, now: 2200 });
  assert.equal(f.sent.length, 1);
  assert.match(f.sent[0].payload.text, /monitor_api_unreachable/);
  await checkWatchdog({ ...f, now: 2500, probe: async () => ({ healthy: true, reason: '', checked_at: 2500 }) });
  assert.equal(f.sent.length, 1);
  for (const now of [2800, 3100, 3400]) await checkWatchdog({ ...f, probe: down, now });
  assert.equal(f.sent.length, 2);
  assert.notEqual(f.sent[0].key, f.sent[1].key);
});

test('lost email response retries identical envelope and key despite changing failure', async () => {
  // Mutation: regenerate the alert on every retry, risking duplicate delivery after a timeout.
  const f = fixture();
  const probe = async () => ({ healthy: false, reason: 'monitor_heartbeat_stale' });
  await checkWatchdog({ ...f, probe, now: 1000 });
  const attempts = [];
  const send = async (key, payload) => { attempts.push({ key, payload }); if (attempts.length === 1) throw Error('timeout'); };
  await assert.rejects(checkWatchdog({ ...f, probe, send, now: 1600 }), /timeout/);
  await checkWatchdog({ ...f, probe: async () => { throw Error('API down'); }, send, now: 1900 });
  assert.deepEqual(attempts[0], attempts[1]);
});

test('healthy responses must be fresh and brief outages do not alert', async () => {
  // Mutation: accept a cached green response or alert during a brief deploy restart.
  const f = fixture();
  await checkWatchdog({ ...f, now: 1000, probe: async () => { throw Error('restart'); } });
  await checkWatchdog({ ...f, now: 1300, probe: async () => ({ healthy: true, reason: '', checked_at: 1300 }) });
  assert.equal((await f.store.read()).incident, null);
  for (const now of [1600, 1900, 2200]) await checkWatchdog({ ...f, now,
    probe: async () => ({ healthy: true, reason: '', checked_at: 1300 }) });
  assert.equal(f.sent.length, 1);
  assert.match(f.sent[0].payload.text, /monitor_health_response_invalid/);
});
