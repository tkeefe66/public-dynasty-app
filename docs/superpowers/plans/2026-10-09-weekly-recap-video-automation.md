# Weekly Recap Video Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and publish complete, verified weekly Cal Mercer videos automatically, with editable admin budgets and reliable recovery.

**Architecture:** Extend the existing Postgres generation controller and API-owned publication flow. Use a dedicated Railway media worker with narrow authenticated work endpoints, no database credentials, and private immutable object storage. Preserve current volume-hosted media and the existing edition URLs.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy/Alembic/Postgres, httpx, boto3, Next.js 14/React/TypeScript, Linux Chromium, FFmpeg, pytest and Vitest.

**Spec:** `docs/superpowers/specs/2026-10-09-weekly-recap-video-design.md` (approved by Tom on 2026-10-09, including frontend cap controls).

## Global Constraints

- Earliest release is Tuesday at 08:00 in `America/Denver`, not a fixed UTC offset. Delayed games delay release automatically.
- Two identical canonical competitive-facts fingerprints at least 60 minutes apart.
- Video generation for one weekly episode, all revisions combined: $3.00; video per calendar month: $15.00.
- Written recap plus video for one weekly episode: $5.00; combined per calendar month: $25.00.
- These are intersecting ceilings, not additive allowances. Use USD integer units.
- Automatic generation and publication under standing policy after three reviewed weekly episodes pass qualification.
- No automatic paid retakes in the initial qualification phase.
- Fictional host Cal Mercer, The Gruff New Yorker, explicit `eleven_v4`, full-league coverage, useful variable length, approved animated-score visual design.
- No fallback voice, browser-driven unattended generation, Redis, separate scheduler, or general workflow framework.
- API owns source collection, prose, authorization, sharing and publication; media worker receives no ordinary DB or publication credentials.
- Exact voice/account qualification and deployment remain explicit release gates. No paid calibration, purchase, production setting change or deployment is authorized by this plan alone.
- Do not alter `AGENTS.md` or replace the approved ignored pilot artifacts. Real external IDs belong in protected configuration, never committed fixtures.
- Keep legacy numeric-stage prose receipts valid. No blind resend of an unknown provider outcome.
- Every public asset request checks current publication/share authority; no public bucket or presigned public redirects.
- Initial article revisions require reviewed media reattachment. Material contradictions withdraw affected content before paid correction.

## Review Focus

1. Month rollover during an uncertain charge must not free spending authority or move the same episode into a fresh allowance (Task 2).
2. An empty scoreboard or missing bracket response must hold, not become an all-final or no-game result (Task 4).
3. A stale settings tab must not overwrite newer limits or display another league's balances (Tasks 1 and 3).
4. Revocation between upload and publication, including after backup creation, must remain effective for new public reads (Tasks 9 and 11).
5. A correct caption over incorrectly spoken audio must fail qualification; a clipped ending must fail even if container signatures pass (Tasks 7 and 8).

## Execution and release shape

This is one dependent workflow, organized into three reviewable milestones:

| Milestone | Tasks | Independently testable result |
| --- | --- | --- |
| Budget controls | 1–3 | Persisted admin settings and backend reservations, with no media generation enabled |
| Offline production | 4–8 | Readiness, script, narration adapter and Linux rendering proven with synthetic inputs/saved approved audio |
| Publication and launch | 9–12 | Revocable DB-authoritative publication, corrections, recovery and a gated rollout |

Do not deploy an incomplete milestone as if automatic recaps are available. Keep
media policy disabled until explicitly qualified. The existing written recap
continues independently when media is unavailable. No subscription or hardware
purchase is hidden in an implementation step.

Use the current checkout for read-only discovery. Before product edits, follow
the worktree skill: preserve `.recap-pilot` in its current checkout, inventory its
hashes, and use a read-only reference or verified private copy from any isolated
worktree. Never commit raw pilot contents. Current planning base is `b693579` on
`codex/weekly-recap-redesign`; recheck Git and instructions at execution time.

Each task uses a failing behavioral test, implementation, passing test, review,
and logical commit. Immediately before each commit emit the mandatory
`Skill candidate: ...` line. Stage exact files, never unrelated changes.

## File ownership and interfaces

Paths below are repository-relative. Existing files are integration points;
new files keep the workflow from expanding the existing controller into a single
large module. The task interfaces are proposed contracts, not existing APIs.

| Area | Existing integration | New focused files |
| --- | --- | --- |
| Money | `generation/{policy,store,gateway,usage,accounting}.py` | `generation/recap_budget.py`, `generation/recap_models.py` |
| Admin | `routes/generation_admin.py`, `GenerationSettings.tsx`, `GenerationJob.tsx` | `routes/recap_admin.py`, `GenerationRecapBudget.tsx`, `GenerationRecapEpisode.tsx` |
| Readiness | `analyst_scheduler.py`, `analyst.py`, `generation/planner.py`, engine schedule/Sleeper adapters | `recap_video/{contracts,periods,readiness}.py`, engine `nfl_inventory.py` |
| Editorial | `llm/recap_packet.py`, existing published Analyst artifact | engine `recap_video_claims.py`, `llm/recap_video_writer.py`, `llm/prompts/recap_video.md` |
| Execution | `generation/{commands,worker,features,policy}.py` | `recap_video/workflow.py`, `routes/media_worker.py`, `auth/media_worker.py` |
| Provider/audio | existing receipt/accounting conventions | `recap_video/{elevenlabs,audio,storage}.py`, `media/worker.py` |
| Renderer | approved ignored v8 design | `media/render/{render.cjs,scene.js,index.html,style.css}`, `media/qa.py` |
| Publication | `generation/publication.py`, `analyst_media.py`, `analyst_shares.py`, public routes | `recap_video/{publication,corrections,retention}.py` |
| Ops | config, backup/restore, CI | `media/Dockerfile`, `media/package.json`, `docs/recap-video-operations.md` |

Service paths in the table live under `api/app/services/`; engine paths under
`src/sleeper_dynasty/`; frontend components under `web/components/admin/`.
Register new ORM classes in `api/app/db/models.py` so migrations and logical
backup metadata include them. Use the next free Alembic revision; the expected
sequence from the inspected base is `0011_recap_budget`, `0012_recap_workflow`,
`0013_recap_publication`. Rebase rather than collide with a newly added revision.

### Task 1: Persist budget policy and expose authenticated admin settings

