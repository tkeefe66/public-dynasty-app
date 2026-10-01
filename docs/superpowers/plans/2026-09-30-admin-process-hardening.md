# Admin Process Hardening Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Steps use checkboxes for tracking.

**Goal:** Make every paid generation attributable, bounded, recoverable, and controlled by owner configuration across league variants.

**Architecture:** PostgreSQL stores the registry, policy, operations, attempts, receipts, and canonical artifacts. Existing writers become request builders behind a mandatory gateway. Refresh submits durable data work and publishes generation candidates; a separate worker admits eligible generation.

**Tech Stack:** Python/FastAPI, SQLAlchemy/asyncpg, Alembic, PostgreSQL, Next.js/TypeScript, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-admin-process-hardening-design.md`

## Global Constraints

- Owner-only administrative authority; no commissioner role.
- Dollar amounts remain deferred; preserve existing nonzero budget as an additional stop signal.
- Default paused; no production activation, migration, or deployment during local implementation.
- No direct provider SDK clients outside the managed transport; no SDK retries.
- Unknown provider execution never retries automatically. All receipts and legacy prose survive.
- Existing user, membership, grant, side-bet, archive, revision, and share data are preserved.
- Production concurrency proof uses PostgreSQL, not SQLite.
- One global and per-series paid request at launch, one repair, four Analyst calls maximum.
- CLI calls require authenticated administrative submission rather than a direct API key.

## Review Focus

- An old thread resumes after its lease expires: it must not publish or purchase another stage (tasks 2–3).
- Partial/malformed real league metadata must not qualify as dynasty capabilities (tasks 1, 4).
- HTTP accepted but response lost, or response received but durable persistence fails: no resend (task 3).
- Restore forgets post-snapshot calls, or old workers retain provider credentials: paid execution stays quarantined (tasks 7–8).
- Existing Analyst corrections and share bindings survive migration and publication replay (tasks 4, 7).

## Task 1: Typed policy, registry, and persistence

**Files:** Create `api/app/services/generation/{__init__,models,policy,registry}.py`, `api/migrations/versions/0009_generation_control.py`, `api/tests/test_generation_policy.py`; modify `api/app/db/models.py` and backup tests for new tables/types.

**Interfaces:** `Policy` is a strict Pydantic configuration with per-feature settings; `resolve_policy(session, series_id)` returns values, provenance, revision, and blocking reasons. `register_entry(session, entry)` maps provider season identifiers to verified series. All persistence uses existing session factories.

- [ ] Write failing policy tests: defaults paused; string booleans rejected; profile overrides cannot remove pause; optimistic settings revision rejects stale writes; missing capabilities block paid eligibility.

```python
def test_policy_rejects_truthy_string():
    with pytest.raises(ValidationError):
        Policy.model_validate({"paused": "false"})
```

- [ ] Run `pytest tests/test_generation_policy.py -q` from `api`; confirm the missing module/behavior fails.
- [ ] Add scalar-backed tables with JSON serialized into text where useful, unique semantic keys, immutable revision records, attempt usage in integer micro-USD, and explicit state columns. Seed global control paused in migration and bootstrap.
- [ ] Implement strict resolution, immutable audit events, compare-and-swap revision updates, and verified provider/season links; exercise captured league fixtures alongside malformed synthetic inputs.
- [ ] Re-run policy, identity, and backup schema tests; commit the persistence contract.

## Task 2: Durable operation ownership and commands

**Files:** Create `api/app/services/generation/{store,commands}.py`, `api/tests/test_generation_operations.py`, `api/tests/test_generation_postgres.py`.

**Interfaces:** `submit_operation(...)` returns existing or newly queued work; `claim_operation(session, worker_id)` returns an operation with an incremented lease generation; `require_owner(...)` gates all subsequent transitions. Commands cancel/hold/resolve using expected revision and audit reason.

- [ ] Write failing tests for semantic duplicate submission, client-key payload conflicts, stale lease rejection, cancellation retaining attempts, and coalescing only unstarted desired work.

```python
async def test_stale_owner_cannot_finish(store):
    old = await store.claim("worker-a")
    await store.expire_and_reclaim(old.id, "worker-b")
    with pytest.raises(OwnershipLost):
        await store.complete(old.id, old.generation, {"text": "late"})
