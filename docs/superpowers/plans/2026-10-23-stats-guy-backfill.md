# Stats Guy Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task.

**Goal:** Reconstruct and validate one completed season before publication.
**Architecture:** Immutable HTTP evidence feeds pure ownership/valuation validation;
existing historical manifest and rating resolver produce the private preview.
**Tech Stack:** Python, httpx, Pydantic, pytest; Next.js notice.
**Spec:** `docs/superpowers/specs/2026-10-23-stats-guy-backfill-design.md`

## Global Constraints

- No paid calls, automatic imports, or current-career rating changes.
- Only complete Sleeper dynasty seasons with verified identities and standard TE scoring.
- 98% league / 90% team coverage, maximum two unranked players per team.
- Strict pre-cutoff source dates within seven days; immutable receipts.

## Review Focus

- Truncated boards must not turn missing pages into unranked players.
- Later transactions must not contaminate rosters or pick holdings.
- Current metadata must not substitute current ages into old ratings.
- K/DEF exclusions must be visible and must never affect historical Results.
- Sensitivity failure must prevent importable output.

### Task 1: Receipt and valuation policy

Files: new `api/app/services/historical_backfill.py`, tests in
`api/tests/services/test_historical_backfill.py`; extend historical asset schema.

- [x] Write failing tests for board completeness, dates, coverage, exclusions, and malformed data.
- [x] Implement immutable HTTP receipt client and pure asset policy.
- [x] Validate policy manifests and retain legacy imports.
- [x] Run targeted pytest and Ruff.

### Task 2: Reconstruction and private preview

Files: new `api/app/services/historical_backfill_run.py`, reconstruction tests.

- [x] Test roster reversal, earlier pick transfers, identity mismatch, incomplete records.
- [x] Collect chain evidence, reconstruct holdings, build bounded results, run rating sensitivity.
- [x] Write preview and importable manifest only after validation passes; offline replay supported.
- [x] Run real 2025 preview and verify offline determinism.

### Task 3: Reader disclosure and release verification

Files: rating scope models/services, `RatingScopeNotice`, methodology, documentation.

- [x] Expose source/date and excluded/unranked treatment without altering current scope.
- [x] Test API/UI metadata propagation; run tests, lint, typecheck and build.
- [x] Independent review and fix actionable findings; commit with mandatory skill gate.
- [x] Save validated private preview and publication runbook; deployment/import remain separate.