**Files:** Create `api/app/services/generation/recap_budget.py`, `api/app/services/generation/recap_models.py`, `api/app/routes/recap_admin.py`, `api/migrations/versions/0011_recap_budget.py`, `api/tests/test_recap_budget_policy.py`. Modify `api/app/db/models.py`, `api/app/main.py`.

**Interfaces:** `RecapCaps` is a strict Pydantic model. `get_budget_view(db, series_id: str, episode_id: str | None, now: int) -> dict`; `save_caps(db, series_id: str, caps: RecapCaps, expected_revision: int, actor_id: str, reason: str, acknowledge_overcommitted: bool) -> dict`. These transactions share the admission lock from Task 2.

- [ ] **1. Write policy/API tests** using existing `admin_db`/auth override patterns. Unknown series is 404; nonadmin GET/PUT is 403; zero, negative, fractional integer units, booleans and unknown fields are 422. Two PUTs with one revision yield success then 409; GET returns saved values after a new DB session. Include an existing league with no policy row: defaults must be visible without GET mutating the database.

```python
from pydantic import ValidationError
import pytest
from app.services.generation.recap_budget import RecapCaps

def test_caps_are_inclusive_positive_integer_microdollars():
    caps = RecapCaps()
    assert caps.video_episode_microusd == 3_000_000
    assert caps.video_month_microusd == 15_000_000
    assert caps.combined_episode_microusd == 5_000_000
    assert caps.combined_month_microusd == 25_000_000
    for invalid in (0, -1, True, 1.2):
        with pytest.raises(ValidationError):
            RecapCaps(video_episode_microusd=invalid)
```

- [ ] **2. Run red:** from `api`, `uv run --frozen pytest tests/test_recap_budget_policy.py -q`. Expect the missing new module, then behavioral failures as implementation proceeds.
- [ ] **3. Implement caps and additive tables.** Reuse the existing strict model, `GenerationAudit` and admin dependency. Store `RecapBudgetPolicy(series_id PK, revision, caps_json, updated_at)`; no default activation or rewrite of existing global policies. Use microusd for all arithmetic and positive cents in the UI. Bound API integers to JavaScript's safe-integer range.

```python
from pydantic import Field
from app.services.generation.policy import StrictModel

class RecapCaps(StrictModel):
    video_episode_microusd: int = Field(default=3_000_000, gt=0, le=9_007_199_254_740_991)
    video_month_microusd: int = Field(default=15_000_000, gt=0, le=9_007_199_254_740_991)
    combined_episode_microusd: int = Field(default=5_000_000, gt=0, le=9_007_199_254_740_991)
    combined_month_microusd: int = Field(default=25_000_000, gt=0, le=9_007_199_254_740_991)
```

Add GET/PUT `/api/admin/generation/recap-budgets/{series_id}`; GET accepts optional
`episode_id`. PUT body includes `caps`, `expected_revision`, `reason`, and
`acknowledge_overcommitted`. Audit before/after values. Saving below obligations
returns a structured warning requiring acknowledgement; saving after acknowledgement
retains obligations and blocks new admissions. Use 409 on stale revision, not
silent last-writer wins. API responses include `revision`, `caps`, `episode_id`,
`month_key`, `balances`, `app_limit`, `enforcement_state`.

- [ ] **4. Run green and migration roundtrip** on disposable SQLite and Postgres, preserving seeded users, memberships and old receipt rows. Run `test_generation_admin.py` and `test_generation_migrations.py`. Commit `feat: persist editable recap spending limits`.

### Task 2: Reserve the complete authorized plan before spending

**Files:** Modify `recap_budget.py`, `recap_models.py`, `generation/gateway.py`, `generation/usage.py`, `generation/accounting.py`, `generation/commands.py`. Create `api/tests/test_recap_budget_ledger.py`, `api/tests/test_recap_budget_postgres.py`.

**Interfaces:** `reserve_plan(db, episode_id: str, series_id: str, plan_key: str, allocations: list[dict], now: int) -> str`; `settle_allocation(db, allocation_id: str, actual_microusd: int | None, evidence: dict) -> None`; `remaining_microusd(cap: int, known: int, reserved: int) -> int`. Allocation fields: `key`, `category` (`written`/`video`), `max_microusd`, `rate_snapshot`, `operation_id`. Physical attempts bind exactly one allocation; settlement is idempotent.

Define `episode_identity(series_id: str, season: int, period_id: str) -> str`
here using the existing canonical `digest([series_id, season, period_id])`.
Task 4 uses this same identity for its richer readiness row. Budget identity
therefore exists before the readiness module, without a circular dependency.

- [ ] **1. Write tests** for two workers racing to reserve the last allowance, duplicate plan keys, changed payload under the same key, late receipts after cancellation, unknown outcomes at month rollover, corrected episodes sharing the original identity, and a cap change racing admission. Use real Postgres test DB guard from `test_generation_postgres.py`; a skipped race test is not release proof.

```python
from app.services.generation.recap_budget import remaining_microusd

def test_unknown_reservations_are_not_free_budget():
    assert remaining_microusd(3_000_000, 1_000_000, 1_500_000) == 500_000
    assert remaining_microusd(3_000_000, 2_000_000, 1_500_000) == 0
```

- [ ] **2. Run red:** `uv run --frozen pytest tests/test_recap_budget_ledger.py tests/test_recap_budget_postgres.py -q` from `api`.
- [ ] **3. Implement ledger.** Add `RecapBudgetPlan` (unique episode/plan key and immutable digest) and `RecapBudgetAllocation` (unique plan/key, original month, outstanding ceiling, actual usage, evidence, attempt identity). Lock global control first, then league budget row, then allocation rows in stable order. Keep locks short; never make network calls inside them.

```python
def remaining_microusd(cap: int, known: int, reserved: int) -> int:
    return max(0, cap - known - reserved)

# Each admission checks video episode/month, combined episode/month,
# and any nonzero existing app-wide cap before committing allocations.
# An allocation transfers from reserved to known exactly once on settlement.
```

An unknown from an earlier month remains charged against that original window
and carries forward as outstanding exposure in current admission; settling it
removes only the carry-forward hold, not the historical charge. Episode spend
always spans all revisions and months. Expose carry-forward separately to avoid
mislabeling it as current-month invoiced usage. Additional correction work in a
new month counts in that month's allocation plus the original episode ceiling.

Bind existing written Analyst operations to a durable episode identity before
their first paid call. Backfill known current-period written charges by immutable
operation identity, never double count them in app totals. For historical unknown
costs, show their evidence state; do not reinterpret cancelled requests as free or
active jobs. If a relevant cost cannot be bounded, hold the new episode.

