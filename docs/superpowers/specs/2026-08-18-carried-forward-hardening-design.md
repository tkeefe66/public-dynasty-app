# Carried-forward hardening — two fixes kept off the Outlook branch

**Date:** 2026-08-18
**Status:** design approved, **not implemented**
**Branch:** none yet — item 1 wants its own branch and its own review (see below)

Two defects found while working the Outlook redesign. Neither belongs to that change, and
one of them touches the auth boundary, so both were deliberately left out rather than
smuggled in beside a standings fix. This document is what they are, what was measured, and
what each fix costs.

They are unrelated to each other. Implement them as **two commits**, and item 1 as its own
branch.

---

## Item 1 — the login gate's route matcher is unanchored

### What is wrong

`web/middleware.ts` login-gates every page route. Its exemptions live in the matcher:

```ts
matcher: [
  "/((?!api/|_next/static|_next/image|favicon.ico|.*opengraph-image|.*twitter-image|.*icon).*)",
],
```

The last three exclusions are **unanchored substring matches**. `.*icon` matches any path
containing `icon` anywhere, not a path whose final segment is Next's `icon` metadata route.
So `/league/123icon`, `/leagues/addicon`, `/opengraph-image-anything`, and
`/admin/twitter-image-debug` all skip the middleware entirely, and Next renders the page
shell to an anonymous visitor.

`favicon.ico` is in the same list and is *also* unanchored, but harmlessly — it is a long
enough literal that no realistic route contains it.

### Measured exposure — state this honestly

The point of measuring is so nobody over- or under-reacts. Both readings are real.

**No current route is affected.** The full page-route inventory (`find web/app -name
page.tsx`) is:

```
/                          /league/[id]/draft
/account                   /league/[id]/draft/[season]
/admin                     /league/[id]/gm
/admin/user/[id]           /league/[id]/owner/[uid]
/leagues/add               /league/[id]/settings
/login                     /league/[id]/trade/[tid]
/methodology               /league/[id]
```

None contains `opengraph-image`, `twitter-image`, or `icon` as a substring. There is no
live bypass today.

**And no data leaks even if one existed.** A bypassed route renders the shell only. Every
`/api/*` call is refused for an anonymous caller by the proxy
(`web/app/api/[...path]/route.ts`) and again by `get_current_user` on the backend, and the
sessionless `og-card` scope is admitted only for GET/HEAD on four anchored path regexes in
`require_league_member`. Server components fetching through the proxy get 401s, so a
bypassed page renders empty chrome, not a league.

**The hazard is latent, and that is the whole case for fixing it.** The exposure is one
route name away. `/league/[id]/icons`, an `/admin/iconography` style guide, or any future
route whose name happens to contain those letters becomes publicly reachable **silently** —
no error, no warning, no test failure. Nobody adding a route reads the middleware matcher.
A defect whose trigger is "somebody picks a normal-looking route name" should not be left
armed because it happens not to have fired yet.

### Proposed fix

Anchor each exclusion to a **complete final path segment**, which is how Next actually
names metadata routes:

```ts
matcher: [
  "/((?!api/|_next/static|_next/image|favicon\\.ico|(?:.*/)?(?:opengraph-image|twitter-image|icon|apple-icon)(?:\\.\\w+)?$).*)",
],
```

Three changes, each load-bearing:

- `(?:.*/)?…$` requires the excluded name to be the **last segment**, so `/league/123icon`
  no longer matches while `/league/123/icon` still does.
- `(?:\.\w+)?` admits the extension form. The repo ships `web/app/icon.png` and
  `web/app/apple-icon.png` as static files, so `/icon.png` and `/apple-icon.png` are real
  request paths; `apple-icon` was missing from the exclusion list entirely and is added.
- `favicon\.ico` escapes the dot, which was previously a wildcard.

The four dynamic metadata routes that must keep bypassing the gate are:

```
web/app/league/[id]/opengraph-image.tsx
web/app/league/[id]/gm/opengraph-image.tsx
web/app/league/[id]/owner/[uid]/opengraph-image.tsx
web/app/league/[id]/trade/[tid]/opengraph-image.tsx
```

