/**
 * Login-gate matcher guard — web/middleware.ts
 * ---------------------------------------------------------------------------
 * The matcher decides which requests are authenticated AT ALL, and both ways of
 * getting it wrong fail silently:
 *
 *   too loose  → a path merely *containing* "icon" skips the login gate. That
 *                was the shipped defect: `.*icon` is an unanchored substring,
 *                and every dynamic segment supplies the substring, so
 *                /league/123icon, /admin/user/1icon and /league/123/owner/u1icon
 *                all returned 200 to an unauthenticated caller.
 *   too tight  → a metadata route gets gated. Next gives metadata routes no
 *                session even for a signed-in visitor, so the crawler is 302'd
 *                to /login and every unfurled link silently renders the
 *                fallback card. No error, no test failure.
 *
 * So this file asserts BOTH directions. A test that only proved the og routes
 * bypass would pass on the broken matcher; one that only proved a substring
 * path is gated would pass on a matcher that gates everything.
 *
 * WHY IT GOES THROUGH NEXT'S OWN FUNCTIONS
 * `new RegExp(matcher).test(path)` disagrees with Next — Next runs the literal
 * through path-to-regexp and wraps it (`_next/data` prefix, optional `.json`,
 * optional trailing `[/#?]`), which changes the verdict on /api/health and
 * /_next/static/x.js. So we read middleware.ts FROM DISK and drive it through
 * `getPageStaticInfo` (the AST extraction the build itself performs) and
 * `getMiddlewareRouteMatcher` (the runtime matcher). That proves three things
 * in one pass: the literal is statically extractable, Next compiles it, and the
 * gate/skip verdicts are right.
 *
 * The extractability half is not academic. Next cannot resolve an identifier in
 * `export const config`; hoisting the literal into a `const` yields only a
 * build WARNING and silently falls back to the CATCH-ALL matcher, which gates
 * /api/*, all four og routes and /_next/static/*. `matcher_is_statically_
 * extractable` is the regression test for exactly that.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * vitest's CWD is `web/`, not the repo root. Anchor explicitly (the lesson
 * furniture-rules.test.ts already carries) so a future CWD change cannot make
 * this guard read nothing and report green.
 */
const REPO_ROOT = resolve(__dirname, "..", "..");
const WEB_ROOT = join(REPO_ROOT, "web");
const MIDDLEWARE = join(WEB_ROOT, "middleware.ts");
const APP_DIR = join(WEB_ROOT, "app");

type Verdict = (pathname: string) => boolean;

let gates: Verdict;

beforeAll(async () => {
  const { getPageStaticInfo } = await import(
    "next/dist/build/analysis/get-page-static-info.js"
  );
  const { getMiddlewareRouteMatcher } = await import(
    "next/dist/shared/lib/router/utils/middleware-route-matcher.js"
  );

  const info = await getPageStaticInfo({
    pageFilePath: MIDDLEWARE,
    // Empty config is faithful only while next.config.mjs sets none of the
    // three options that change the compiled matcher — asserted below.
    nextConfig: {},
    page: "/middleware",
    pageType: "root" as never,
  });

  const matchers = info.middleware?.matchers;
  if (!matchers || matchers.length === 0) {
    throw new Error(
      "Next extracted NO matchers from web/middleware.ts. It falls back to the " +
        "catch-all, which gates /api/*, every opengraph-image route and " +
        "/_next/static/*. Almost always cause: the matcher literal was hoisted " +
        "into a const or imported instead of staying inline in config.matcher.",
    );
  }
  const match = getMiddlewareRouteMatcher(matchers);
  gates = (pathname: string) =>
    match(pathname, { headers: {}, nextUrl: { pathname } } as never, {});
});

