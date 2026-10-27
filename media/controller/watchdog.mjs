import { readFile, open, rename } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';

export const GRACE_SECONDS = 600;

export function watchdogStore(path) {
  return {
    async read() {
      try { return JSON.parse(await readFile(path, 'utf8')); }
      catch (error) { if (error.code === 'ENOENT') return null; throw error; }
    },
    async write(value) {
      const file = await open(path + '.next', 'w', 0o600);
      try { await file.writeFile(JSON.stringify(value)); await file.sync(); }
      finally { await file.close(); }
      await rename(path + '.next', path);
    },
  };
}

export async function checkWatchdog({ store, probe, send, now, recipient, sender }) {
  let state = await store.read();
  if (state && now - state.checkedAt < 240) return;
  let reason = 'monitor_api_unreachable';
  try {
    const result = await probe();
    if (result.healthy === true && result.reason === '' && Number.isFinite(result.checked_at)
        && Math.abs(now - result.checked_at) < 120) reason = '';
    else if (result.healthy === false && /^[a-z_]+$/.test(result.reason || '')) reason = result.reason;
    else reason = 'monitor_health_response_invalid';
  } catch { /* API errors and timeouts are monitored independently of that API. */ }
  if (!reason) {
    await store.write({ checkedAt: now, incident: null });
    console.log(JSON.stringify({ event: 'recap_watchdog', status: 'healthy', checked_at: now }));
    return;
  }
  // Changing symptoms during the same outage must not reset the grace period.
  const incident = state?.incident || { id: randomUUID(), since: now, sent: false };
  state = { checkedAt: now, incident };
  incident.reason = reason;
  await store.write(state);
  console.log(JSON.stringify({ event: 'recap_watchdog', status: 'unhealthy', reason, since: incident.since }));
  if (incident.sent || now - incident.since < GRACE_SECONDS) return;
  if (!incident.payload) {
    incident.firstSendAt = now;
    incident.payload = { from: sender, to: [recipient],
      subject: 'Public Dynasty recap monitoring is unhealthy',
      text: `The independent Railway watchdog cannot confirm that weekly recap monitoring is working.\n\nCause: ${reason}\nUnhealthy since: ${new Date(incident.since * 1000).toISOString()}\n\nAutomatic checks have retried for at least ten minutes. Recaps may stop being monitored across all eight leagues. Inspect the Railway API and recap monitor heartbeat/configuration. This alert does not start generation or authorize additional AI spending.` };
    await store.write(state);
  }
  // Same immutable envelope/key after timeouts, within Resend's 24-hour window.
  if (now - incident.firstSendAt >= 23 * 3600) {
    console.error(JSON.stringify({ event: 'recap_watchdog', status: 'email_outcome_unresolved' }));
    return;
  }
  if (incident.payload.from !== sender || incident.payload.to[0] !== recipient) {
    throw new Error('Watchdog alert recipient changed; review saved incident');
  }
  await send('recap-watchdog/' + incident.id, incident.payload);
  incident.sent = true;
  await store.write(state);
  console.log(JSON.stringify({ event: 'recap_watchdog', status: 'alert_accepted', reason }));
}

export async function runWatchdog(env = process.env, {
  store = watchdogStore('/state/recap-watchdog.json'),
  healthPath = '/api/internal/media/recap-monitor-health',
} = {}) {
  if (env.RECAP_WATCHDOG_ENABLED !== 'true') return;
  for (const key of ['MEDIA_CONTROL_API_URL', 'MEDIA_WORKER_TOKEN', 'RECAP_WATCHDOG_RESEND_API_KEY',
    'RECAP_WATCHDOG_TO', 'RECAP_WATCHDOG_FROM']) {
    if (!env[key]) throw new Error('Watchdog configuration missing: ' + key);
  }
  const api = new URL(env.MEDIA_CONTROL_API_URL);
  if (api.username || api.password || api.pathname !== '/' || api.search || api.hash
      || !(api.protocol === 'https:' || api.protocol === 'http:' && api.hostname.endsWith('.railway.internal'))) {
    throw new Error('Watchdog requires HTTPS or Railway private API origin');
  }
  await checkWatchdog({ store,
    now: Math.floor(Date.now() / 1000), recipient: env.RECAP_WATCHDOG_TO, sender: env.RECAP_WATCHDOG_FROM,
    probe: async () => {
      const response = await fetch(new URL(healthPath, api), {
        headers: { authorization: 'Bearer ' + env.MEDIA_WORKER_TOKEN }, redirect: 'error',
        signal: AbortSignal.timeout(20_000),
      });
      if (!response.ok) throw new Error('Monitor health API unavailable');
      return response.json();
    },
    send: async (key, payload) => {
      const response = await fetch('https://api.resend.com/emails', {
        method: 'POST', headers: { authorization: 'Bearer ' + env.RECAP_WATCHDOG_RESEND_API_KEY,
          'Content-Type': 'application/json', 'Idempotency-Key': key },
        body: JSON.stringify(payload), redirect: 'error', signal: AbortSignal.timeout(20_000),
      });
      if (!response.ok || typeof (await response.json()).id !== 'string') throw new Error('Watchdog email not confirmed');
    },
  });
}
