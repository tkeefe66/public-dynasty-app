import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileStore } from './store.mjs';

test('restart reloads durable draining identity; corrupt state never becomes idle', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'recap-store-'));
  const path = join(directory, 'state.json');
  try {
    const store = fileStore(path);
    assert.equal(await store.read(), null);
    const state = { phase: 'draining', id: 'vm', nonce: 'nonce', createdAt: 1, lastDemand: 2, launches: [1] };
    await store.write(state);
    assert.deepEqual(await fileStore(path).read(), state);
    await writeFile(path, '{"phase":"running"}');
    await assert.rejects(fileStore(path).read(), /state invalid/);
    assert.equal(await readFile(path, 'utf8'), '{"phase":"running"}');
  } finally { await rm(directory, { recursive: true, force: true }); }
});
