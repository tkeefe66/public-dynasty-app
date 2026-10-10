import { defineConfig } from '@playwright/test';

const origin = process.env.RECAP_ACCEPTANCE_ORIGIN;
if (!origin || !/^http:\/\/127\.0\.0\.1:\d+$/.test(origin) ||
    process.env.AUTH_SECRET !== 'throwaway-recap-acceptance-session-secret') {
  throw new Error('Run the owned PostgreSQL acceptance harness; no real account or existing server fallback.');
}
export default defineConfig({
  testDir: '.', testMatch: 'recap-admin.spec.ts', workers: 1, retries: 0,
  timeout: 120_000, reporter: 'list', outputDir: process.env.RECAP_ACCEPTANCE_OUTPUT,
  use: { baseURL: origin, viewport: { width: 390, height: 844 }, hasTouch: true,
    launchOptions: process.env.RECAP_ACCEPTANCE_CHROME ? { executablePath: process.env.RECAP_ACCEPTANCE_CHROME } : {},
    screenshot: 'only-on-failure', trace: 'retain-on-failure' },
});
