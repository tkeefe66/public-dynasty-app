import { test } from 'node:test';
import assert from 'node:assert/strict';
import { encryptedStore } from '../../scripts/external-recap-watchdog.mjs';

test('public GitHub cache stores only authenticated ciphertext and survives a new runner', async () => {
  // Mutation: cache plaintext alert addresses or silently accept modified incident state.
  let saved;
  const base = { read:async()=>saved, write:async value=>{saved=value;} };
  const key='ab'.repeat(32);
  const state={incident:{id:'incident',since:1000,payload:{to:['owner@example.test']}}};
  await encryptedStore(base,key).write(state);
  assert.doesNotMatch(JSON.stringify(saved), /owner|example|incident/);
  assert.deepEqual(await encryptedStore(base,key).read(),state);
  await assert.rejects(encryptedStore(base,'cd'.repeat(32)).read());
  saved.data=(parseInt(saved.data.slice(0,2),16)^1).toString(16).padStart(2,'0')+saved.data.slice(2);
  await assert.rejects(encryptedStore(base,key).read());
});
