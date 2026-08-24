---
name: railway-deploy
description: Use when deploying, redeploying, or debugging the trade-grader web app on Railway (the api/ FastAPI + web/ Next.js services), when editing api/Dockerfile or web/Dockerfile, or when the web→api proxy returns 500 / ECONNREFUSED / hits localhost.
---

# Railway deploy — trade-grader web app

> **Identity (do not get this wrong):** this repo is `/Users/tomkeefe/Code Apps/public-dynasty`, GitHub `tkeefe66/public-dynasty-app`, Railway project **`public-dynasty`** (workspace `tkeefe66's Projects`, env `production`), live at **https://dynasty.tomkeefe.ai**. The old project `sleeper-trade-grader`, the old repo folder `Code Apps/sleeper-dynasty`, and the old URLs `web-production-f949.up.railway.app` and `ffbdynasty.com` (custom domain deleted 2026-08-03) are **retired** — never deploy there. Confirm the linked project (`railway status`) before any `railway up`.

**REQUIRED BACKGROUND:** the *why* behind this setup — IPv6-only private networking (bind `::`), build-time env baking (`API_URL` as build ARG), shared-root monorepo (`RAILWAY_DOCKERFILE_PATH` instead of `rootDirectory`), volume/ignore/status commands, silent GitHub-source unbinding — lives in the global `railway-cli` skill, "Monorepo / Docker Patterns" section. This file is only what's specific to this app.

## Topology

Three-service Railway project (`public-dynasty`). The two app services build from the **repo root** (the api needs the shared `src/` package) — shared-root pattern, Dockerfile selected per service.

| Service | Dir | Builder | Networking | Live |
|---|---|---|---|---|
| `Web` | `web/` Next.js standalone | `web/Dockerfile` | **public** domain, port 8000 | https://dynasty.tomkeefe.ai |
| `API` | `api/` FastAPI/uvicorn | `api/Dockerfile` | **private** (`public-dynasty-app.railway.internal:8000`), IPv6, `/data` volume | — |
| `Postgres` | managed | — | private (auth/session store) | — |

`railway up --service api` / `--service web` match case-insensitively (CI uses lowercase). The browser hits `Web`; `Web` server-side proxies `/api/*` to `API` via `next.config.js` `rewrites()` using `API_URL`. Auth is NextAuth + Google (`AUTH_*` vars, `AUTH_URL=https://dynasty.tomkeefe.ai`, `CANONICAL_HOST=dynasty.tomkeefe.ai`) backed by `Postgres`.

## This app's service config

```bash
railway variable set RAILWAY_DOCKERFILE_PATH=api/Dockerfile --service api
railway variable set PORT=8000 --service api
railway variable set RAILWAY_DOCKERFILE_PATH=web/Dockerfile --service web
railway variable set PORT=8000 --service web
railway variable set 'API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}' --service web
```

Both app services pinned `PORT=8000` so the private `API_URL` reference resolves deterministically.

**Local invariants the Dockerfiles depend on** (each maps to a pattern in the global skill):
- `api/Dockerfile` CMD binds `uvicorn ... --host ::`
- `web/Dockerfile` builder stage has `ARG API_URL` + `ENV API_URL=$API_URL` *before* `npm run build`
- `web/public/.gitkeep` exists — `COPY /app/public` fails the Docker build without it
- `.railwayignore` at repo root

## Deploy / redeploy

**Both app services auto-deploy on push to `main` via Railway's native GitHub integration** — each service's Settings → Source is connected to `tkeefe66/public-dynasty-app`, branch `main`. One push redeploys both `Web` and `API`. There is **no** GitHub Actions workflow (`.github/workflows/deploy.yml` does **not** exist — don't re-add one).

```bash
git push origin main          # Railway builds + deploys Web and API
```

> **If a push doesn't deploy:** the native source connection has likely come unbound (see the global skill). Re-check each service → Settings → Source = `public-dynasty-app`/`main`.

**Fallback — manual local upload** (works even if the native connection is broken; also for uncommitted local state). Confirm `railway status` shows `public-dynasty` first:

```bash
railway up --service api --detach -m "..."
railway up --service web --detach -m "..."
```

## Verify end-to-end

First wait for both services to finish: use the "Watching a deploy" poll loop from the global `railway-cli` skill for `api` and `web` (in-flight states include `DEPLOYING`, not just `BUILDING` — loop to a terminal state). Then:

The app is login-gated and the `/api/*` proxy requires a session, so an anonymous `curl` of `/api/health` returns **401** (that's the proxy doing its job, not a failure). Verify via the public, unauthenticated endpoints instead:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://dynasty.tomkeefe.ai/        # 302 -> /login (login gate active)
curl -s -o /dev/null -w "%{http_code}\n" https://dynasty.tomkeefe.ai/login   # 200
curl -s https://dynasty.tomkeefe.ai/api/auth/providers                       # {"google":{...}} — NextAuth + Google up
```

To confirm the web→API private proxy + backend health, read the API runtime logs (`railway logs --service API --lines 30` → `Application startup complete` / `Uvicorn running on http://[::]:8000`) rather than curling the gated `/api/health`.

### Actually calling a gated API route

Logs only prove the process started. When the check is "did this code path run in
production," you have to make the call. `API` has **no public domain** — it is private-
networking only — and every business router is registered with a guard
(`api/app/main.py`: `dependencies=league_guard` / `admin_guard`), so both the public
proxy *and* an unauthenticated loopback request return 401. The method is in the global
`railway-cli` skill, "Exercising a route on a service with no public domain"; the values
for this app are:

- Bind address inside the container is `http://[::1]:8000` — `127.0.0.1` gives
  `Connection refused` (uvicorn binds `::`).
- `league_guard` is `require_league_member`. Any signed-in user may **read** the
  allowlisted league (`TRADE_GRADER_ALLOWLISTED_LEAGUE_ID`) without a membership row,
  so a self-minted token is enough for verification; writes still need real membership.
- Tokens are HS256 over `get_settings().auth_backend_secret`
  (`TRADE_GRADER_AUTH_BACKEND_SECRET`, shared with the web app's `AUTH_BACKEND_SECRET`),
  claims `sub` + `email`. `get_current_user` **upserts a user row and touches activity**
  for whatever email the token names — use a real owner's address, not a fake one.

⚠️ **`GET /api/league/{id}/refresh?force=true` is the expensive one.** It is the only
route that drives the four `src/sleeper_dynasty/llm/*_writer.py` writers, and `force=true`
regenerates **every** trade story plus one GM blurb and one franchise outlook per owner —
measured Aug 2026: **177 Haiku calls, ~$0.86 for a single run** on an 11-owner league.
Omit `force` for a cheap liveness check. Before running it, read the "Levers" section of
the `llm-cost-analysis` skill and state the cost estimate up front.

## Common mistakes

- Deploying to the retired `sleeper-trade-grader` project → wrong target. Verify `railway status` = `public-dynasty`.
- Setting `rootDirectory` per service → breaks the api build (loses shared `src/`).
- Editing a Dockerfile without preserving the local invariants above → the failure modes in the global skill's Monorepo / Docker Patterns section.
