# Generation hardening verification

Automated checks use synthetic identities and fake provider transport. No paid provider request is needed. PostgreSQL races and migrations require the isolated `GENERATION_TEST_DATABASE_URL`; CI provisions it.

| Design scenario | Executable coverage |
|---|---|
| A1 — duplicate triggers | `test_generation_postgres.py::test_concurrent_submission_and_claim_has_one_winner`, `test_two_gateway_instances_cannot_send_the_same_stage`; refresh coalescing tests |
| A2 — observer disconnect | `web/tests/api.test.ts` polling/close tests; `test_generation_refresh.py::test_post_joins_job_and_observation_is_read_only` |
| A3 — late cancelled worker | `test_generation_gateway.py::test_late_cancelled_response_is_accounted_but_cannot_advance`; operation lease fencing tests |
| A4 — accepted request, lost response | `test_generation_gateway.py::test_lost_response_stays_unknown_across_recovery`; worker restart test |
| A5 — durable boundaries | Receipt persistence failure, saved receipt accounting replay, completed-stage recovery, and archive projection replay tests in generation adversarial/gateway/publication suites |
| A6 — changed approved content | `test_generation_worker.py::test_changed_content_cannot_reuse_validation`; existing Analyst review/repair tests |
| A7 — newer correction wins | `test_generation_publication.py::test_old_generation_cannot_overwrite_newer_owner_correction`; correction proposal CAS tests |
| A8 — cache/schema/fact changes | `test_generation_artifacts.py::test_legacy_prose_survives_cache_schema_and_fact_changes`; deleted-cache free refresh regression |
| A9 — pause/admission ordering | Native PostgreSQL `test_committed_pause_wins_against_waiting_admission`; stage pause and post-validation publication pause regressions |
| A10 — unavailable accounting | Receipt storage failure, unknown model pricing, malformed response, strict policy and unknown-usage tests |
| A11 — capabilities/phase | Strict policy fixtures, captured missing-format fixture, malformed Yahoo flag tests, historical scope and season-renewal regressions |
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
| A22 — abandonment/late receipt | `test_abandoned_unknown_receipt_settles_once_without_replacement` |

The built API image runs `scripts/check_generation_runtime.py` with Docker networking disabled: one fake HTTP call produces one immutable receipt, one priced attempt and one validated artifact; a second worker tick sends nothing. An invalid GM response test accounts for exactly two requests and publishes no artifact.

The matrix identifies coverage, not a claim that every possible process crash or provider behavior has been exhaustively explored. Production activation additionally needs backup fingerprints, matched API/Web commit verification, provider reconciliation and the semantic checks in the rollout runbook.

Owner controls were rendered with synthetic responses at 390px and 1280px, checked for horizontal overflow and inspected visually. Unit interaction tests verify partial policy writes, visible conflicts and exact preview approval. This is not evidence of production authentication or deployment.