plus the static `web/app/icon.png` and `web/app/apple-icon.png`.

### This touches the auth boundary

A matcher edit is a one-line diff that decides which requests are authenticated at all.
Getting the regex *marginally* wrong in the other direction is worse than the bug: an
over-tight pattern bounces crawlers to `/login` and every unfurled link in the group chat
renders the fallback card instead of a real one — a silent product regression with no error
to notice.

Therefore:

- **Its own branch and its own commit.** Do not land it beside unrelated work; a reviewer
  must be able to see the auth change alone.
- **A real review, not a self-check.** This repo has an `adversarial-security-audit` skill
  for exactly this shape of change — run it against the diff rather than reasoning about
  the regex in the head that wrote it.

### Required test — both directions

A test asserting only that the metadata route still bypasses would pass on today's broken
matcher. A test asserting only that a substring path is gated would pass on a matcher that
gates everything. **Both directions are required, in one test file, or the test proves
nothing.**

Extract the matcher pattern into an exported constant so a unit test can compile it against
paths directly (`web/tests/` runs vitest; see `CLAUDE.md` for the config-path gotcha —
bare `npx vitest run` silently uses no config).

| Path | Must the gate run? |
|---|---|
| `/league/123/opengraph-image` | no — bypass |
| `/league/123/gm/opengraph-image` | no — bypass |
| `/icon.png` | no — bypass |
| `/apple-icon.png` | no — bypass |
| `/favicon.ico` | no — bypass |
| `/league/123icon` | **yes — gate** |
| `/leagues/addicon` | **yes — gate** |
| `/opengraph-image-debug` | **yes — gate** |
| `/league/123/opengraph-image/secret` | **yes — gate** |
| `/league/123` | yes — gate |
| `/admin` | yes — gate |

The four `/league/123icon`-shaped rows are the regression proof: run them against the
current matcher first and confirm they fail, exactly as a mutation check.

**The proposed pattern was checked against this table before this spec was written** — all
fourteen rows behave as tabulated, and the four hazard paths (`/league/123icon`,
`/leagues/addicon`, `/opengraph-image-debug`, `/league/123/opengraph-image/secret`) bypass
the gate under the *current* matcher and are gated under the proposed one. That is a
regex check, not a middleware check: it does not prove Next compiles or applies the pattern
identically, which is why the test above is still required rather than optional.

### Cost accepted

The matcher becomes harder to read, and a future metadata route type (Next adds them
occasionally) must be added to the alternation by name rather than caught by a loose
wildcard. That is the trade: an allowlist you must maintain, over a wildcard that silently
admits things nobody enumerated. It is the same direction the `og-card` path allowlist
already chose.

### Rejected alternatives

- **Leave it, since nothing is exposed today.** Rejected: the trigger is a route name, the
  failure is silent, and the fix is one line. "Not currently exploitable" is not a
  property anyone maintains on purpose.
- **Anchor with `$` alone (`.*opengraph-image$`).** Rejected: still substring-anchored at
  the front, so `/league/123opengraph-image` bypasses. The segment boundary is the
  property that matters, not the end of the string.
- **Drop the exclusions and let the middleware allow metadata routes explicitly in its
  body.** Rejected as strictly worse: it runs `auth()` on every crawler request, which
  costs a session decode per unfurl and moves the decision from a declarative config a
  reviewer can read into imperative code a reviewer must simulate.

---

## Item 2 — the engine test suite eats the developer's cache

### What is wrong

Running `pytest tests/` from the repo root destroys `~/.sleeper-dynasty/cache/`.

The mechanism, traced end to end:

1. `tests/test_cli.py::test_run_recap_builds_and_delivers` (`:11`) builds an
   `argparse.Namespace` with `no_cache=True` (`:46-50`) and pins `tmp_path` for `out` —
   **the output only**. Nothing pins the cache directory.
2. It calls `cli._run_recap(args)` (`:57`).
3. `cli.py:926` does `cache = FileCache()`. `FileCache.__init__` takes
   `cache_dir: Path = DEFAULT_CACHE_DIR` (`src/sleeper_dynasty/cache.py:17`), which is
   `Path.home() / ".sleeper-dynasty" / "cache"` (`:12`). This is the developer's real
   cache.