Calculate the complete bounded draft/review/repair/review plan using actual
request/token bounds, with uncached conservative pricing. Reject unsupported
tools/options or unknown rate dimensions. Exact prompt token counting or a
demonstrably safe upper bound must include serialization overhead; average
characters-per-token estimates cannot enforce a cap. Narration reserves all
allowed chunks using the final submitted character count and qualified rate.
Revalidate saved/current authority at each physical dispatch. Existing nonzero
app-wide ceilings must include reservations for all managed provider requests,
including non-recap jobs, so concurrent unrelated work cannot bypass them.

Ledger totals reconcile with `ProviderAttempt` rather than adding the same
cost twice. A receipt over its reservation stops further work and flags the
pricing error; already-incurred cost is recorded honestly. A cap increase only
reconsiders otherwise eligible budget holds, never unknown-outcome replacements.

- [ ] **4. Run green** plus `test_generation_gateway.py`, `test_generation_usage.py`, `test_llm_budget.py`, and real Postgres races. Temporarily remove the admission lock and confirm the overspend race test fails; restore it. Commit `feat: reserve recap spend before provider requests`.

### Task 3: Ship the editable frontend budget controls

**Files:** Create `web/components/admin/GenerationRecapBudget.tsx`, `web/tests/GenerationRecapBudget.test.tsx`. Modify `web/components/admin/GenerationSettings.tsx`, `web/lib/generation.ts`, `web/tests/GenerationControl.test.tsx`.

**Interfaces:** `GenerationRecapBudget({seriesId, episodeId, busy, version, run})` uses existing `ActionProps` behavior. `RecapBudgetView` matches Task 1; each balance has `scope`, `cap_microusd`, `known_microusd`, `reserved_microusd`, `uncertain_microusd`, `carry_forward_microusd`, `remaining_microusd`. Uncertain is a subset of reserved, not an additional subtraction.

- [ ] **1. Write UI tests** with mocked `generationRequest`: render four labeled inputs, edit/save/refetch, preserve unsaved values on server failure, render 409 conflict without overwriting, warn before saving below obligations, reject invalid money, and switch leagues while the earlier fetch is delayed. Use a full reload test with real API in the final milestone.

```tsx
// In the component test, mount with a successful synthetic GET response.
await user.clear(screen.getByLabelText("Video per episode ($)"));
await user.type(screen.getByLabelText("Video per episode ($)"), "4.50");
await user.type(screen.getByLabelText("Reason for budget change"), "Allow longer coverage");
await user.click(screen.getByRole("button", { name: "Save recap limits" }));
expect(generationRequest).toHaveBeenCalledWith(
  "/recap-budgets/synthetic-series",
  expect.objectContaining({ caps: expect.objectContaining({ video_episode_microusd: 4_500_000 }) }),
  "PUT",
);
```

Test setup imports `screen`/`render` from Testing Library, `userEvent`, and mocked
`generationRequest`; create `user = userEvent.setup()`. Supply synthetic league
and budget responses through the same mocks used by existing admin tests.

- [ ] **2. Run red:** from `web`, `npx vitest --config tests/vitest.config.ts run tests/GenerationRecapBudget.test.tsx`.
- [ ] **3. Implement visible settings** adjacent to Weekly Analyst for a selected league. Other scopes prompt selection of a league instead of editing ambiguous totals. Keep budget controls out of collapsed technical details. Label combined values as including video; show episode, Denver month dates, known/reserved/remaining totals and any tighter app-wide cap. The inactive rollout state explicitly says media automation is not enabled.

```ts
export function parseDollars(value: string): number | null {
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  const micro = cents * 10_000;
  return Number.isSafeInteger(micro) && micro > 0 ? micro : null;
}
```

Use explicit Save and server-confirmed success; the screen must not display
edited values as saved. Abort/ignore stale reads on league change. Link budget
holds to this selected-league panel. Preserve the existing four-feature bulk
automatic action; adding media later must not silently opt it into that action.

- [ ] **4. Run green**, targeted admin regression tests, `npx tsc --noEmit`, and `npm run lint`. Inspect narrow/mobile layout and keyboard labels. Commit `feat: expose recap budgets in admin AI writing`.

### Task 4: Establish durable episode readiness and playoff coverage

**Files:** Create `api/app/services/recap_video/{__init__,contracts,periods,readiness}.py`, `src/sleeper_dynasty/api/nfl_inventory.py`, `api/migrations/versions/0012_recap_workflow.py`, `api/tests/test_recap_readiness.py`, `tests/test_nfl_inventory.py`. Modify `src/sleeper_dynasty/api/nfl_schedule.py`, `src/sleeper_dynasty/api/sleeper.py`, `api/app/services/{analyst,analyst_scheduler}.py`, `generation/{planner,recap_models}.py`, `tests/test_nfl_schedule.py`.

**Interfaces:** `EpisodeKey(series_id: str, season: int, period_id: str)`; `ReadinessDecision(ready: bool, code: str, eligible_at: int, facts_digest: str)`; `evaluate_readiness(snapshot: dict, previous: dict | None, now: int) -> ReadinessDecision`; `observe_period(db, key: EpisodeKey, snapshot: dict, now: int) -> str`. `snapshot` has `expected_games`, `observed_games`, `schedule_revision`, `inventory_verified`, `participants`, `pairings`, `scores`, `starters`, `bracket`, `dispositions`, `facts_digest`, `observed_at`, `eligible_at`.

- [ ] **1. Write red cases**: Tuesday 07:59/08:00 across DST, observation 59/60 minutes apart, missing expected event, unknown/cancelled/postponed status without disposition, changed schedule revision, two unmatched owners, missing bracket fetch, a bye, placement game, tied game and an unfinished two-week final. Every failure asserts no paid submission. Add a rollover test retaining an already admitted period while new historical backfill remains held.

```python
from app.services.recap_video.readiness import evaluate_readiness

def test_empty_scoreboard_never_means_finished():
    result = evaluate_readiness({
        "expected_games": ["synthetic-game"], "observed_games": [],
        "inventory_verified": True, "eligible_at": 1,
    }, previous=None, now=2)
    assert not result.ready
    assert result.code == "schedule_incomplete"
```

