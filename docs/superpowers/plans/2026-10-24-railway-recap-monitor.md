# Railway recap monitor implementation plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution.

**Goal:** Run the existing eight-league weekly monitoring contract while the owner's computer sleeps, with bounded recovery and help-only email.

**Architecture:** Add a monitor task to the always-running Railway API, independent of the existing free-refresh scheduler. Postgres owns leases, next useful check, progress, and notification delivery. Existing generation commands and gateways retain all spending and publication authority. No coding agent or new AI provider is introduced.

**Tech stack:** Existing Python/FastAPI/SQLAlchemy, ZoneInfo, httpx, Resend REST delivery.

**Spec:** Owner-approved migration in this chat on 2026-10-24; original monitor requirements retained below.

## Global constraints

- Monday 22:30 America/Denver; validate games before edition audit, hourly incomplete follow-up, skip known gates, return weekly after completion.
- Use verified league-series mappings and scoring-period rules, including multiweek rounds and season completion. Operational identifiers belong in environment configuration.
- Four calls per normal Analyst job, stricter saved-job ceilings, $5 edition/$25 league-month combined limits. Never create replacement approvals, reset attempts/breakers, backfill, or resend ambiguous paid work.
- Recover only through existing audited controls and original owners/connections. Escalate code defects and unsupported recovery.
- Email existing owner only for unresolved blockers or approval; persist deduplication and provider idempotency. Never send routine progress, completion, or test email without separate authorization.
- Desktop monitor stays active until deployed cloud task and notification configuration are verified. No unrelated main-branch commits are pushed.

## Review focus

- Concurrent API replicas and restarts must not duplicate recovery or email.
- An unfinished/delayed game must defer before artifact or paid-work audit.
- A successful job alone must not count as delivered reviewed member content.
- Removed owner/connection, changed scope, unknown spend, exhausted calls must block recovery.
- Ambiguous email outcome must reuse its exact idempotency key only inside its provider window, then quarantine.

## Task 1: Durable schedule and alert state

Files: monitor models, migration 0021, monitor scheduling/state module, tests.

- [ ] Write failing tests for DST, gate prioritization, atomic due claim, stale lease rejection, alert dedup and cancellation.
- [ ] Implement persisted lease and progress with scope binding; validate before state changes.
- [ ] Test migration upgrade/downgrade and concurrent claims.

## Task 2: Read-only evidence and bounded recovery

Files: monitor evidence/recovery modules and tests.

- [ ] Write failing tests for incomplete inventory, multiweek gates, publication proof, exhausted/ambiguous allowances, same-job free retry, and recovery limits.
- [ ] Use qualified NFL inventory and completion evidence, existing provider clients/scoring-period functions, current job/artifact/outbox/archive records.
- [ ] Permit only existing audited resume/projection controls; persist a bounded recovery-attempt count, never alter paid allowances or safety holds.
- [ ] Run targeted monitor and existing budget/gateway tests.

## Task 3: Help-only mail and API lifecycle

Files: mail adapter, runner, config/lifespan integration, operations docs and tests.

- [ ] Write failing tests for zero mail on routine checks, unresolved-help-only payload, current owner binding, timeout/429/auth errors, idempotent retry and expired-window quarantine.
- [ ] Add opt-in API task, dry-run diagnostics, persistent delivery state and sanitized logs; no new public endpoint.
- [ ] Verify real email configuration without sending a synthetic alert.

## Task 4: Review, deploy and cut over

- [ ] Fresh independent review of recovery, concurrency and notification boundaries; resolve material findings.
- [ ] Run relevant tests, syntax/static checks and diff checks; commit through skill-candidate gate.
- [ ] Deploy only reviewed release commit to API; verify terminal Railway success, live revision and migrated schema.
- [ ] Initialize operational scope/floor and verify cloud loop checkpoint plus authenticated existing-owner browser publication checks; do not trigger AI for testing.
- [ ] Pause existing desktop automation only after cloud loop and email readiness are verified. State future-run and actual-email-delivery limitations explicitly.
