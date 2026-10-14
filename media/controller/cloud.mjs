import { Sandbox, SandboxNotFoundError } from 'railway';
import { readFile } from 'node:fs/promises';

export function cloudAdapter(config) {
  /** @type {import('railway').ConnectOptions} */
  const options = { token: config.token, authType: 'project-token', environmentId: config.environmentId };
  const connect = id => Sandbox.connect(id, options);
  return {
    async create(nonce) {
      const vm = await Sandbox.create(config.checkpoint, { ...options, idleTimeoutMinutes: 10,
        resources: { cpu: 2, memoryGB: 4 }, networkIsolation: 'ISOLATED',
        env: { RECAP_CONTROLLER_NONCE: nonce } });
      return vm.id;
    },
    async find(nonce) {
      const rows = await Sandbox.list({ ...options, first: 100 });
      if (rows.length >= 100) throw new Error('Sandbox inventory exceeds reconciliation bound');
      const matches = [];
      for (const row of rows.filter(r => r.status === 'RUNNING')) {
        const vm = await connect(row.id);
        const result = await vm.execHttp("python3 -c 'import os; print(os.environ.get(\"RECAP_CONTROLLER_NONCE\", \"\"))'", { timeoutSec: 10 });
        if (result.exitCode === 0 && result.stdout.trim() === nonce) matches.push(vm.id);
      }
      if (matches.length > 1) throw new Error('Multiple sandboxes claim one controller identity');
      return matches[0] ?? null;
    },
    async status(id) {
      try { return (await connect(id)).status; }
      catch (error) { if (error instanceof SandboxNotFoundError) return 'DESTROYED'; throw error; }
    },
    async start(id) {
      const vm = await connect(id);
      const code = await readFile(new URL('./bootstrap.py', import.meta.url), 'utf8');
      // Constant bootstrap code in argv; secret values only flow through stdin.
      const quoted = "'" + code.replaceAll("'", "'\\''") + "'";
      const handle = vm.exec('python3 -c ' + quoted, { stdin: true, timeoutSec: 60, maxOutputBytes: 1024 });
      const result = handle.result();
      // Attach a handler before writing, since transport setup may fail first.
      result.catch(() => {});
      await handle.stdin.write(JSON.stringify({ image: config.image, env: config.workerEnv }));
      await handle.stdin.end();
      const outcome = await result;
      if (outcome.exitCode !== 0 || outcome.timedOut) throw new Error('Worker startup failed');
    },
    async heartbeat(id) { await (await connect(id)).heartbeat(); },
    async drain(id) {
      const vm = await connect(id);
      const result = await vm.execHttp("docker exec recap-worker python3 -c 'from pathlib import Path; Path(\"/scratch/drain\").touch(); print(\"drained\" if Path(\"/scratch/drained\").exists() else \"draining\")'", { timeoutSec: 15 });
      if (result.exitCode !== 0) throw new Error('Worker drain handshake unavailable');
      return result.stdout.trim() === 'drained';
    },
    async destroy(id) { await (await connect(id)).destroy(); },
  };
}
