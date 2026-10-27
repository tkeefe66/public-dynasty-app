import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { mkdir } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { runWatchdog, watchdogStore } from '../media/controller/watchdog.mjs';

export function encryptedStore(base, keyHex) {
  if (!/^[a-f0-9]{64}$/.test(keyHex || '')) throw new Error('Watchdog state encryption key missing');
  const key = Buffer.from(keyHex, 'hex');
  return {
    async read() {
      const saved = await base.read();
      if (!saved) return null;
      const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(saved.iv, 'hex'));
      decipher.setAuthTag(Buffer.from(saved.tag, 'hex'));
      return JSON.parse(Buffer.concat([decipher.update(Buffer.from(saved.data, 'hex')), decipher.final()]).toString());
    },
    async write(value) {
      const iv = randomBytes(12);
      const cipher = createCipheriv('aes-256-gcm', key, iv);
      const data = Buffer.concat([cipher.update(JSON.stringify(value)), cipher.final()]);
      await base.write({ iv: iv.toString('hex'), tag: cipher.getAuthTag().toString('hex'), data: data.toString('hex') });
    },
  };
}

async function main() {
  await mkdir('.watchdog-state', { recursive: true });
  await runWatchdog({
    RECAP_WATCHDOG_ENABLED: 'true',
    MEDIA_CONTROL_API_URL: process.env.WATCHDOG_ORIGIN,
    MEDIA_WORKER_TOKEN: process.env.WATCHDOG_PROBE_TOKEN,
    RECAP_WATCHDOG_TO: process.env.WATCHDOG_TO,
    RECAP_WATCHDOG_FROM: process.env.WATCHDOG_FROM,
    RECAP_WATCHDOG_RESEND_API_KEY: process.env.WATCHDOG_RESEND_API_KEY,
  }, { healthPath: '/api/recap-monitor-health',
    store: encryptedStore(watchdogStore('.watchdog-state/state.enc'), process.env.WATCHDOG_STATE_KEY),
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => {
    // Do not print exceptions containing credentials or provider response bodies.
    console.error('External recap watchdog failed; inspect configuration and the saved encrypted incident.');
    process.exitCode = 1;
  });
}
