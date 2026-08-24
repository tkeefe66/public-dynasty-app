# Setup & Deploy

This is a multi-tenant web app: users sign in with Google, link Sleeper, import
their dynasty leagues, and get every trade graded. Three tiers in one repo:

- `src/sleeper_dynasty/` — the engine (Sleeper/KTC clients, grader, file cache)
- `api/` — FastAPI backend (auth, memberships, admin) + the engine
- `web/` — Next.js 14 app (App Router)

League analysis is cached globally by `league_id` on a disk volume; a Postgres
database stores only **identity** (users) and **memberships**. First importer of
a league pays the (one-time) LLM cost; everyone after reuses the cache.

---

## 1. Local development

### Prereqs
- **Python 3.11** (the engine requires ≥3.11 — macOS system `python3` is 3.9, use Homebrew's `python@3.11`)
- **Node 20+**

### Backend
```bash
# from the repo root
python3.11 -m venv .venv
source .venv/bin/activate          # do this in every new terminal
pip install --upgrade pip
pip install -e .                   # the engine
pip install -e ./api               # the FastAPI service

# create the identity DB tables (local default = SQLite under the cache dir)
cd api && alembic upgrade head
```

Create **`api/.env`** (same folder you run uvicorn from):
```
TRADE_GRADER_AUTH_BACKEND_SECRET=<32+ random chars, MUST match web AUTH_BACKEND_SECRET>
TRADE_GRADER_ADMIN_EMAILS=you@example.com
ANTHROPIC_API_KEY=sk-ant-...                 # optional; without it AI prose is skipped
# TRADE_GRADER_ALLOWLISTED_LEAGUE_ID=...      # optional rollout bridge (read-only)
```
Run it (from `api/`, venv active):
```bash
uvicorn uvicorn_entry:app --reload --port 8000
```

### Frontend
```bash
cd web
npm install
```
Create **`web/.env.local`**:
```
API_URL=http://localhost:8000
AUTH_SECRET=<openssl rand -base64 32>
AUTH_GOOGLE_ID=<from Google Cloud>
AUTH_GOOGLE_SECRET=<from Google Cloud>
AUTH_BACKEND_SECRET=<same value as api TRADE_GRADER_AUTH_BACKEND_SECRET>
AUTH_URL=http://localhost:3000
```
Run it:
```bash
npm run dev      # http://localhost:3000
```

> The three secrets are distinct: `AUTH_GOOGLE_SECRET` is from Google;
> `AUTH_SECRET` encrypts the session cookie; `AUTH_BACKEND_SECRET` is the shared
> key that signs the web→api token and **must be identical** in both `.env` files.

---

## 2. Google OAuth client (required for login)

Google Cloud Console → **APIs & Services**:
1. **OAuth consent screen** → External → add yourself under **Test users**
   (while unverified, only test users can sign in).
2. **Credentials → Create OAuth client ID → Web application**:
   - Authorized JavaScript origins: your web origin (`http://localhost:3000` and/or `https://<web-domain>`)
   - Authorized redirect URIs: `<origin>/api/auth/callback/google`
3. Copy the **Client ID** / **Client secret** into `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET`.

**To open signups to the public:** publish the consent screen (and complete
Google verification if prompted).

---

## 3. Production (Railway)

One project, **two services from this repo root**, selected by Dockerfile.
Do **not** set a root directory.

| Service | Dockerfile | Networking |
|---|---|---|
| `api` | `api/Dockerfile` | private, IPv6, `/data` volume |
| `web` | `web/Dockerfile` | public domain |

Add a **PostgreSQL** plugin.

**api service variables:**
```
RAILWAY_DOCKERFILE_PATH=api/Dockerfile
PORT=8000
TRADE_GRADER_DATABASE_URL=${{Postgres.DATABASE_URL}}   # auto-normalized to asyncpg
TRADE_GRADER_AUTH_BACKEND_SECRET=<random, matches web>
TRADE_GRADER_ADMIN_EMAILS=you@example.com
ANTHROPIC_API_KEY=sk-ant-...
# TRADE_GRADER_LLM_MONTHLY_BUDGET_USD=50       # optional; editable later in /admin
```
Mount a volume at **`/data`** on the api service. The api Dockerfile runs
`alembic upgrade head` on boot, so migrations apply automatically.

**web service variables:**
```
RAILWAY_DOCKERFILE_PATH=web/Dockerfile
PORT=8000
API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000   # or hardcode <api>.railway.internal:8000
AUTH_SECRET=<openssl rand -base64 32>
AUTH_GOOGLE_ID=...
AUTH_GOOGLE_SECRET=...
AUTH_BACKEND_SECRET=<same as api TRADE_GRADER_AUTH_BACKEND_SECRET>
AUTH_URL=https://<your-web-domain>             # MUST include https:// (no trailing slash)
AUTH_TRUST_HOST=true
LEAGUE_ID=<a default league id, optional>
```

### Gotchas (learned the hard way)
- **`AUTH_URL` must include `https://`** and be the public domain — a bare host
  crashes NextAuth middleware (`Invalid URL`).
- **`AUTH_TRUST_HOST=true`** is required behind Railway's proxy.
- **`API_URL` must resolve to a real host** (`http://host:8000`) — if the
  `${{api.*}}` reference is empty (api service not named `api`), hardcode
  `http://<api-service>.railway.internal:8000`.
- **Both services must auto-deploy from `main`.** In each service's Settings →
  Source, connect the repo + branch `main` so a `git push` rebuilds *both*. If
  only one is connected, the other silently serves stale code.
- The Postgres URL from Railway is `postgresql://…`; the app normalizes it to
  `postgresql+asyncpg://…` automatically.

### Verify a deploy
- Confirm **both** services' latest deployment is the commit you pushed
  (Railway shows the commit/message per deployment).
- `https://<web>/login` returns 200; sign in → lands on **My Leagues**.
- Add a league → it imports and renders; refresh progress streams to completion.
- `/admin` (as an `ADMIN_EMAILS` user) shows users (with their leagues, active-days
  + last-seen, and a per-user activity drill-down at `/admin/user/{id}`), leagues
  (with per-league activity), a product-usage section (active users DAU/7d/30d),
  LLM spend + budget editor.

---

## 4. Tests
```bash
cd api && pytest -v                      # backend
cd web && npm run test -- --run          # web unit (vitest)
```
