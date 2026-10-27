import { setTimeout } from 'node:timers/promises';
import { reconcile, MAX_DAILY_LAUNCHES } from './controller.mjs';
import { cloudAdapter } from './cloud.mjs';
import { fileStore } from './store.mjs';
import { failureEvent, observed } from './diagnostics.mjs';
import { runWatchdog } from './watchdog.mjs';

function required(name) {
  const value = process.env[name];
  if (!value) throw Object.assign(new Error('Missing controller configuration'),
    { code: 'MISSING_CONFIGURATION', variable: name });
  return value;
}

async function main() {
  // Independent of media demand, VM quotas, and worker configuration.
  await runWatchdog();
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
  const context = { operation: 'configuration', phase: 'unknown' };
  const store = observed(fileStore('/state/recap-controller.json'), 'store', context);
  const cloud = observed(cloudAdapter(config), 'cloud', context);
  let last = '';
  const deadline = Date.now() + 70 * 60_000;
  while (Date.now() < deadline) {
    try {
      await runWatchdog();
      let needed = null;
      try {
        context.operation = 'demand.fetch';
        const response = await fetch(new URL('/api/internal/media/demand', api), {
        headers: { authorization: `Bearer ${config.workerEnv.MEDIA_WORKER_TOKEN}` },
        redirect: 'error', signal: AbortSignal.timeout(20_000),
      });
      if (!response.ok) throw Object.assign(new Error('Demand API unavailable'), { status: response.status });
        const demand = await response.json();
        if (typeof demand.needed !== 'boolean') throw new Error('Demand response invalid');
        needed = demand.needed;
      } catch (error) {
        console.error(JSON.stringify(failureEvent(error, context)));
      }
      const now = Math.floor(Date.now() / 1000);
      const status = await reconcile({ store, cloud, needed, now });
      if (status === 'daily_limit') {
        // The volume lock keeps this snapshot stable across reconciliation and logging.
        const state = await store.read();
        const launches = state.launches.filter(t => t > now - 86400)
          .sort((a, b) => a - b);
        const nextEligible = launches[launches.length - MAX_DAILY_LAUNCHES] + 86400;
        console.log(JSON.stringify({ event: 'recap_worker_lifecycle', status: 'waiting_daily_limit',
          launches_used: launches.length, launch_limit: MAX_DAILY_LAUNCHES,
          next_eligible_at: new Date(nextEligible * 1000).toISOString(),
          message: 'Waiting for rolling 24-hour worker launch capacity. Failed or unconfirmed creation attempts count toward the limit. The next scheduled run at or after next_eligible_at can resume queued work.',
        }));
        return;
      }
      if (status !== last) console.log(JSON.stringify({ event: 'recap_worker_lifecycle', status }));
      last = status;
      if (['idle', 'destroyed', 'creation_expired'].includes(status)) return;
    } catch (error) {
      // Preserve durable state and let the next cron reconnect. Never dump SDK
      // errors: provider response bodies and command arguments may be sensitive.
      console.error(JSON.stringify(failureEvent(error, context)));
      process.exitCode = 1;
      return;
    }
    await setTimeout(30_000);
  }
  throw new Error('Controller deadline exceeded; preserve state for next scheduled run');
}

main().catch(error => {
  console.error(JSON.stringify(failureEvent(error, { operation: 'configuration_or_deadline', phase: 'unknown' })));
  process.exitCode = 1;
});
