import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reconcile } from './controller.mjs';

function fixture() {
  let state = null;
  const events = [];
  const store = { read: async () => structuredClone(state), write: async s => { state = structuredClone(s); } };
  const cloud = {
    create: async nonce => { events.push('create'); return 'vm-1'; },
    find: async () => null,
    status: async () => 'RUNNING',
    start: async () => { events.push('start'); },
    heartbeat: async () => { events.push('heartbeat'); },
    drain: async () => true,
    destroy: async () => { events.push('destroy'); },
  };
  return { store, cloud, events, state: () => state };
}

test('idle queue allocates nothing; queued work starts exactly one worker', async () => {
  // Mutation: unconditional create spends on empty queues, or recreation duplicates a worker.
  const f = fixture();
  assert.equal(await reconcile({ ...f, needed: false, now: 1000 }), 'idle');
  assert.deepEqual(f.events, []);
  await reconcile({ ...f, needed: true, now: 1000 });
  await reconcile({ ...f, needed: true, now: 1100 });
  assert.equal(f.events.filter(e => e === 'create').length, 1);
  assert.equal(f.state().id, 'vm-1');
});

test('a claim racing idle demand drains before destruction', async () => {
  const f = fixture();
  await reconcile({ ...f, needed: true, now: 1000 });
  f.cloud.drain = async () => false; // worker claimed after demand snapshot
  assert.equal(await reconcile({ ...f, needed: false, now: 1500 }), 'draining');
  assert.equal(f.state().phase, 'draining');
  assert.equal(f.events.includes('destroy'), false);
  // A new demand snapshot must not restart claims during drain.
  const starts = f.events.filter(e => e === 'start').length;
  await reconcile({ ...f, needed: true, now: 1501 });
  assert.equal(f.events.filter(e => e === 'start').length, starts);
  f.cloud.drain = async () => true;
  assert.equal(await reconcile({ ...f, needed: true, now: 1502 }), 'destroying');
});

test('unknown demand cannot launch but still enforces retained VM expiry', async () => {
  const f = fixture();
  assert.equal(await reconcile({ ...f, needed: null, now: 1000 }), 'idle');
  await reconcile({ ...f, needed: true, now: 1000 });
  assert.equal(await reconcile({ ...f, needed: null, now: 4600 }), 'destroying');
});

test('restart after lost create response adopts nonce without creating again', async () => {
  // Mutation: retrying create after a transport error leaks duplicate sandboxes.
  const f = fixture();
  f.cloud.create = async () => { throw new Error('private provider response'); };
  await assert.rejects(reconcile({ ...f, needed: true, now: 1000 }));
  assert.equal(f.state().phase, 'creating');
  assert.ok(f.state().nonce);
  f.cloud.find = async nonce => { assert.equal(nonce, f.state().nonce); return 'vm-1'; };
  f.cloud.create = async () => { assert.fail('duplicate creation'); };
  await reconcile({ ...f, needed: true, now: 1100 });
  assert.equal(f.state().id, 'vm-1');
  assert.deepEqual(f.events, ['start', 'heartbeat']);
});

test('cannot inject credentials before recording sandbox identity', async () => {
  // Mutation: start before durable identity makes a crash leave an untracked paid worker.
  const f = fixture();
  f.cloud.start = async id => {
    assert.equal(f.state().id, id);
    assert.equal(f.state().phase, 'running');
  };
  await reconcile({ ...f, needed: true, now: 1000 });
});

test('unsuccessful uncredentialed creation expires without a permanent manual hold', async () => {
  // Mutation: retaining creating forever prevents every following weekly job.
  const f = fixture();
  f.cloud.create = async () => { throw new Error('offline'); };
  await assert.rejects(reconcile({ ...f, needed: true, now: 1000 }));
  assert.equal(await reconcile({ ...f, needed: true, now: 1100 }), 'creation_pending');
  assert.equal(await reconcile({ ...f, needed: true, now: 2200 }), 'creation_expired');
  assert.equal(f.state().phase, 'idle');
  assert.deepEqual(f.events, []);
});

test('idle grace retains running VM then confirms destruction before replacement', async () => {
  // Mutation: clearing ID before confirmed destruction permits two credentialed workers.
  const f = fixture();
  await reconcile({ ...f, needed: true, now: 1000 });
  await reconcile({ ...f, needed: false, now: 1100 });
  assert.equal(f.state().phase, 'running');
  await reconcile({ ...f, needed: false, now: 1500 });
  assert.equal(f.state().phase, 'destroying');
  await reconcile({ ...f, needed: true, now: 1600 });
  assert.equal(f.events.filter(e => e === 'create').length, 1);
  f.cloud.status = async () => 'DESTROYED';
  await reconcile({ ...f, needed: true, now: 1700 });
  assert.equal(f.state().phase, 'idle');
});

test('control-plane outage cannot be interpreted as destruction', async () => {
  // Mutation: treating any lookup failure as missing starts a duplicate VM.
  const f = fixture();
  await reconcile({ ...f, needed: true, now: 1000 });
  f.cloud.status = async () => { throw new Error('offline'); };
  await assert.rejects(reconcile({ ...f, needed: true, now: 1100 }));
  assert.equal(f.state().id, 'vm-1');
  assert.equal(f.events.filter(e => e === 'create').length, 1);
});

test('hard lifetime and daily creation limit bound infrastructure spending', async () => {
  // Mutation: endless keepalive or recreation can leave a billable VM running all week.
  const f = fixture();
  await reconcile({ ...f, needed: true, now: 1000 });
  await reconcile({ ...f, needed: true, now: 4600 });
  assert.equal(f.state().phase, 'destroying');
  f.cloud.status = async () => 'DESTROYED';
  await reconcile({ ...f, needed: true, now: 4601 });
  await f.store.write({ ...f.state(), launches: [1000, 2000] });
  assert.equal(await reconcile({ ...f, needed: true, now: 5000 }), 'daily_limit');
  assert.equal(f.events.filter(e => e === 'create').length, 1);
});

test('creation capacity resumes exactly 24 hours after the oldest reserved attempt', async () => {
  // Mutation: using >= for the rolling cutoff blocks work at the advertised eligibility time.
  const f = fixture();
  await f.store.write({ phase: 'idle', launches: [1000, 2000] });
  assert.equal(await reconcile({ ...f, needed: true, now: 87399 }), 'daily_limit');
  assert.deepEqual(f.events, []);
  assert.equal(await reconcile({ ...f, needed: true, now: 87400 }), 'running');
  assert.equal(f.events.filter(e => e === 'create').length, 1);
  assert.deepEqual(f.state().launches, [2000, 87400]);
});
