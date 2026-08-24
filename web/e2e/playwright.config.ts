import { defineConfig, devices } from "@playwright/test";
import { loadEnvConfig } from "@next/env";
import path from "path";

/**
 * The suite runs in two flavours (followup C6):
 *
 * - `chromium` — anonymous. Only the landing spec, which asserts the
 *   login-gate redirect and therefore must NOT carry a session.
 * - `chromium-authed` — loads the forged session written by the `setup`
 *   project, so specs reach real pages through real middleware.
 *
 * `loadEnvConfig` gives this process the same `.env.local` the dev server reads,
 * so the `AUTH_SECRET` used to forge the cookie is the one the app decrypts
 * with. Without it Playwright would see an empty env while Next saw the file.
 */
loadEnvConfig(path.join(__dirname, ".."));

const STORAGE_STATE = path.join(__dirname, ".auth", "storageState.json");

/**
 * `reuseExistingServer` adopts whatever is already listening on this port — it
 * does not check that the listener is *this* app. A different project's dev
 * server on :3000 therefore runs the entire matrix against the wrong
 * application, and the symptom is not "wrong app": it is the auth setup failing
 * with "forged session was rejected by middleware", because the other app has
 * no idea what our cookie is. That happened here, and the only tell was an
 * unfamiliar font name in the failure log's `<html class>`.
 *
 * `E2E_PORT` moves the suite off a busy port. The port is threaded through the
 * dev command as well as the URL so a spawned server and an adopted one can
 * never disagree about where the app is.
 */
const PORT = Number(process.env.E2E_PORT ?? 3000);
const ORIGIN = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: ".",
  webServer: {
    command: `npm run dev -- -p ${PORT}`,
    url: ORIGIN,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  use: { baseURL: ORIGIN },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      // Anonymous: the login-gate specs only mean anything without a session.
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /landing\.spec\.ts/,
    },
    {
      name: "chromium-authed",
      use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE },
      dependencies: ["setup"],
      testIgnore: /landing\.spec\.ts/,
    },
  ],
});