describe("login-gate matcher", () => {
  it("matcher_is_statically_extractable", async () => {
    const { getPageStaticInfo } = await import(
      "next/dist/build/analysis/get-page-static-info.js"
    );
    const info = await getPageStaticInfo({
      pageFilePath: MIDDLEWARE,
      nextConfig: {},
      page: "/middleware",
      pageType: "root" as never,
    });
    // A non-empty array is the whole property: an empty/undefined result is
    // Next's silent catch-all fallback, not an error.
    expect(info.middleware?.matchers?.length).toBeGreaterThan(0);
  });

  it("next_config_sets_nothing_that_would_change_the_compiled_matcher", () => {
    // basePath, i18n and trailingSlash each rewrite the compiled regexp, which
    // would make every verdict below a fiction. Fail loudly instead.
    const cfg = readFileSync(join(WEB_ROOT, "next.config.mjs"), "utf8");
    for (const key of ["basePath", "i18n", "trailingSlash"]) {
      expect(cfg).not.toMatch(new RegExp(`^\\s*${key}\\s*:`, "m"));
    }
  });

  // ---- direction 1: paths that MUST be gated -----------------------------
  //
  // The six `…icon`-shaped rows are the regression proof. Every one of them
  // returned 200 unauthenticated against a running server on the old matcher.
  it.each([
    "/",
    "/login", // the middleware runs and lets it through in its body
    "/methodology",
    "/admin",
    "/leagues/add",
    "/league/123",
    "/league/123icon",
    "/leagues/addicon",
    "/admin/user/1icon",
    "/league/123/owner/u1icon",
    "/league/123/trade/t1icon",
    "/league/123/draft/2025icon",
    "/opengraph-image-debug",
    // The explicit allowlist closes these too; segment-anchoring would not.
    "/admin/icon",
    "/league/123/settings/icon",
    "/favicon.icons",
    "/favicon.ico/secret",
    // No such route today. Adding one means adding it to the matcher, or
    // crawlers get a /login redirect.
    "/robots.txt",
  ])("gates %s", (path) => {
    expect(gates(path)).toBe(true);
  });

  // ---- direction 2: paths that MUST bypass -------------------------------
  it.each([
    // Anonymous /api/* must 401 from the proxy, never 302 to /login.
    "/api/health",
    "/api/auth/session",
    "/_next/static/chunks/main-app.js",
    "/_next/image",
    "/favicon.ico",
    "/icon.png",
    "/apple-icon.png",
    "/league/123/opengraph-image",
    "/league/123/gm/opengraph-image",
    "/league/123/owner/u1/opengraph-image",
    "/league/123/trade/t1/opengraph-image",
    // Yahoo-shaped league ids carry dots.
    "/league/449.l.12345/opengraph-image",
    // The URL Next generates once ANY route group is added above these files.
    "/league/123/gm/opengraph-image-a1b2c3",
    // The URL `generateImageMetadata` produces. Verified 200 image/png live.
    "/league/123/gm/opengraph-image/anything/deep",
    "/league/123/opengraph-image/secret",
  ])("bypasses %s", (path) => {
    expect(gates(path)).toBe(false);
  });

  // ---- direction 2, derived: every REAL metadata route on disk -----------
  //
  // Hand-written rows go stale. This walks app/ and re-derives the URLs, so
  // adding, moving or renaming a metadata route fails here until the matcher's
  // allowlist is updated — which is the one cost of choosing an allowlist over
  // a wildcard, paid by the test rather than by a broken unfurl in production.
  it("every metadata route file under web/app bypasses the gate", () => {
    const found = metadataRoutes(APP_DIR);
    expect(found.length).toBeGreaterThan(0); // a guard that read nothing is not green
    const gated = found.filter((url) => gates(url));
    expect(gated).toEqual([]);
  });
});

/** Walk app/ and turn each metadata file into the URL it is served at. */
function metadataRoutes(dir: string, urlPrefix = ""): string[] {
  const NAMES = ["opengraph-image", "twitter-image", "icon", "apple-icon", "favicon"];
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      // Route groups `(x)` and parallel slots `@x` contribute no URL segment;
      // a dynamic `[id]` gets a concrete stand-in.
      const seg = entry.startsWith("(") || entry.startsWith("@")
        ? ""
        : entry.startsWith("[")
          ? "/123"
          : `/${entry}`;
      out.push(...metadataRoutes(full, urlPrefix + seg));
      continue;
    }
    const dot = entry.lastIndexOf(".");
    const base = dot === -1 ? entry : entry.slice(0, dot);
    const ext = dot === -1 ? "" : entry.slice(dot);
    // Numbered variants: icon2.tsx → /icon2
    if (!NAMES.some((n) => base === n || new RegExp(`^${n}\\d+$`).test(base))) continue;
    // Code routes (.tsx/.ts/.js) serve at the bare name; static image/ico files
    // serve at name + extension.
    out.push(
      urlPrefix + "/" + base + ([".tsx", ".ts", ".jsx", ".js"].includes(ext) ? "" : ext),
    );
  }
  return out;
}