- [ ] **2. Run red:** API readiness tests and engine schedule tests in their separate test roots.
- [ ] **3. Implement evidence and period records.** `RecapEpisode` has unique `(series_id, season, period_id)`, canonical `episode_id`, league/week/round/NFL-week membership, lifecycle, admitted-at, eligibility and source/article digests. `RecapObservation` retains immutable snapshot hashes, provider timestamps and source pointers. Preserve original decimal values as strings, not binary float arithmetic.

The expected game inventory must come from a verified season schedule obtained
independently of the current weekly scoreboard. Start qualification with the
nflverse schedule dataset (source link below); compare full-season/team coverage
and current week identities against a second schedule source. Persist the
qualified version, source bytes and event crosswalk. Do not introduce an R
runtime: use the upstream repository's documented machine-readable representation
after verifying its schema. If no representation can be qualified, emit
`schedule_inventory_unqualified` and complete offline work; never infer expected
games from the partial response being checked. This source choice is a technical
qualification gate, not proof of NFL-authoritative disposition.

Extend ESPN extraction to retain event IDs, completion/status, kickoff and source
errors without breaking existing weather/bye consumers. Schedule revisions reset
stability, and missing rows never delete an expected game silently. Fetch bracket
evidence with an explicit success/error distinction rather than the existing
empty-list-on-error helper. Build participant status from full roster inventory,
raw brackets and actual round rules; the existing title-path metric classifier
is not sufficient for coverage.

```python
# Readiness order: inventory validity -> exact expected-event coverage ->
# authoritative final/disposition -> participant/result evidence -> stable
# facts for 3600 seconds -> local Tuesday deadline.
# eligible_at is computed with ZoneInfo("America/Denver"), then stored as UTC.
# An observed_at field is never part of the competitive-facts hash.
```

Schedule this through the existing free collection cycle, with persisted due
times. Surface collector failures to the job rather than letting logged errors
become successful refreshes. Gate new weekly written publication on the same
readiness evidence for the enabled workflow; do not retroactively withdraw old
unrelated editions solely because the new collector has not observed them.

- [ ] **4. Run green** and `test_analyst_scheduler.py`, `test_generation_completed_period.py`, `test_generation_refresh.py`; verify season rollover and prior regular-season behavior. Commit `feat: gate recap episodes on complete stable results`.

### Task 5: Compile evidence-backed claims and the complete show script

**Files:** Create `src/sleeper_dynasty/engine/recap_video_claims.py`, `src/sleeper_dynasty/llm/recap_video_writer.py`, `src/sleeper_dynasty/llm/prompts/recap_video.md`, `tests/test_recap_video_claims.py`, `tests/test_recap_video_writer.py`. Modify `api/app/services/recap_video/contracts.py`, `generation/{features,policy}.py`.

**Interfaces:** `compile_claims(snapshot: dict) -> dict`; `validate_script(script: dict, claims: dict, published_article: dict) -> list[str]`; `RecapVideoWriter` consumes the existing managed gateway adapter and produces a structured script. Script shape: `segments[{id, owner_ids, matchup_ids, claim_ids, text, spoken_numbers}]`, `opening`, `closing`, `premises`. Claims contain exact decimal values, source IDs, scope and arithmetic operands.

- [ ] **1. Write tests** using a synthetic twelve-owner/six-matchup fixture, plus a playoff fixture containing inactive owners. Cover sums requiring more than three starters, a margin where rounding could flip the winner, legal single substitution versus optimal lineup, a fabricated injury claim, an invented personal anecdote, omitted owner and mismatch with corrected published prose. Review returns structured issues; unresolved issues cannot emit a publishable script.

```python
from sleeper_dynasty.engine.recap_video_claims import coverage_errors

def test_coverage_is_inventory_based_not_a_success_boolean():
    assert coverage_errors(["owner-a", "owner-b"], ["owner-a"]) == ["owner-b"]
    assert coverage_errors(["owner-a", "owner-b"], ["owner-b", "owner-a"]) == []
```

Define `coverage_errors(expected: list[str], covered: list[str]) -> list[str]`
in the engine claims module as sorted missing IDs. Keep full semantic validation in
`validate_script`; this coverage test alone does not prove quality.

- [ ] **2. Run red:** engine claim/writer tests. Do not mix root and API `tests` packages in one pytest process.
- [ ] **3. Implement typed facts and bounded writing.** Build from full snapshots, not the trimmed article packet. Require the published roast revision and acknowledged reader projection; operation success alone cannot satisfy this input. Use exact claims for graphics and recorded spoken variants for narration. Never feed provider-returned instructions into execution tools.

```python
def coverage_errors(expected: list[str], covered: list[str]) -> list[str]:
    return sorted(set(expected) - set(covered))

# Call order is fixed: draft -> review -> optional repair -> final review.
# Each call has an allocation from the single bounded script plan.
# A review failure after the allowed repair becomes an explicit hold.
```

The prompt preserves angry AM-radio delivery, natural profanity, football context,
varied transitions and a closing callback. Store a bounded recent-episode premise
history (latest six episodes) scoped to the league; retain all published scripts
but only include that compact history in prompts. Repeated catchphrases are
allowed; unexplained repeated joke structures are a review issue. Do not turn
estimated duration into a hard editorial truncation.

Register `recap_video` explicitly with disabled defaults and a fixed script call
contract. Keep ElevenLabs model fields separate from Anthropic writer model
validation. Existing policies missing the new feature stay disabled for it.

- [ ] **4. Run green** with `tests/test_recap_writer.py`, `tests/test_managed_generation.py` and API policy tests. Use local synthetic output for prompt snapshots; no paid call. Commit `feat: produce fully sourced weekly video scripts`.

### Task 6: Add fenced checkpoints and a restricted media-worker protocol

**Files:** Create `api/app/services/recap_video/workflow.py`, `api/app/services/generation/provider_control.py`, `api/app/routes/media_worker.py`, `api/app/auth/media_worker.py`, `media/worker.py`, `api/tests/test_recap_workflow.py`, `api/tests/test_media_worker_auth.py`, `api/tests/test_generation_provider_control.py`. Modify `generation/{commands,worker,gateway,administration,recap_models}.py`, `api/app/{config,main}.py`.

**Interfaces:** `claim_stage(db, worker_id: str, capabilities: set[str], now: int) -> dict | None`; `complete_stage(db, stage_id: str, generation: int, epoch: str, input_digest: str, result: dict) -> dict`. Work lease carries stage ID, generation, epoch, input digest, expiry, capability and allowed asset references. `run_stage(lease: dict) -> dict` in the worker handles only its registered stage kinds.

