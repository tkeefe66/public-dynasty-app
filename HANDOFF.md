# Cold-start handoff — Yahoo redraft/keeper adapter

**Status 2026-08-11: ingestion half shipped (Tasks 1–5). Tasks 6–9 are hard-blocked
on Yahoo granting Fantasy API access. Nothing is in flight.**

The four open questions this file used to ask have all been answered — see
"Decisions" below. The missing artifact is no longer a plan; the plan exists at
`docs/superpowers/plans/2026-08-11-yahoo-ingestion-protocol.md` and its first
five tasks are merged.

**Read first, in order:**
1. repo `CLAUDE.md` — the "Platform ingestion protocol" and "Yahoo adapter —
   blocked" bullets are the current state of this work
2. `docs/superpowers/plans/2026-08-11-yahoo-ingestion-protocol.md` — the plan.
   Its "Blocker" section at the top explains the Yahoo entitlement gate; its
   "Two corrections to the design spec" section explains where the design is wrong
3. `docs/superpowers/specs/2026-08-11-yahoo-adapter-design.md` — the original
   design. **Two of its claims are false**; the plan says which

## The blocker

**Yahoo Fantasy Sports is a restricted API.** Registering an app at
`developer.yahoo.com/apps/create` is not sufficient — it needs a separate access
application at <https://sports.yahoo.com/developer/access/>, submitted
2026-08-11, approval time unknown.

Symptoms, so this is not re-diagnosed: no Fantasy Sports checkbox on the app
form; `?error=invalid_scope` when requesting the documented `fspt-r` scope;
and a valid token that 401s with `oauth_problem="additional_authorization_required"`
on **`/game/nfl`** — a public metadata endpoint. That last detail is the proof
it is app entitlement, not scope and not the token.

**The day access is granted, resume at Task 5 Step 1** (record fixtures), then
Tasks 6–9. The tooling is written and works as far as the entitlement allows:

```bash
set -a; source api/.env; set +a
python3 scripts/yahoo_dev_token.py       # token + your league keys
python3 scripts/record_yahoo_fixtures.py # writes tests/fixtures/yahoo/
```

Two tests in `tests/test_yahoo_json.py` **skip** until fixtures exist. They must
pass before any adapter mapping is written — that discipline caught several
wrong assumptions already.

## Decisions (do not re-ask)

- Yahoo **replaces** MFL as the next platform. **Redraft and keeper only.**
- **Background refresh is required**, and it is the reason the auth half exists.
  Yahoo data is private, so unattended refresh is impossible without a stored
  refresh token — there is no on-demand design that preserves the warm cache.
  This reversed an earlier on-demand answer; do not re-litigate it.
- **Refresh tokens are stored encrypted**: Fernet envelope, key from a Railway
  env var, `key_version` column for rotation. Not pgcrypto, not plaintext.
- **Sleeper was refactored onto the shared protocol first**, so there are two
  implementations of one interface rather than one plus a special case. Done.
- **A revoked connection shows a stale band with cached data still visible** —
  a league only goes stale when *every* connected member's token is dead, since
  any member's token can read the whole league.
- **Leagues stay self-contained.** Nothing pooled or ranked across leagues. The
  cross-league grade is separately specced and deliberately unbuilt.
- Skills are never created unprompted; propose with a `Skill candidate:` line.

## What shipped (merged to main)

Tasks 1–5. The first three improve the Sleeper path on their own merits and are
live in production regardless of whether Yahoo ever ships:

- `League.format` replaced the Sleeper-specific `league_type` int on the
  platform-neutral domain model — `derive_capabilities` now holds no platform
  knowledge, which is the fix this handoff originally predicted would be needed
- `LeaguePlatform` protocol + id-shape routing (no migration, no new column)
- `SleeperClient` moved behind it, deleting `grader_io`'s reach-through into the
  private `client._client`. **Two regressions were introduced and fixed during
  this refactor** — a 2× transaction-request amplification and a lost
  `asyncio.gather` — both caught by existing call-counting tests, not new ones
- `yahoo_id` → `sleeper_id` crosswalk (5,319 pairs after filtering R's `"NA"`)
- Yahoo JSON unwrapping primitives + the fixture recorder

## The auth half is not planned yet

Deliberate. Plan 2 (OAuth flow, `yahoo_connection` record, Fernet storage,
scheduler integration, reconnect UI) should be written **after** a working
adapter, so it is shaped by real requirements. It is now doubly blocked — write
it only once ingestion actually reads a Yahoo league.

**Run `adversarial-security-audit` before shipping any of the auth half.**
Storing third-party OAuth refresh tokens is the first genuinely
credential-holding thing this app would do.

## Verification (bare invocations break — see CLAUDE.md)

```bash
pytest tests/                  # engine. NEVER bare `pytest` from root:
pytest api/tests/              #   api/tests and tests/ are both packages named "tests"
cd web && npx tsc --noEmit
cd web && npx vitest --config tests/vitest.config.ts run
```

Green baseline at merge: **engine 566 (+2 skipped), api 482, frontend 329, tsc clean.**

## Process conventions

- Explicit-path `git add` — never `git add -A` (another worktree shares this
  repo; see `git worktree list`).
- A `Skill candidate: <name> - <desc>` or `Skill candidate: none.` line
  immediately before every commit.
- Push to `main` **auto-deploys both services** on Railway. Confirm
  `railway status` shows `public-dynasty` first. Poll deploys by **commit
  message**, not bare status — a check right after a push reads the *previous*
  deployment and will lie to you.
- `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` trailer.

## Delete this file when the Yahoo build lands or is abandoned

If Yahoo denies access, delete it and remove the "Yahoo adapter — blocked"
bullet from `CLAUDE.md`. A handoff that outlives its project misleads the next
cold start. Precedent: `be83705`.