4. `no_cache=True` → `cache.invalidate_all()` (`cli.py:927`), which unlinks **every
   `*.json`** in that directory (`cache.py:48-59`). That is what removes the
   `chain_*.json` blobs.
5. The test's `get_players` stub then writes its two-player fixture back through the same
   cache under `_PLAYERS_CACHE_KEY = "players_nfl.json"` (`cli.py:65`).

Observed after a run: `players_nfl.json` is 131 bytes containing exactly the fixture from
`tests/test_cli.py:39-42` —

```json
{"p1": {"full_name": "Josh Allen", "position": "QB", "team": "BUF"},
 "p2": {"full_name": "Scrub", "position": "RB", "team": "NYJ"}}
```

— with the `chain_*.json` blobs gone alongside it. `identity.db` and the dated snapshot
subdirectories survive only because `invalidate_all` is deliberately restricted to
top-level `*.json` (`cache.py:51-56`); that restriction was written to protect the identity
database and is the only reason the damage is not worse.

### Why this is worth a spec rather than a one-line patch

It has already cost real time. During the Outlook session it silently destroyed a warm
cache mid-run, and a subsequent agent measured against the stale two-player substitute blob
and **reported a wrong conclusion**. The failure mode is not "the test is messy" — it is
"the test suite silently replaces the data another measurement is about to read, and the
substitute parses fine."

### The fix must be general

Patching `test_run_recap_builds_and_delivers` fixes the one test that was caught. Survey
first — this was measured, and the answer is that the exposure is broader than one test:

- **Three CLI entry points construct a bare `FileCache()`**: `_run_analysis` (`cli.py:416`),
  `_run_trades` (`:703`), `_run_recap` (`:926`). Any test reaching any of them, now or
  later, reaches the real directory. `_run_trades` additionally iterates
  `cache.cache_dir` directly (`:709`).
- **`tests/test_integration.py` is immune only by accident of a different concern.** It
  calls `_run_analysis` but patches `sleeper_dynasty.cli.FileCache` (`:95`) to assert on
  the mock, not to protect the developer's disk. Remove that assertion and the protection
  goes with it.
- **`tests/test_cache.py` is correct** — every case passes `cache_dir=tmp_path`.
- **There is no `tests/conftest.py` at all** in the engine suite, so there is nowhere the
  default is currently pinned.
- **The API suite has the same default and pins it in only five places.**
  `api/app/config.py:15` defaults `cache_dir` to the same real path, and only
  `test_lifespan.py` and `test_settings_llm_cost.py` set `TRADE_GRADER_CACHE_DIR` to a
  `tmp_path`. The remaining ~775 tests inherit the real directory. They happen to be
  read-mostly today, which is luck, not design.
- **`FileCache.__init__` calls `mkdir(parents=True, exist_ok=True)`** (`cache.py:19`), so
  merely constructing one touches the real home directory even when nothing is written.
- Adjacent, same family, out of scope here but worth knowing: `html_report.py:55` writes to
  `~/.sleeper-dynasty/reports/` from a module-level `REPORTS_DIR`.

**Decision: a session-level autouse guard, not a per-test fix.** The reasoning is that
this class of defect is invisible on a green suite — the test passed the whole time it was
deleting data — so the protection must not depend on anyone remembering to apply it to a
new test. A guard that covers the suite by default is the only version that holds as tests
are added.

### Implementation shape

The obstacle: `DEFAULT_CACHE_DIR` is bound as a **default argument value at function
definition time**, so monkeypatching `sleeper_dynasty.cache.DEFAULT_CACHE_DIR` from a
fixture does nothing to `FileCache()` calls. Two ways out, in preference order:

1. **Preferred — resolve the default at call time.** Change the signature to
   `def __init__(self, cache_dir: Path | None = None)` and resolve
   `cache_dir or DEFAULT_CACHE_DIR` in the body. Then a `tests/conftest.py` autouse fixture
   monkeypatches the module constant to a `tmp_path` for every test. This is a two-line
   production change that makes the constant genuinely patchable, which is what it reads as
   today and is not.