- [ ] **1. Write tests** for worker claims excluding API/source/prose/publication jobs, expired leases, stale completion after cancellation, changed input digests, duplicate completion, heartbeat loss, process crash between checkpoints and an unknown narration attempt. Assert a media credential gets 403 on admin/publication actions and on another lease's assets.

```python
from app.services.recap_video.workflow import worker_can_claim

def test_renderer_cannot_claim_publication():
    assert worker_can_claim({"render"}, "render")
    assert not worker_can_claim({"render"}, "publish")
    assert not worker_can_claim({"narrate", "render"}, "analyst_refresh")
```

Define `worker_can_claim(capabilities: set[str], kind: str) -> bool` as membership
in both the lease capabilities and the fixed media-stage allowlist.

- [ ] **2. Run red:** `test_recap_workflow.py`, `test_media_worker_auth.py` and existing worker tests.
- [ ] **3. Implement durable `RecapStage` and `RecapProviderAttempt` tables** in the workflow migration, preserving existing numeric `ProviderAttempt` semantics. Unique stage key is episode/revision/stage/chunk; each authorized replacement has a distinct attempt identity under the same episode budget. State progression:

```text
observing -> ready -> waiting_for_article -> scripting -> narration
          -> speech_check -> rendering -> media_check -> review -> published
Any stage -> held | needs_attention
Published -> withdrawn -> correction -> review -> published
```

API-owned stages orchestrate the existing queue; media stages are subordinate
checkpoint rows, not a second independent scheduler. Add capability filters to
claiming and explicit API-projector ownership to `drain()`. Lease heartbeat is
30 seconds with the existing lease interval; stale epoch/generation rejects
result selection while late receipts may still settle accounting.

Implement `/api/internal/media/{claim,heartbeat,complete}` plus lease-scoped asset
download/upload and provider-dispatch authorization. Use a dedicated service
credential mapped to a fixed worker capability set; never reuse backend user JWT
or DB credentials. API returns one-time dispatch authority only after durable
attempt admission and budget reservation. Restarted workers reconcile, never
reuse dispatch authority to send again. Bound all bodies, reject unexpected fields,
verify asset digests server-side, and keep user/share identities out of tokens.

Transient free stages retry at 1, 5 and 15 minutes, then need attention;
deterministic input failures wait for an input/policy revision. No stage loop
silently purchases another take. Log operation/stage IDs and transitions without
secrets or public share URLs.

Add `ProviderAccountControl(provider, account_key, hold, cooldown_until,
max_concurrency, revision)` with a unique provider/account key. The account key
is an internal configuration alias, never the raw external account identifier.
`require_provider_ready(db, provider: str, account_key: str, now: int) -> None`
checks that row and raises the existing `Held` exception with an explicit reason.
Copy legacy provider hold/cooldown into the configured Anthropic account during
migration; do not drop a live hold. Global emergency pause remains global.
Per-provider/account failures and concurrency must count attempts from the correct
ledger and must not put the other provider into cooldown. Preserve shared league
and aggregate spending constraints. Test ElevenLabs 401/429 while Anthropic work
continues, Anthropic failure while free rendering continues, independent accounts,
and global emergency stop blocking both paid providers. Audit scoped resets and
display the affected provider/account alias in admin recovery controls.

- [ ] **4. Run green** and real Postgres concurrent-claim tests; prove old refresh and prose workflows still work. Commit `feat: isolate durable media work behind restricted leases`.

### Task 7: Implement exact-voice narration and independent speech checks

**Files:** Create `api/app/services/recap_video/{elevenlabs,audio,storage}.py`, `api/tests/test_recap_elevenlabs.py`, `api/tests/test_recap_audio.py`. Modify `recap_models.py`, `media/worker.py`, `api/app/config.py`.

**Interfaces:** `preflight_voice(client, voice_id: str, model_id: str) -> dict`; `split_narration(segments: list[dict], max_chars: int = 2000) -> list[dict]`; `ElevenLabsTransport.send(request: dict) -> dict`; `verify_speech(script: dict, raw_transcript: dict) -> dict`. Audio result has request/history identity, immutable object hash/size, timing, metering evidence and outcome state, never generic JSON containing base64 audio.

- [ ] **1. Write mocked HTTP tests** for exact model/voice, 2,000-character chunks including tags, no split across protected number/unit or setup/punchline spans, missing credentials, unknown rate, 401, 429, timeout after send, invalid JSON, missing alignment, persistence failure, two returned variants and duplicate receipt. No automatic resend. Speech fixtures include incorrect number, negation, winner verb, omitted ending, duplicated chunk and documented name aliases.

```python
from app.services.recap_video.audio import verify_speech

def test_caption_text_cannot_hide_wrong_spoken_score():
    report = verify_speech(
        {"segments": [{"id": "s1", "text": "Won by fourteen points.",
                       "spoken_numbers": [{"value": "14", "spoken": "fourteen"}]}]},
        {"text": "Won by forty points.", "words": []},
    )
    assert report["passed"] is False
    assert "spoken_number_mismatch" in report["issues"]
```

- [ ] **2. Run red** without provider credentials or internet.
- [ ] **3. Implement direct transport** using httpx with implicit retries disabled and a bounded timeout. Preflight metadata and billing terms are read-only. Configure approved voice ID privately; send `model_id="eleven_v4"`, qualified settings and `output_format="mp3_44100_128"` to the documented dialogue timestamp endpoint. Do not assume editor stability/similarity controls map to the dialogue endpoint.

```python
request = {
    "model_id": "eleven_v4",
    "inputs": [{"voice_id": configured_voice_id, "text": approved_chunk_text}],
}
# configured_voice_id and approved_chunk_text come only from the bound lease.
# Reject dispatch if final text length or its qualified price exceeds allocation.
```

Keep API key only in the narration supervisor, never renderer subprocesses.
Persist request identity as soon as available. Decode/store response audio in a
private immutable object before final checkpoint success; if crash occurs before
storage, reconcile by exact retained provider identity. Balance changes cannot
identify a result. If retrieval is not uniquely possible, retain uncertain
exposure and require a bounded replacement decision.

Run independent local transcription with a pinned model artifact and checksum,
using the approved pilot's small.en approach as the starting point. Package the
model before runtime; do not let a renderer download it. Preserve raw words and
confidence data; aliases normalize orthography only. Forced alignment follows
speech verification and cannot fix a semantic mismatch. Missing or ambiguous
speech evidence holds. API availability and comparable full joined performance
remain calibration gates even when mocks pass.

