import { randomUUID } from 'node:crypto';

export const IDLE_SECONDS = 300;
export const MAX_SECONDS = 3600;
export const MAX_DAILY_LAUNCHES = 2;

/**
 * One caller under the persistent-volume flock. No provider calls here.
 * cloud.start is idempotent on one VM; only confirmed destruction clears its ID.
 * @param {{store: {read: Function, write: Function}, cloud: {create: Function,
 * find: Function, status: Function, start: Function, drain: Function, heartbeat: Function, destroy: Function},
 * needed: boolean|null, now: number}} input
 */
export async function reconcile({ store, cloud, needed, now }) {
  let state = await store.read() ?? { phase: 'idle', launches: [] };
  state.launches = state.launches.filter(t => t > now - 86400);
  const save = async () => store.write(state);
  if (state.phase === 'creating') {
    // Creation carried only an ownership nonce: no worker/provider credentials.
    // Unknown outcomes are found by nonce, never blindly retried.
    const id = await cloud.find(state.nonce);
    if (!id) {
      if (now - state.createdAt < 1200) return 'creation_pending';
      // A late orphan never received credentials and has a ten-minute idle TTL.
      state = { phase: 'idle', launches: state.launches };
      await save();
      return 'creation_expired';
    }
    state = { ...state, phase: 'running', id };
    await save();
  }
  if (state.phase === 'idle') {
    if (!needed) return 'idle';
    if (state.launches.length >= MAX_DAILY_LAUNCHES) return 'daily_limit';
    state = { phase: 'creating', nonce: randomUUID(), createdAt: now, lastDemand: now,
      launches: [...state.launches, now] };
    await save();
    const id = await cloud.create(state.nonce);
    state = { ...state, phase: 'running', id };
    await save();
  }
  const status = await cloud.status(state.id);
  if (status === 'DESTROYED') {
    state = { phase: 'idle', launches: state.launches };
    await save();
    return 'destroyed';
  }
  if (state.phase === 'destroying') {
    await cloud.destroy(state.id);
    return 'destroying';
  }
  if (needed) state.lastDemand = now;
  if (status === 'FAILED' || now - state.createdAt >= MAX_SECONDS) {
    state.phase = 'destroying';
    await save();
    await cloud.destroy(state.id);
    return 'destroying';
  }
  if (status !== 'RUNNING') return 'starting';
  if (state.phase === 'draining' || needed === false && now - state.lastDemand >= IDLE_SECONDS) {
    state.phase = 'draining';
    await save();
    if (await cloud.drain(state.id)) {
      state.phase = 'destroying';
      await save();
      await cloud.destroy(state.id);
      return 'destroying';
    }
    await cloud.heartbeat(state.id);
    return 'draining';
  }
  await save();
  await cloud.start(state.id);
  await cloud.heartbeat(state.id);
  return 'running';
}
