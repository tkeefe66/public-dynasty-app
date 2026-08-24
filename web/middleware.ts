import { auth } from "@/auth";

// Login-gate all page routes. Unauthenticated users are redirected to /login.
//
// Exemptions are handled by the matcher below (it never runs on /api, static
// assets, or image-generation routes), so OG/twitter image unfurls and the
// proxy's own 401s are left untouched. /login itself is allowed through here.
export default auth((req) => {
  const { nextUrl } = req;

  // Canonical host: redirect any other host (e.g. the *.up.railway.app default
  // domain) to the configured canonical domain so there's one home + clean URLs.
  const canonical = process.env.CANONICAL_HOST;
  if (canonical) {
    const host = req.headers.get("host");
    if (host && host !== canonical) {
      const url = new URL(nextUrl);
      url.host = canonical;
      url.protocol = "https:";
      url.port = "";
      return Response.redirect(url, 308);
    }
  }

  const isLoggedIn = !!req.auth;
  const isLogin = nextUrl.pathname === "/login";

  if (isLogin) {
    if (isLoggedIn) {
      return Response.redirect(new URL("/", nextUrl));
    }
    return; // allow the login page for signed-out users
  }

  if (!isLoggedIn) {
    const url = new URL("/login", nextUrl);
    return Response.redirect(url);
  }
});

// The matcher literal MUST stay inline in `config.matcher` below. Next parses
// `export const config` out of the AST at build time and cannot resolve an
// identifier: hoisting the string into a `const` (same file or imported) emits
// only `WARNING: Unknown identifier ... The default config will be used
// instead.` and falls back to the CATCH-ALL. That builds and deploys, and then
// middleware runs on everything — /api/* 302s to /login instead of 401ing
// (breaking the proxy contract), every og route is gated (every unfurl becomes
// the fallback card), and /_next/static/* is gated for signed-out visitors
// (breaking the login page's own assets). tests/middleware-matcher.test.ts
// reads this file from disk and drives it through Next's own analyzer, so that
// regression fails the suite rather than shipping silently.
export const config = {
  // Run on everything except an EXPLICIT ALLOWLIST of non-page routes.
  //
  // Every exclusion below is anchored — either a `/`-terminated prefix or a
  // `$`-terminated exact path. The previous form used unanchored substrings
  // (`.*opengraph-image`, `.*icon`), which meant any path merely *containing*
  // "icon" skipped the login gate: /league/123icon, /admin/user/1icon and
  // /league/123/owner/u1icon all returned 200 unauthenticated, because dynamic
  // segments supply the substring. That was live on every dynamic route.
  //
  //   api/                 — NextAuth + the API proxy manage their own auth
  //                          (anonymous /api/* must 401, never 302)
  //   _next/static,
  //   _next/image          — Next internals (see residual note below)
  //   favicon.ico          — browsers request it implicitly
  //   icon.png,
  //   apple-icon.png       — app/icon.png + app/apple-icon.png
  //   league/…/opengraph-image — the four app/**/opengraph-image.tsx routes,
  //                          listed by path. Metadata routes get NO session
  //                          even for a signed-in visitor, so gating one 302s
  //                          the crawler and silently degrades every unfurl to
  //                          the fallback card. `(?:-[a-z0-9]+)?` admits the
  //                          `opengraph-image-<hash>` URL Next generates once a
  //                          route group appears above these files, and
  //                          `(?:/.*)?` admits the `opengraph-image/<id>` URL
  //                          `generateImageMetadata` produces — both are one
  //                          ordinary refactor away and both would otherwise be
  //                          gated. tests/middleware-matcher.test.ts derives the
  //                          expected URLs by globbing app/, so adding, moving
  //                          or renaming a metadata route fails the suite until
  //                          this list is updated.
  //
  // Residual, stated rather than implied: `_next/static` and `_next/image` stay
  // PREFIX-anchored, so /_next/static-leak/x still bypasses. That is inert —
  // Next reserves /_next, so no app route can be served there — and tightening
  // them risks breaking asset delivery for signed-out visitors on /login, which
  // is the failure direction that has no error to notice. Also note robots.txt,
  // sitemap.xml and manifest.webmanifest would be GATED; none exists today, and
  // adding one means adding it here or handing crawlers a /login redirect.
  matcher: [
    "/((?!api/|_next/static|_next/image|favicon\\.ico$|icon\\.png$|apple-icon\\.png$|league/[^/]+/(?:gm/|owner/[^/]+/|trade/[^/]+/)?opengraph-image(?:-[a-z0-9]+)?(?:/.*)?$).*)",
  ],
};