Define `PrivateMediaStore` with `put_verified(key, bytes, sha256)`, `head(key)`,
`read_range(key, start, end)` and `delete_unreferenced(key)`. Reuse boto3 already
installed; API mediates worker object access through the restricted lease API.
Only API owns bucket credentials. Protect filesystem fallback from path traversal.

- [ ] **4. Run green** and mutation tests replacing numeric tokens and dropping a final sentence. Record that no paid media was generated. Commit `feat: add receipt-safe exact-voice narration`.

### Task 8: Port the approved visuals to reproducible Linux rendering

**Files:** Create `media/{__init__.py,Dockerfile,package.json,package-lock.json,qa.py}`, `media/render/{render.cjs,scene.js,index.html,style.css}`, `api/tests/test_recap_render_contract.py`, `scripts/check_recap_media_runtime.py`. Modify `.github/workflows/ci.yml`, `api/pyproject.toml`, `recap_video/contracts.py`, `media/worker.py`.

**Interfaces:** CLI `node media/render/render.cjs --episode <json> --output <directory>`; Python `measure_bundle(bundle_dir: Path, episode: dict) -> dict` in `media/qa.py`. Episode timeline binds claims, script, audio hash, timing, canvas geometry, fonts and renderer version. QA report carries measured durations, hashes, sync error, decode results and issue codes.

- [ ] **1. Write failing offline tests** for missing font/asset, overflowing caption, invalid time bounds, truncated MP4, wrong score graphic, absent final audio, sync error over 100 ms, duplicated chunk and cancelled render leaving children alive. Use short synthetic tone/video fixtures committed without personal data. A separate private pilot replay checks actual design parity.

```python
from media.qa import check_sync

def test_sync_limit_is_measured():
    assert check_sync(audio_start_ms=30, video_start_ms=0) == []
    assert check_sync(audio_start_ms=101, video_start_ms=0) == ["av_sync_exceeded"]
```

Define `check_sync(*, audio_start_ms: float, video_start_ms: float) -> list[str]`
using absolute difference greater than 100 ms. This sample tests the threshold;
integration tests must extract timestamps from actual decoded media.
Add the repository root to the API test pythonpath for the new `media` package,
after the API and engine paths so existing test-package precedence is preserved.

- [ ] **2. Run red** against the Linux image, not only macOS Chrome.
- [ ] **3. Extract reusable design** from current ignored v8 helpers with synthetic inputs, approved font licenses and unchanged visual direction. Expose `renderFrame(timeSeconds)` rather than realtime `MediaRecorder`. Capture frames using pinned Chromium/Playwright, then FFmpeg H.264/AAC muxing. Pin dependency/browser versions together and retain the lockfile. Avoid refactoring unrelated web design.

```js
for (let frame = 0; frame < frameCount; frame += 1) {
  await page.evaluate(t => window.renderFrame(t), frame / fps);
  await page.screenshot({ path: framePath(frame) });
}
```

Here `frameCount = Math.ceil(durationSeconds * fps)`, `fps = 30`, and
`framePath(frame)` is a zero-padded filename under the assigned scratch directory.
The frame function only reads validated episode data and packaged assets. Deny
all browser network requests and disable external protocol access in FFmpeg.
Give subprocesses an allowlisted environment, nonroot user and isolated network
namespace. Verify Railway runtime can enforce the isolation; if it cannot,
hold rollout until a supported equivalent is demonstrated.

Initial *qualification limits*, not measured production recommendations: one
render at a time, 20-minute deadline, 2 GiB process memory and 4 GiB scratch.
Benchmark the approved 137-second pilot and a synthetic four-minute episode;
adjust infrastructure limits from measurements before provisioning. Never shorten
content to make an unmeasured resource limit pass.

Measure full decode, media endings, audio sync, clipping/silence, caption layout
and representative first/transition/last frames. Store the raw measurements.
Reuse saved approved audio during the private pilot replay; do not regenerate it.
CI runs container QA with `--network none`, validates cancellation/cleanup and
ensures no environment secret appears in subprocess output.

- [ ] **4. Run green**, inspect synthetic and private pilot frames at phone size, compare scores/captions to bound inputs and record resource measurements. Commit `feat: render and verify recap videos in Linux`.

### Task 9: Make article, media and sharing publication authoritative in Postgres

**Files:** Create `api/app/services/recap_video/publication.py`, `api/migrations/versions/0013_recap_publication.py`, `api/tests/test_recap_publication.py`. Modify `generation/{recap_models,publication}.py`, `api/app/services/{analyst_media,analyst_shares}.py`, `api/app/routes/analyst_sharing.py`, `api/app/publish_recap_media.py`, `web/app/share/analyst/[token]/page.tsx`, `web/app/api/public/analyst/[token]/media/[bundle]/[asset]/route.ts`, `web/lib/recap-media.ts`.

**Interfaces:** `select_publication(db, episode_id: str, expected_revision: int, media_id: str | None, approval: dict) -> dict`; `authorize_public_read(db, token: str, bundle_id: str | None, now: int) -> dict`. One `RecapPublication` row binds article revision, facts digest, selected media, policy/approval revision, enabled/withdrawn status and authority revision. Separate persistent `RecapShareDecision` retains edition opt-out and league future-sharing permission.

- [ ] **1. Write race tests** for revoke during upload, article correction before media select, pause before projection, stale outbox replay, worker credential publication, guessed bundle and revoked GET/HEAD/Range. An article without ready video remains readable. Results-only/private packet is never returned. New article revisions hide old media pending reviewed attachment.

```python
# Extend existing public-media HTTP fixtures with a DB authority row.
def test_withdrawn_edition_does_not_serve_old_manifest(client, published_fixture):
    published_fixture.withdraw(reason="score_changed")
    response = client.get(published_fixture.media_url)
    assert response.status_code in (404, 410)
    assert "no-store" in response.headers["cache-control"]
```

Create `published_fixture` in this test module by adapting `test_analyst_media.py`:
it seeds a synthetic article/token/bundle and exposes `media_url` plus `withdraw`
which changes only the DB authority. Leaving the old file in place is essential.

- [ ] **2. Run red** with existing media/share/proxy tests.
- [ ] **3. Implement upload-before-selection.** Verify object bytes/hashes before a
short conditional transaction that rechecks source/article, current policy,
epoch, approval, opt-out, and sharing permissions. Global generation pause blocks
new selection; already published content remains readable unless explicitly
withdrawn/revoked/quarantined. API projector then installs reader projections;
only successful installation acknowledges the outbox.

