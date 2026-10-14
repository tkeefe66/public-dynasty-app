import { setTimeout } from 'node:timers/promises';
import { reconcile } from './controller.mjs';
import { cloudAdapter } from './cloud.mjs';
import { fileStore } from './store.mjs';

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing controller configuration: ${name}`);
  return value;
}

async function main() {
  const config = {
    token: required('RAILWAY_TOKEN'), environmentId: required('RAILWAY_ENVIRONMENT_ID'),
    checkpoint: required('RECAP_WORKER_CHECKPOINT'), image: required('RECAP_WORKER_IMAGE'),
    workerEnv: { MEDIA_API_URL: required('MEDIA_API_URL'), MEDIA_WORKER_TOKEN: required('MEDIA_WORKER_TOKEN'),
      ELEVENLABS_API_KEY: required('ELEVENLABS_API_KEY') },
  };
  const api = new URL(required('MEDIA_CONTROL_API_URL'));
  if (api.username || api.password || api.pathname !== '/' || api.search || api.hash
      || !(api.protocol === 'https:' || api.protocol === 'http:' && api.hostname.endsWith('.railway.internal'))) {
    throw new Error('Controller requires HTTPS or Railway private API origin');
  }
  const store = fileStore('/state/recap-controller.json');
  const cloud = cloudAdapter(config);
  let last = '';
  const deadline = Date.now() + 70 * 60_000;
  while (Date.now() < deadline) {
    try {
      let needed = null;
      try {
        const response = await fetch(new URL('/api/internal/media/demand', api), {
        headers: { authorization: `Bearer ${config.workerEnv.MEDIA_WORKER_TOKEN}` },
        redirect: 'error', signal: AbortSignal.timeout(20_000),
      });
      if (!response.ok) throw new Error('Demand API unavailable');
        const demand = await response.json();
        if (typeof demand.needed !== 'boolean') throw new Error('Demand response invalid');
        needed = demand.needed;
      } catch {
        console.error('Demand API unavailable; reconciling existing VM lifetime without launching work.');
      }
      const status = await reconcile({ store, cloud, needed, now: Math.floor(Date.now() / 1000) });
      if (status !== last) console.log(JSON.stringify({ event: 'recap_worker_lifecycle', status }));
      last = status;
      if (['idle', 'destroyed', 'creation_expired'].includes(status)) return;
      if (status === 'daily_limit') throw new Error('Daily infrastructure limit reached');
    } catch {
      // Preserve durable state and let the next cron reconnect. Never dump SDK
      // errors: provider response bodies and command arguments may be sensitive.
      console.error('Recap controller failed; state retained. Next scheduled run will reconcile without resending narration.');
      process.exitCode = 1;
      return;
    }
    await setTimeout(30_000);
  }
  throw new Error('Controller deadline exceeded; preserve state for next scheduled run');
}

main().catch(() => {
  console.error('Recap controller configuration or lifecycle failed; check required variables and retained state.');
  process.exitCode = 1;
});
