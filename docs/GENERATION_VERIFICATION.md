# Generation hardening verification

Automated checks use synthetic identities and fake provider transport. No paid provider request is needed. PostgreSQL races and migrations require the isolated `GENERATION_TEST_DATABASE_URL`; CI provisions it.

Final local verification on 2026-09-30: **1,070 engine tests, 991 API tests (including native PostgreSQL races and migrations), and 865 web tests passed**. TypeScript, changed generation UI lint, generation-module Ruff, production web build, and the network-disabled locked API container contract passed. No production migration, deployment, activation or paid provider call was performed.

| Design scenario | Executable coverage |
|---|---|
| A1 — duplicate triggers | `test_generation_postgres.py::test_concurrent_submission_and_claim_has_one_winner`, `test_two_gateway_instances_cannot_send_the_same_stage`; refresh coalescing tests |
| A2 — observer disconnect | `web/tests/api.test.ts` polling/close tests; `test_generation_refresh.py::test_post_joins_job_and_observation_is_read_only` |
| A3 — late cancelled worker | `test_generation_gateway.py::test_late_cancelled_response_is_accounted_but_cannot_advance`; operation lease fencing tests |
| A4 — accepted request, lost response | `test_generation_gateway.py::test_lost_response_stays_unknown_across_recovery`; worker restart test |
| A5 — durable boundaries | Receipt persistence failure, saved receipt accounting replay, completed-stage recovery, and archive projection replay tests in generation adversarial/gateway/publication suites; `test_generation_review_recovery.py` covers artifact storage, shutdown and local accounting failure recovery with one physical send |
| A6 — changed approved content | `test_generation_worker.py::test_changed_content_cannot_reuse_validation`; existing Analyst review/repair tests |
| A7 — newer correction wins | `test_generation_publication.py::test_old_generation_cannot_overwrite_newer_owner_correction`; correction proposal CAS tests |
| A8 — cache/schema/fact changes | `test_generation_artifacts.py::test_legacy_prose_survives_cache_schema_and_fact_changes`; deleted-cache free refresh regression |
| A9 — pause/admission ordering | Native PostgreSQL `test_committed_pause_wins_against_waiting_admission`; stage pause and post-validation publication pause regressions |
| A10 — unavailable accounting | Receipt storage failure, unknown model pricing, malformed response, strict policy and unknown-usage tests |
| A11 — capabilities/phase | Strict policy fixtures, captured missing-format fixture, malformed Yahoo flag tests, historical scope and season-renewal regressions; `test_generation_completed_period.py` checks the final completed regular week remains eligible entering playoffs |
| A12 — stable series | `test_generation_policy.py::test_verified_season_renewal_inherits_series_hold`; legacy import identity and conflict tests |
| A13 — permissions | Owner API denial, force rejection, cross-league observation, Yahoo own-grant and revoked-admin tests |
| A14 — removed memberships | `test_remove_and_readd_last_member_keeps_series_held`; owner registry retention test |
| A15 — stale previews | Admin policy CAS and exact candidate/policy/head preview tests; frontend conflict/approval interaction tests |
| A16 — bypasses/retries | Static unmanaged-client guard, CLI rejection tests, production HTTP transport retry check, receipt parser and outbox replay tests |
| A17 — old snapshot | `test_generation_restore.py::test_restoring_pre_call_snapshot_cannot_repeat_paid_work` |
| A18 — old workers/rollback | Activation requires stopped-worker acknowledgement; restore rejects old epoch even after pause. Actual credential revocation and old-process drain require the operational checks in `GENERATION_ROLLOUT.md`. New software cannot inspect or control every legacy process. |
| A19 — migration/archive fidelity | All-table logical roundtrip, idempotent legacy import, PostgreSQL additive migration and original/revision projection tests; existing Analyst share tests |
| A20 — flood/cooldown | PostgreSQL concurrent submissions, refresh cooldown, no-side-effect GET, rotating bounded candidate scan, real HTTP transport shared 429 cooldown |
| A21 — shared breaker | `test_shared_breaker_survives_new_worker_and_blocks_next_subject` |
| A22 — abandonment/late receipt | `test_abandoned_unknown_receipt_settles_once_without_replacement`; `test_settled_late_receipt_resumes_original_authorization_without_repurchase` checks settlement audit, original authorization reuse and zero additional calls |

The built API image runs `scripts/check_generation_runtime.py` with Docker networking disabled: one fake HTTP call produces one immutable receipt, one priced attempt and one validated artifact; a second worker tick sends nothing. An invalid GM response test accounts for exactly two requests and publishes no artifact.

The matrix identifies coverage, not a claim that every possible process crash or provider behavior has been exhaustively explored. Production activation additionally needs backup fingerprints, matched API/Web commit verification, provider reconciliation and the semantic checks in the rollout runbook.

Owner controls were rendered with synthetic responses at 390px and 1280px, checked for horizontal overflow and inspected visually. Unit interaction tests verify partial policy writes, visible conflicts and exact preview approval. This is not evidence of production authentication or deployment.

## Independent review

A fresh reviewer examined the complete branch against the design, including PostgreSQL fencing, malformed metadata, lost responses, restore quarantine and archive preservation. It reported three important findings and no critical or minor findings. Each finding was reproduced by a failing test before its fix:

- Local artifact/receipt persistence failure and graceful shutdown now hold work for explicit recovery. Completed stages replay without another physical request; consumed calls and the original authorization remain unchanged.
- A successful late receipt clears provisional transport errors, retains the previous state in an audit event and permits explicit recovery of the original job. Cancellation and restore fences remain effective.
- Verified completed-week evidence is stored separately from the dashboard phase. The final regular-season week remains eligible when the league enters playoffs; the dashboard still displays its postseason content.

## Implementation decisions

- Execution remains local and reviewable. The build request approved implementation; production migration, deployment and activation require the rollout sequence. If that scope is narrower than intended, release remains a separate step.
- Authorization and job state share one operation table; physical attempt and stage checkpoint share one receipt record. Unique keys and immutable receipts preserve the contracts. A future split can be additive if these responsibilities diverge.
- Automatic summaries and Analyst cover only the latest completed regular week; new trade eligibility expires after seven days. Older or missed content needs an exact reviewed campaign, so late discoveries can require owner intervention.
- Legacy injected writers remain for isolated tests. API-key-only CLI generation is blocked and directs operators to admin jobs; old CLI callers must change workflows.
- Job observation uses two-second bounded GET polling with the existing closeable interface. Progress can lag by two seconds; disconnecting does not cancel work.
- Restore retains the backed-up epoch as comparison evidence while quarantining all paid work. Activation requires a different externally configured epoch. Legacy import requires provider-registered identities and reports missing mappings; free refresh and review may be needed before import can finish.
- Hard dollar caps remain deferred by explicit user choice. Call, concurrency, eligibility and retry limits are active controls, but they do not promise a universal currency ceiling.
- Actual legacy-process termination, credential revocation and production backup fidelity were outside local review. The rollout runbook requires those checks before activation; local tests cannot prove them.

No review findings were deferred as minor work. Existing grader lint debt remains outside this change: final review reduced its diagnostic count from 22 to 21, with no new diagnostics; the generation modules and added recovery tests pass Ruff.