2. **Fallback — patch `FileCache.__init__.__defaults__`** from the autouse fixture, with no
   production change. Rejected as the default because it depends on a CPython
   implementation detail that no reader of `cache.py` would expect, which is the same class
   of surprise as the bug.

Mirror it in `api/tests/conftest.py` with an autouse fixture setting
`TRADE_GRADER_CACHE_DIR` to a `tmp_path`. `get_settings()` (`api/app/config.py:116`) is
**not** memoized, so the env var takes effect per call — verify that is still true when
implementing, because adding an `lru_cache` there later would silently defeat the guard.

### Required tests

- A test that constructs a bare `FileCache()` under the fixture and asserts
  `cache.cache_dir` is not `Path.home() / ".sleeper-dynasty" / "cache"`. This is the guard
  guarding itself; without it the fixture can be quietly broken by a refactor and the suite
  stays green — which is the exact failure the whole item is about.
- Keep `test_run_recap_builds_and_delivers` as-is otherwise. It is not the defect; it is
  the thing that happened to find it.

### Cost accepted

Any test that genuinely wants the real cache directory must now opt out explicitly. That is
the intended direction — an opt-out is visible in the diff, where the current implicit
opt-in is not — but it does mean a future integration test wanting real cached data needs a
line to say so. Additionally, if a fixture ever depends on a file already sitting in the
developer's cache, it will now fail rather than silently pass on one machine and fail on
CI. That is a fix, not a cost, but it may look like a new failure the first time.

### Rejected alternatives

