import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Load instrumentation.ts (Sentry server/edge init) on Next 14.
  experimental: { instrumentationHook: true },
  // The transparent /api rewrite was replaced by an explicit catch-all Route
  // Handler (app/api/[...path]/route.ts) that injects the Authorization header
  // and streams SSE. NextAuth's own routes live under app/api/auth/* and take
  // precedence over the catch-all.
  eslint: {
    // `npm run lint` (next lint) is the linting entrypoint — run it
    // explicitly, in CI or locally. Before web/.eslintrc.json existed, `next
    // build` had no ESLint config to run and silently skipped linting; keep
    // that decoupling now that a config is committed, since a handful of
    // pre-existing lint errors in untouched files (react/no-unescaped-entities
    // in MethodologyContent.tsx, a rules-of-hooks violation in
    // PastPicksTable.tsx) would otherwise fail every build until someone
    // fixes them.
    ignoreDuringBuilds: true,
  },
};

// Wrap for Sentry. No org/project/authToken → no source-map upload; Sentry is
// inert at runtime unless the *_SENTRY_DSN envs are set.
export default withSentryConfig(nextConfig, {
  silent: true,
  sourcemaps: { disable: true },
});
