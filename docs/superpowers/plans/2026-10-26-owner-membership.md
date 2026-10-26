# Owner membership implementation plan

**Goal:** Separate former owners from default current-owner lists while preserving every historical record and exposing consistent status across the app.

**Approved design:** User approved current/former/unverified status, separate former owners, preserved history, and consistent labels on 2026-10-26.

**Architecture:** Derive membership from the newest season's roster assignments after canonical owner resolution. Extend the shared OwnerRef response; do not mutate historical caches, owner mappings, rating inputs, or authorization memberships. Missing or incomplete latest rosters cannot establish former status.

**Tech stack:** Python/FastAPI, TypeScript/React, pytest/vitest.

## Constraints and review focus

- Same rules for Sleeper/Yahoo and dynasty/keeper/redraft.
- Returning owners keep identity and history; names and roster slots do not establish identity.
- New season or missing roster data must not label everyone former.
- Season-filtered historical views retain that season's participants.
- Current-list rank is within the displayed population; all-time history remains explicitly accessible.
- Former profiles, historical trade sides, and head-to-head opponents carry the same status.

## Tasks

- [x] Add regression tests for complete/incomplete rosters, aliases, returners, unknown owners, season selection, and preserved historical profiles/trades.
- [x] Add pure `owner_membership(entry, uid)` resolver and shared OwnerRef fields; propagate to trade side responses.
- [x] Add shared status label and membership filtering helpers. Separate Owners rail with current default and former section; apply current/all-owner controls to career ledgers and rankings without filtering historical seasons.
- [x] Test UI selection, former navigation, ranks/counts, and labels. Run affected API/frontend suites, lint and TypeScript checks.
- [x] Review changes, fix findings, document verification, and commit on feature branch.

## Execution notes

User explicitly authorized implementation; execute inline without another approval gate. Existing clean checkout moved from main to `codex/owner-membership-status`. No deployment requested.


## Verification

- 126 affected API tests passed, covering owner/trade/dashboard responses, identity links, roster ranks, and historical season ratings.
- Full frontend suite: 1,037 tests across 113 files passed.
- TypeScript no-emit check passed; Next lint passed with the pre-existing DashboardClient effect-cleanup warning.
- Synthetic browser QA at 390px and 1280px: 10 default owner links, 3 former owners behind disclosure, former profile selection and collapse fallback working, zero horizontal overflow. Temporary QA route removed and server stopped.
- Mutation probe changed former classification to current; all three format regression cases failed. Restored source byte-for-byte and reran API tests successfully.
- Independent review findings fixed: missing draft helper import, ambiguous mobile bet labels, and missing status in bet/profile selectors.
- No production deployment or live Dads membership verification performed. No cache data or historical records modified.