- **Fix the one test (`cache_dir` wired to `tmp_path` in `_run_recap`'s args).** Rejected:
  three call sites and no conftest means the next test to touch the CLI reintroduces it,
  and this defect is invisible when reintroduced.
- **Have `invalidate_all` refuse to run against `DEFAULT_CACHE_DIR` when `PYTEST_CURRENT_TEST`
  is set.** Rejected: production code that behaves differently under test is a worse
  property than the bug, and it fixes only deletion — the fixture *write* that poisoned
  `players_nfl.json` would still land.
- **Move the default cache dir to a env-var-only setting with no filesystem default.**
  Rejected as out of proportion: it changes the CLI's user-facing behaviour for every
  installed user to fix a test-isolation problem.

---

## Item 1 — review corrections (adversarial security review, 2026-08-18)

The reviewer compiled both patterns through **Next 14.2.35's own** functions
(`getMiddlewareMatchers` -> `getMiddlewareRouteMatcher`) and cross-validated against a running
dev server on 16 paths, with live behaviour and harness agreeing on all 16. Five things must
change. The first is a factual correction to this spec; the second would take the site down if
the spec's own instruction were followed.

### 1. The bypass is LIVE on every dynamic route — not latent

This spec's "measured exposure" section inventoried only **static** route names and concluded no
current route contains the substrings. **Dynamic segments supply the substring.** Verified twice,
independently, against the running app, unauthenticated:

```
/methodology                302 -> /login      (gated, correct)
/admin                      302 -> /login      (gated, correct)
/league/123icon             200                (BYPASS)
/admin/user/1icon           200                (BYPASS)
/league/123/owner/u1icon    200                (BYPASS)
/league/123/trade/t1icon    200                (BYPASS)
/league/123/draft/2025icon  200                (BYPASS)
```

Every dynamic page route in the app has a live bypass right now. Unauthenticated requests reach
`generateMetadata`, the layout, and the page's server render, and cause outbound backend fetch
attempts — an unauthenticated compute-and-fetch surface on six route templates with unbounded
distinct URLs.

**Severity stays low, and for a better reason than this spec gave.** To bypass, the URL must
*contain* the substring, and every path parameter here is a numeric platform id (Sleeper ids are
all-digits; Yahoo's are `nnn.l.nnnnn`). So **a bypassing URL is necessarily a URL with a corrupted
id** — there is no bypassing URL that also names real data. That closes the leak question far
more firmly than "the API refuses anonymous callers", which the reviewer also verified
independently (proxy 401s with no session; RSC fetches attach no token; the `og-card` scope is
minted only in the four `opengraph-image.tsx` files and `get_current_user` 401s it outright).

Correcting this **strengthens** the case for the fix. Reframe from "latent, one route name away"
to "live on every dynamic route, non-leaking only because ids are numeric".

### 2. This spec's own required test would silently break the site — remove it

The instruction to "extract the matcher pattern into an exported constant so a unit test can
compile it" **must be dropped.** Next parses `export const config` from the AST at build time and
cannot resolve an identifier:

```
inline string literal          -> matcher extracted correctly
const MATCHER = "..." same file -> {} + warning
import { MATCHER }              -> {} + warning

WARNING: Unknown identifier "MATCHER" at "config.matcher[0]".
         The default config will be used instead.
```

"The default config" is the **catch-all** (`^/.*$`). Middleware would then run on everything:
`/api/*` would 302 to `/login` instead of 401 (breaking the proxy contract), all four og routes
would be gated (breaking every unfurl), and `/_next/static/*` would be gated for signed-out
visitors — breaking the login page's own assets. It is a **warning, not an error**: the build
succeeds and deploys. That is precisely the silent-failure class this item exists to close,
introduced by the item's own test.

**Replacement:** keep the literal inline in `config.matcher`; have the test read
`web/middleware.ts` from disk and drive it through Next's own analyzer. That proves three things
at once — the literal is statically extractable, Next compiles it, and the gate/skip verdicts are
right. Resolve the path against the **repo root**, not vitest's CWD (the gotcha
`furniture-rules.test.ts` already documents). Note a naive `new RegExp(matcher).test(path)`
disagrees with Next on `/api/health` and `/_next/static/x.js`.

### 3. Two latent breaks in the proposed pattern

- **Route groups.** Adding any route group above the four og files moves the URL to
  `opengraph-image-<6 chars>` (verified by running Next's generator), which
  `(?:\.\w+)?$` **gates**. Every unfurl silently becomes the fallback card.
- **`generateImageMetadata`.** Dynamic metadata routes register as
  `.../opengraph-image/[[...__metadata_id__]]/route`, so real URLs become
  `/opengraph-image/<id>` — also gated. Confirmed live that
  `/league/123/gm/opengraph-image/anything/deep` returns 200 image/png today.

Neither breaks today; both are one ordinary refactor away, which is the same argument this spec
uses to justify the fix at all.

### 4. The explicit allowlist alternative must be weighed, not omitted

This spec cites the `og-card` path-allowlist precedent while not taking it. The reviewer built
and tested the equivalent, which scores 25/25 on the full table — it keeps all six metadata
routes bypassing, **survives both the `-<hash>` and `/<id>` forms above**, and additionally gates
`/admin/icon`, `/league/123/settings/icon`, `/favicon.icons` and `/favicon.ico/secret`, which the
proposed pattern still admits. Cost: the four og routes are listed by path, so a rename must be
mirrored — which the required test would catch. Adopt it or explain why segment-anchoring beats
it; it currently dominates on every axis this spec cares about.

(Note the alternative "let metadata routes authenticate via the og-card principal" is **not
viable** — middleware runs before the route handler, so a gated og route 302s the crawler
regardless of what token the handler would mint. Worth one line so nobody proposes it later.)

### 5. State the residual class rather than presenting the defect as closed

Anchoring narrows the defect from "path contains `icon`" to "path's final segment is exactly
`icon`/`apple-icon`/`opengraph-image`/`twitter-image` (+ optional extension)". `icon` is a short,
plausible final segment (`/admin/icon`, `/league/[id]/settings/icon`). Separately, `favicon.ico`,
`_next/static` and `_next/image` are **prefix**-anchored under both patterns, so `/favicon.ico/secret`
and `/_next/static-leak/x` bypass either way — this spec calls that "harmless"; the accurate
statement is that a whole subtree bypasses. Also worth one comment line: `robots.txt`,
`sitemap.xml` and `manifest.webmanifest` would be **gated** by both patterns; none exists today,
and adding one later hands crawlers a `/login` redirect.

### Not verified

The proposed pattern was never placed in a running server (the reviewer was told not to modify
files), and all probes were `next dev`, not a production build. Do a live probe of the chosen
pattern at implementation time. `basePath`, `i18n` and `trailingSlash` would each change the
compiled regex; none is set today.

## Item 2 — review corrections (independent review, 2026-08-18)

The review verified every citation in Item 2 exactly — the mechanism, the three bare
`FileCache()` call sites, `test_integration.py`'s accidental immunity, the five API test files
that set `TRADE_GRADER_CACHE_DIR`, the non-memoized `get_settings()`, and the severity framing
all check out as written. Two changes are required before implementation.

### 1. The census missed a second, independent binding — and the proposed fix does not reach it

`api/app/services/grader_io.py:16` does `from sleeper_dynasty.cache import DEFAULT_CACHE_DIR, ...`
and `:346` uses it as a fallback:

```python
nfl_cache = FileCache(getattr(league_cache, "cache_dir", None) or DEFAULT_CACHE_DIR)
```

A `from … import` **copies the reference at import time**, so patching
`sleeper_dynasty.cache.DEFAULT_CACHE_DIR` — the engine-side fix this spec proposes — never
touches `grader_io.DEFAULT_CACHE_DIR`. And the API-side half (an autouse fixture setting
`TRADE_GRADER_CACHE_DIR`, i.e. `Settings.cache_dir`) does not reach it either, because this call
site bypasses `get_settings()` entirely.

This is the identical bug class Item 2 exists to close, one layer up, and **neither half of the
proposed fix closes it.** That matters especially because the spec's central argument is that a
general guard beats a targeted patch; a census that misses an instance the general guard cannot
catch undercuts its own case.

Verified as the **only** such instance: `grader_io.py:16` is the sole re-import of that constant
across `src/` and `api/`.

It is live but not yet destructive: `api/tests/test_grader_io.py:143` calls
`pull_supporting_data(...)` with `league_cache` omitted, so `getattr(None, "cache_dir", None)`
falls through to the real path. In that test `season_weeks` is empty, so `fetch_nfl_points`'s
write loop never fires and only `FileCache.__init__`'s `mkdir` touches the real directory. That
is luck, not design — one non-empty chain away from a real write. Production is safe
(`grader.py:590-592` always passes a real `league_cache`), so the exposure is test-only, which is
exactly this item's category.

**Required:** fix `grader_io.py:346` to source its fallback from `get_settings().cache_dir`
rather than re-importing the engine constant, as part of this item rather than deferred. That
also removes the redundant import.

### 2. The guard test does not cover that call site

The proposed guard — construct a bare `FileCache()` under the fixture and assert its `cache_dir`
is not the real path — is well aimed at the bug that caused the incident, and would catch a
future conftest fixture silently breaking. It cannot catch the `grader_io` variant, because that
call site never constructs a bare `FileCache()`; it always passes an argument, just the wrong one.

**Required:** add a second guard asserting `pull_supporting_data(..., league_cache=None)` (or
`fetch_nfl_points`'s cache resolution) never touches `Path.home()`.

### Noted, no change required

The review traced whether an autouse env-var fixture in `api/tests/conftest.py` could arrive too
late, given that file imports `app.main` at module scope and `create_app()` captures
`get_settings()` in a closure read by `lifespan()`. It is moot: the `client` fixture yields
`TestClient(app)` **without** `with`, so lifespan never fires for the route tests, and
`test_lifespan.py` sets the env var and calls `create_app()` itself afterwards, so it is already
isolated. Route-level resolution goes through `Depends(get_cache_dir)` per request and would be
correctly gated.

## Out of scope

- `~/.sleeper-dynasty/reports/` (`html_report.py:55`) has the same module-level home-directory
  shape. Not reached by any current test; noted so the next person recognises the family.
- The `og-card` path allowlist in `require_league_member` is **not** part of item 1. It is
  already anchored, and widening or narrowing it is a separate decision with its own
  exposure argument.
