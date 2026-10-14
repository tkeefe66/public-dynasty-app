import { open, readFile, rename } from 'node:fs/promises';
import { dirname } from 'node:path';

export function fileStore(path) {
  return {
    async read() {
      let raw;
      try { raw = await readFile(path, 'utf8'); }
      catch (error) { if (error.code === 'ENOENT') return null; throw error; }
      const state = JSON.parse(raw);
      if (!['idle', 'creating', 'running', 'draining', 'destroying'].includes(state.phase)
          || !Array.isArray(state.launches) || state.launches.some(t => !Number.isFinite(t))
          || (state.phase !== 'idle' && (!state.nonce || !Number.isFinite(state.createdAt)
            || !Number.isFinite(state.lastDemand)))
          || (['running', 'draining', 'destroying'].includes(state.phase) && !state.id)) {
        throw new Error('Controller state invalid; preserve file and reconcile existing sandbox');
      }
      return state;
    },
    async write(state) {
      const file = await open(path + '.next', 'w', 0o600);
      try { await file.writeFile(JSON.stringify(state)); await file.sync(); }
      finally { await file.close(); }
      await rename(path + '.next', path);
      const directory = await open(dirname(path), 'r');
      try { await directory.sync(); } finally { await directory.close(); }
    },
  };
}