```text
verified immutable upload
  -> lock authority + compare revisions + check permission
  -> select article/media pointer + increment authority revision + enqueue outbox
  -> install projection idempotently
public request -> current DB authority -> allowed immutable bytes
```

Backfill legacy share/media records in a dry-run-first migration command, keeping
tokens and volume bundles byte-for-byte. Missing or malformed legacy evidence
holds only that edition for operator review. Switch public reads to DB authority
only after reconciliation proves existing live shares match; never recreate a
revoked token. Legacy CLI publishing goes through the same authority service.

Support private bucket streaming with bounded single byte ranges, HEAD, 416,
client disconnect cleanup, no-store/nosniff headers and content disposition.
Preserve the existing slow-transfer behavior; metadata/header timeouts must not
abort healthy long downloads. Never redirect public clients to storage URLs.
Current DB outage fails closed with a retryable service error, not filesystem
fallback. Same URL shows correction status while an edition is withdrawn.

- [ ] **4. Run green**, local real HTTP page/media tests, exact hash comparisons,
phone playback/seeking/download, old pilot compatibility and PostgreSQL races.
Commit `feat: bind public recap reads to current publication authority`.

### Task 10: Add corrections, qualification and actionable admin recovery

**Files:** Create `api/app/services/recap_video/corrections.py`, `web/components/admin/GenerationRecapEpisode.tsx`, `api/tests/test_recap_corrections.py`, `api/tests/test_recap_qualification.py`, `web/tests/GenerationRecapEpisode.test.tsx`. Modify `recap_video/{workflow,periods}.py`, `routes/recap_admin.py`, `analyst_scheduler.py`, `GenerationControl.tsx`, `GenerationJob.tsx`, `web/lib/generation.ts`.

**Interfaces:** `observe_correction(db, episode_id: str, snapshot: dict, now: int) -> dict`; `record_preview_approval(db, episode_id: str, expected_revision: int, actor_id: str, evidence: dict) -> dict`; `qualification_status(db, series_id: str, season: int) -> dict`. Approval binds exact source/article/script/audio/QA hashes and provider/renderer qualification versions.

- [ ] **1. Write tests** for stat correction after publication, prior-week change affecting a later streak, a typo-only article revision still requiring media review, three approvals of one episode not counting as three episodes, new season invalidating qualification, changed voice/model/template requiring requalification, and disabled future sharing surviving weekly automation. Paid repair blocked by budget must not keep wrong content public.

```python
from app.services.recap_video.corrections import qualified_episode_count

def test_qualification_counts_distinct_successful_episodes():
    approvals = [
        {"episode_id": "e1", "passed": True},
        {"episode_id": "e1", "passed": True},
        {"episode_id": "e2", "passed": False},
    ]
    assert qualified_episode_count(approvals) == 1
```

Define `qualified_episode_count(approvals: list[dict]) -> int` as distinct IDs
whose current bound approval passed; DB-level qualification also checks season,
current versions, reconciled receipts and unchanged content.

- [ ] **2. Run red** API correction/qualification and frontend episode tests.
- [ ] **3. Implement due-based reconciliation** in the existing scheduler: every
15 minutes through Friday 23:59 Denver for the released episode, daily thereafter
through the season, and on relevant explicit refresh. Retain dependency edges
to prior result/standings/bracket snapshots. Update fingerprints and immediately
withdraw contradictory article/media authority in the same transaction that
records the correction. Propose repair against the original episode budget.

Admin displays episode, stage, exact failed evidence, known/reserved/uncertain
cost and recommended action. Provide review-and-publish, resume free work,
reconcile request, approve bounded replacement, skip video, restore access and
disable future sharing. Each action has current-state/revision checks and
specific spending/publication semantics. No generic paid Retry button.

```text
Budget hold: "Video needs $0.60; $0.40 remains" -> Edit recap limits
Unknown call: "Narration response missing; up to $0.32 reserved" -> Reconcile request
Correction: "Week score changed; public edition withdrawn" -> Review correction
Qualification: "2 of 3 reviewed episodes passed" -> Review finished preview
```

Keep initial preview approval one action per finished episode. After three
distinct fully qualified episodes, apply the already accepted standing policy
to that league/current season. Unknown playoff formats retain review. Deduplicate
attention events by episode/state/reason; unchanged polling produces no repeat
notification. Do not add email/text delivery or send messages without separate
authorization. Keep skipped video explicit while a valid article remains usable.

- [ ] **4. Run green** with scheduler and historical/catch-up regression tests.
Commit `feat: manage recap corrections and reviewed automatic rollout`.

### Task 11: Complete retention, private diagnostics and restore quarantine

**Files:** Create `api/app/services/recap_video/retention.py`, `api/tests/test_recap_retention.py`, `api/tests/test_recap_restore.py`. Modify `api/app/services/{backup_service,route_normalize}.py`, `generation/recovery.py`, `scripts/restore.py`, `api/app/main.py`, `api/Dockerfile`, relevant Web Sentry configuration and media routes.

**Interfaces:** `retention_candidates(db, now: int) -> list[dict]`; `reconcile_restore(db, manifest: dict, objects: dict) -> dict`; `redact_share_path(path: str) -> str`. Retention candidates are proposals; delete only after a second reference check under lock and a storage grace period.

- [ ] **1. Write tests** for failed takes at 89/90 days, unresolved take beyond 90
days, published master, backup-only referenced object, 7-day disposable frames,
orphan upload grace, stale deletion candidate gaining a reference, and a revoked
token restored from an older backup. Redaction tests cover access logs, exceptions,
telemetry, request breadcrumbs and query strings.

```python
from app.services.recap_video.retention import can_remove_failed_take

def test_unresolved_take_outlives_normal_retention():
    assert not can_remove_failed_take(age_days=120, unresolved=True, referenced=False)
    assert not can_remove_failed_take(age_days=120, unresolved=False, referenced=True)
    assert can_remove_failed_take(age_days=90, unresolved=False, referenced=False)
```

Define the helper above as the threshold plus no unresolved/reference guards;
the database deletion path must additionally recheck live and backup references.

- [ ] **2. Run red**, plus existing backup roundtrip/restore tests.
- [ ] **3. Implement retention and manifests.** Keep published/approved masters
until explicit removal; retain facts/scripts/receipts/QA for edition life; expire
failed/superseded takes after 90 days only if settled/unreferenced; frames after
7 days. Orphan uploads have a 7-day grace and are reconciled against pending
attempts/checkpoints before deletion. Backup manifests retain object keys/hashes
and revocation history through the recovery-point lifetime.