```

- [ ] Run operation tests; implement transactional row locking, active keys, finite lease ownership, and explicit states.
- [ ] Exercise two independent PostgreSQL connections racing submission/claim; only one wins. Ensure lease expiry never settles an unresolved provider attempt.
- [ ] Commit only after concurrency and cancellation tests pass.

## Task 3: Mandatory provider gateway, accounting, and checkpoint replay

**Files:** Create `api/app/services/generation/{gateway,transport,accounting}.py`, `src/sleeper_dynasty/llm/managed.py`, and gateway tests; modify four writer constructors to accept managed clients.

**Interfaces:** `Gateway.invoke(operation_id, generation, stage_index, request)` replays a matching saved receipt or admits one physical call. `ManagedClient.messages.create(**request)` bridges synchronous writers to the owning async loop. `Transport.send(request)` returns raw status/body/headers; parsing follows durable receipt persistence.

- [ ] Write fake-HTTP tests for pause/admission races, accepted-then-disconnected response, malformed JSON with recorded receipt, lease loss during send, unknown price, and repeat invocation after receipt persistence.

```python
async def test_lost_response_is_not_retried(gateway, transport):
    transport.accept_then_disconnect = True
    await gateway.run_once()
    await gateway.recover()
    await gateway.recover()
    assert transport.physical_sends == 1
    assert await gateway.unknown_attempt_count() == 1
```

- [ ] Persist permit/counter under shared control lock before HTTP. Recheck actor, grants, epoch, ownership, and feature/series gates every send. Store raw receipt, normalized token dimensions, pricing snapshot, and usage before business parsing.
- [ ] Disable HTTP/SDK retries. Stop on errors; trip shared breaker after three terminal generation failures. Auth/accounting faults stop immediately. Late responses settle once without advancing a stale job.
- [ ] Reconstruct the exact SDK Message from a durable receipt when replaying a completed writer stage; mismatching request digests hold rather than resubmit.
- [ ] Run gateway tests against fake transport and PostgreSQL; mutate pause and unknown-outcome guards to verify named tests fail, then restore and commit.

## Task 4: Feature planning, artifacts, and complete writer migration

**Files:** Create `api/app/services/generation/{planner,features,artifacts,publication,worker}.py`; modify grader, story/blurb generation, Analyst generation/store/scheduler, and CLI.

**Interfaces:** Refresh emits immutable candidate snapshots containing feature, stable subject, semantic event, and validated facts. `plan_candidates(...)` imports prior prose and admits only approved future events. Worker runs existing writer against saved facts with managed client; `save_artifact(...)` uses expected head revision and queues archive projection.

- [ ] Write failing tests: schema deletion/prompt changes reuse prose; linked season imports deduplicate one historical trade; first activation proposes old content instead of buying it; weekly summaries coalesce; terminal subject failure remains held.

```python
async def test_cache_rebuild_never_repurchases(importer, planner, transport):
    await importer.import_saved_story("synthetic-trade", {"body": "saved"})
    await planner.rebuild_after_schema_change()
    assert transport.physical_sends == 0
    assert await importer.read_story("synthetic-trade") == {"body": "saved"}
```

- [ ] Remove production paid execution from GraderService and free Analyst fact collection. Preserve injected pure test writers while the default path only plans candidates. Stop shipping known-invalid fallback prose.
- [ ] Build feature-specific facts from existing helpers, serialize the request snapshot, and generate only through managed jobs. Analyst maximum is draft/review/repair/review; other features permit one targeted local-validation repair.
- [ ] Import archives and chain prose idempotently with legacy provenance. Save generated artifacts independent of chain schema. Make file projection replay compare stable artifact/revision/digest; conflict cannot overwrite a correction.
- [ ] CLI paid paths submit authenticated owner jobs or fail clearly; direct API-key-only commands cannot call the provider. All known SDK callsites have an enforceable guard test.
- [ ] Run feature, archive, CLI, artifact and cache-rebuild tests; commit caller migration.

## Task 5: Refresh submission, observation, and provider credentials

**Files:** Modify `api/app/routes/refresh.py`, `api/app/services/refresh_service.py`, `api/app/main.py`, `api/app/services/platform_client.py`, `web/lib/api.ts`, and refresh tests.

**Interfaces:** POST `refresh-jobs` returns a durable operation; GET job/status/events only reads. Worker re-resolves manual actor credentials or an explicit scheduler principal. Member progress never includes raw generation facts or receipts.

- [ ] Test GET creates zero work; two POSTs join; disconnecting subscription leaves job running; cross-league ID denied; revoking Yahoo manual user's grant cannot select another member.

```python
def test_legacy_get_does_not_execute(client, execution_spy):
    response = client.get("/api/league/synthetic/refresh")
    assert response.status_code == 410
    execution_spy.assert_not_called()
