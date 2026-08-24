import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * The owner page's tab whitelist lives in TWO places and nothing kept them in
 * step:
 *
 *   - `app/league/[id]/owner/[uid]/page.tsx` — `VALID_TABS`, the SERVER-side
 *     check that turns `?tab=…` into `initialTab`.
 *   - `components/OwnerDeepDive.tsx` — `TABS`, the client list that renders the
 *     bar and decides which panel shows.
 *
 * "draft" was in the second and not the first. The failure was invisible from
 * inside the app: clicking Draft worked and pushed `?tab=draft` to the URL, so
 * the tab looked fine — but opening that URL failed the server whitelist and
 * landed on Overview. Every shared link to a franchise's Draft tab, including
 * the one the copy-receipt action builds, went to the wrong tab.
 *
 * Scanning source rather than importing, because `TABS` is built inside the
 * component body with conditional entries and cannot be read without rendering.
 */
const read = (p: string) => readFileSync(path.resolve(__dirname, "..", p), "utf8");

function serverTabs(): string[] {
  const src = read("app/league/[id]/owner/[uid]/page.tsx");
  const m = src.match(/const VALID_TABS = \[([^\]]*)\]/);
  if (!m) throw new Error("VALID_TABS not found — did the constant move or get renamed?");
  return [...m[1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]);
}

function clientTabs(): string[] {
  const src = read("components/OwnerDeepDive.tsx");
  const start = src.indexOf("const TABS:");
  if (start === -1) throw new Error("TABS not found — did the constant move or get renamed?");
  const block = src.slice(start, src.indexOf("];", start));
  return [...block.matchAll(/key:\s*"([a-z]+)"/g)].map((x) => x[1]);
}

describe("owner page tab whitelist", () => {
  it("finds both lists", () => {
    expect(serverTabs().length).toBeGreaterThan(2);
    expect(clientTabs().length).toBeGreaterThan(2);
  });

  it("every tab the client renders is accepted by the server whitelist", () => {
    const server = new Set(serverTabs());
    const missing = clientTabs().filter((k) => !server.has(k));
    expect(
      missing,
      `These tabs render in the bar but are rejected by VALID_TABS, so a deep ` +
        `link to them silently opens Overview: ${missing.join(", ")}`
    ).toEqual([]);
  });

  it("the server whitelist has no tab the client cannot render", () => {
    const client = new Set(clientTabs());
    const extra = serverTabs().filter((k) => !client.has(k));
    expect(
      extra,
      `VALID_TABS accepts tabs the client has no panel for, which resolves to ` +
        `Overview with no indication anything was wrong: ${extra.join(", ")}`
    ).toEqual([]);
  });
});