```text
restore database + required objects
  -> execution quarantine ON + public-serving quarantine ON
  -> reconcile hashes, current revocation evidence, budgets and epoch
  -> explicit reopening only after reconciliation passes
```

Store serving activation outside the restored database (deployment configuration
bound to a restore epoch), so a stale DB cannot reactivate itself. If newer
revocations cannot be recovered, affected older tokens stay disabled. Existing
downloads and already-started streams cannot be recalled; do not claim otherwise.

Use structured IDs instead of token paths in logs; filter Uvicorn/proxy access
logs and Sentry URL/breadcrumb fields. Do not disable all error logging. Maintain
`include_local_variables=False`. Verify private draft data and provider metadata
never appear in public response schemas, thumbnails or captions accidentally.

- [ ] **4. Run green** and a disposable backup/restore rehearsal with synthetic
objects and post-backup revocation. Commit `feat: preserve recap privacy and authority through recovery`.

### Task 12: Integrate, review and prepare the gated Railway rollout

**Files:** Create `docs/recap-video-operations.md`, `api/tests/test_recap_video_end_to_end.py`, `web/e2e/recap-admin.spec.ts`. Modify `.github/workflows/ci.yml`, `README.md`, `docs/recap-media.md`, `scripts/check_recap_media_runtime.py` and media deployment configuration.

**Interfaces:** Operations runbook consumes the exact settings, routes, stage
contracts and reports above. It records release commit, configured target service
names, migration state, qualification evidence and remaining holds; no secrets.

- [ ] **1. Add end-to-end acceptance** with a synthetic league, fake providers,
private test storage, real Postgres and the Linux renderer. Drive Tuesday
readiness -> written publication -> narration -> QA -> preview approval -> public
read; inject a crash at each boundary and prove completed paid work is reused.
Advance three distinct episodes to automatic mode, then correct/revoke/restore.
Exercise frontend edit/save/reload against real API enforcement, including a
request blocked by the newly lowered cap.

```text
Expected paid submissions: exactly those with unique admitted attempt identities.
Expected reader data: selected article/media hashes, never a private results packet.
Expected recovery: no second provider submission after ambiguous transport failure.
Expected settings: persisted cap controls affect the next admission transaction.
```

- [ ] **2. Run complete verification in separate roots:**

| Working directory | Command |
| --- | --- |
| repository root | `uv run --frozen pytest tests -q` |
| `api` | `uv run --frozen pytest -q` |
| `web` | `npx vitest --config tests/vitest.config.ts run` |
| `web` | `npx tsc --noEmit` |
| `web` | `npm run lint` |
| `web` | `npm run build` |
| repository root | `git diff --check` |
| repository root | `python3 scripts/check_publication.py` (with intended files staged) |

Use the existing disposable Postgres `_tests` guard. Record unrelated baseline
lint failures separately; do not silently waive newly introduced findings. Do
not add a global Python formatter/linter as unrelated scope; run any existing
configured Python checks discovered at execution time. Container runtime and
Playwright acceptance are additional to unit tests, not replaced by them.

- [ ] **3. Complete independent whole-branch review** appropriate to the chosen
execution method, fix findings, rerun affected checks and commit the complete
runbook/acceptance changes. All checks above must refer to the final commit.

- [ ] **4. Present the concrete release candidate before external changes.**
Confirm Railway target API, Web and new media worker with Tom before first
deployment. Include measured worker resource needs, private bucket access model,
exact voice entitlement/rate evidence and the bounded calibration request
(payload scope, provider, maximum cost and publication condition). No automatic
top-up, subscription purchase, credential creation or paid test is implicit.

- [ ] **5. After release authorization**, provision private storage/worker with
least privilege, back up and fingerprint existing data/shares, apply additive
migrations, deploy API/Web/worker with media disabled, and wait for each exact
commit deployment to reach terminal success. Reconcile legacy shares before
enabling DB-authoritative reads. Validate frontend budgets, live signed-out
legacy playback, new synthetic media, range/HEAD and revoked requests. Avoid
revoking the actual pilot just to test revocation.

- [ ] **6. After bounded calibration authorization**, test the approved voice,
multi-chunk seam and full joined delivery; reconcile actual charges/reservations.
Then qualify three reviewed episodes. Obtain actual recipient preview evidence
without sending messages on Tom's behalf unless explicitly authorized. Advance
to standing automatic operation only after all qualification evidence passes.

## Plan self-review and coverage map

| Specification section | Owning tasks |
| --- | --- |
| Accepted schedule/creative choices | 4, 5, 7, 8, 10 |
| Architecture and worker/storage ownership | 6, 7, 9, 12 |
| Period readiness and playoff status | 4 |
| Full-source claims and article consistency | 5, 9, 10 |
| Exact voice, transcription, captions, deterministic rendering | 7, 8 |
| Caps, reservations, unknown exposure, editable admin controls | 1, 2, 3 |
| Durable recovery and provider isolation | 2, 6, 7 |
| Publication, sharing, corrections and revocation | 9, 10 |
| Retention, backup and restore quarantine | 11 |
| Operator recovery and qualification | 3, 10, 12 |
| Phased release and account/resource gates | 7, 8, 12 |

Before handoff, check file references, all four approved cap values, interface
names across tasks, the five Review Focus cases and absence of unresolved
implementation placeholders. External qualification gates are deliberately
explicit holds; successful mock tests cannot be represented as account or
production verification.

## Technical references verified during planning

- [ElevenLabs dialogue with timestamps](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert-with-timestamps): explicit model, 2,000-character reliability recommendation, optional alignment and model-dependent continuity. Recheck before adapter implementation.
- [nflverse schedule documentation](https://nflreadr.nflverse.com/reference/load_schedules.html) and [upstream loader](https://github.com/nflverse/nflreadr/blob/main/R/load_schedules.R): a candidate independent season inventory, not a qualified production source yet.
- [Sleeper API](https://docs.sleeper.com/): raw matchups and brackets; platform-specific round interpretation still requires representative fixtures.

## Execution handoff

Recommended: **subagent-driven execution**, with one task implemented and reviewed
at a time, because money reservations and publication authority span several
interfaces and mistakes can incur charges or expose withdrawn content. Native
execution is also available with one final independent branch review. Neither
method changes the paid-calibration, deployment or publication qualification gates.