```

- [ ] Replace legacy GET with explicit upgrade response. Implement member-scoped job observation and bounded polling/SSE without owned task creation. Add backend worker loop independent of browsers.
- [ ] Scheduler submits deduplicated refresh work; free refresh reuse/cooldowns survive replicas and restarts. Update cold-cache and manual clients to POST then observe with a cancellable subscription handle.
- [ ] Run refresh, lifespan, auth, Yahoo, and frontend API tests; commit.

## Task 6: Owner API and admin interface

**Files:** Create `api/app/routes/generation_admin.py`, `web/components/admin/GenerationControl.tsx`, admin API functions and tests; modify admin page and settings cost responses.

**Interfaces:** Owner endpoints expose registry, effective policy/provenance, operations/attempts, audit, candidate previews/campaigns, cancellation and uncertainty resolution. Every mutation includes expected revision and reason; preview apply binds exact subject IDs and versions.

- [ ] Write tests for non-owner denial, stale settings/campaign conflict, consistent policy values across settings/admin/worker, and removed-member league visibility.

```python
async def test_stale_policy_form_is_rejected(api):
    revision = (await api.policy())["revision"]
    await api.save_policy(revision, paused=True)
    assert (await api.save_policy(revision, paused=False)).status_code == 409
```

- [ ] Implement typed route bodies, audited mutations, recovery actions with no implicit retry, and paginated diagnostic reads. Preserve configured nonzero legacy budget and expose unknown costs separately.
- [ ] Build admin controls for pause, profiles/overrides, league lifecycle, jobs, candidate preview/approval, audit, and explicit recovery. Show generation period/timestamp with saved prose.
- [ ] Run Vitest interaction tests, TypeScript, changed-file lint, and responsive UI checks; commit.

## Task 7: Backup, restore quarantine, and deployment contract

**Files:** Modify `api/app/services/backup_service.py`, `scripts/restore.py`, `api/Dockerfile`, dependency lock, CI; create a generation migration/reconciliation command and runbook.

**Interfaces:** Restore always invalidates execution epoch and starts quarantined; epoch is checked against a separately configured deployment value. Migration imports local artifacts without provider calls and returns counts/hashes/conflicts.

- [ ] Write restore test from before a fake provider completion; startup sends zero calls. Test all new tables round-trip through existing backup serialization, with artifact/revision checksums preserved.

```python
async def test_restore_never_reactivates(snapshot, restore, worker, transport):
    await restore(snapshot)
    await worker.tick()
    assert transport.physical_sends == 0
    assert await worker.hold_reason() == "restore_quarantine"
```

- [ ] Require generation credential removal/drain of old workers in deployment runbook; never claim new DB flags control old versions. Make Docker consume locked dependencies; run no-network fake-transport contract checks on the actual runtime.
- [ ] Implement idempotent import, fingerprints, visible conflicts, and restore epoch quarantine before worker startup. No automatic production migration/activation.
- [ ] Run migration/restore/backup tests; commit.

## Task 8: Full validation and independent review

- [ ] Run engine and API suites separately; PostgreSQL race/crash tests; web Vitest, TypeScript, lint, production build, and browser interactions.
- [ ] Map spec scenarios A1–A22 to executable tests; resolve any missing coverage before completion.
- [ ] Reconcile fake physical sends with attempt/receipt/usage/artifact counts. Verify no direct provider bypass and no production calls in tests.
- [ ] Dispatch a fresh whole-branch reviewer with the spec, this plan, diff, and progress ledger. Fix material findings with a failing regression test and rerun affected/full checks as appropriate.
- [ ] Commit verified fixes. Report exact branch, tests, remaining limitations, and production rollout steps; do not deploy without the confirmed service target.
