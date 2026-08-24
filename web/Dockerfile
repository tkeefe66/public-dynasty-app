FROM node:20-alpine AS deps
WORKDIR /app
COPY web/package.json web/package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
# The build context is the REPO ROOT (both services share it — see the
# railway-deploy skill), and the design system lives there, outside web/.
# `web/app/globals.css` imports it as `../../.design/tokens/*` and
# `web/app/layout.tsx` loads its font binaries the same way, so the image has to
# reproduce the repo's own directory relationship rather than flattening web/ to
# /app: build from /repo/web with .design as a sibling, and every relative path
# resolves identically here and on a dev machine.
WORKDIR /repo
COPY --from=deps /app/node_modules ./web/node_modules
COPY web ./web
COPY .design ./.design
WORKDIR /repo/web
# next.config.mjs bakes the /api/* rewrite destination from API_URL at BUILD
# time. Railway passes service variables as build args, so declare it here and
# expose it to `next build`; otherwise it falls back to localhost.
ARG API_URL
ENV API_URL=$API_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# Next infers the file-tracing root from the nearest lockfile, which is still
# web/package-lock.json — so the standalone output keeps its familiar shape with
# server.js at the top. The design system's woff2 builds come through
# .next/static/media (webpack emits them), and nothing reads .design at runtime:
# lib/og-font.ts fetches over HTTP precisely because standalone tracing cannot
# see a bare fs.readFile of a binary asset.
COPY --from=builder /repo/web/.next/standalone ./
COPY --from=builder /repo/web/.next/static ./.next/static
COPY --from=builder /repo/web/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
