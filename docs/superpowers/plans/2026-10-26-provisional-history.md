# Provisional historical ratings implementation plan

> For agentic workers: use superpowers:executing-plans for implementation. Independent UI and collector changes may be delegated with explicit interfaces.

**Goal:** Rate verified later seasons without treating unresolved earlier history as complete.

**Architecture:** Keep the existing full Results/Assets formula. Persist a versioned, source-bound Results coverage manifest separately from asset evidence. The historical builder applies this manifest before deriving Results; its included and excluded seasons become part of the rating provenance and digest. API and shared UI disclose provisional status.

**Tech stack:** Python/FastAPI/Pydantic, pytest; TypeScript/Next.js, Vitest.

**Spec:** User-approved conversation: exclude whole unresolved seasons consistently, list missing history, require verified selected-year results and assets, never replace missing evidence with zeros or current values.

## Constraints and review focus

- Selected year cannot be excluded. No usable evidence means no rating.
- Source, identity, or membership changes invalidate an imported policy rather than silently promote it to verified.
- Full raw history and transaction ledgers stay intact; Results exclusions must not remove pick transfers.
- Weekly PF/PA approvals remain exact and audited. Wins/losses and postseason discrepancies are excluded, never repaired by policy.
- Same included season set applies leaguewide. Actual year gaps retain recency decay. No historical trend comparisons.
- Existing fully verified snapshots and current career ratings retain their behavior.

## Tasks

- [x] Collector: explicit exclusions, independently validated included years, complete transaction retention, source fingerprints, and regression tests.
- [x] Coverage store and builder: source-bound manifests, unchanged assets, provisional scope, missing-policy guards across refreshes and identity corrections, and both rating surfaces tested.
- [x] API/UI: provisional status, included/excluded years, accessible disclosure, and retained valuation attribution.
- [x] Private replay: later Mantasy Results validate without the unresolved first year; keeper assets remain unavailable. Later Chill Results validate independently; the most recent completed year passes full asset validation and identical offline replay. Its preceding year exceeds missing offensive price coverage. Nothing published.
- [x] Focused and broader tests, independent review, and preview validation completed. Logical unit prepared for commit; deployment/publication remains separate.

## Verification record

- Root engine suite: 1,474 passed. Web: 1,052 passed; TypeScript passed; lint has one existing DashboardClient ref warning.
- API broad run: 2,151 passed, 57 skipped, four existing trade-view fixture failures caused by missing owner_aliases. Final focused coverage/scope/model/grader checks and collector checks pass.
- New coverage files lint clean; legacy-file lint findings unchanged from baseline.
- All private coverage manifests match normal-refresh source fingerprints after correcting Sleeper playoff-team metadata. Existing sealed raw evidence is retained.
- Review fixes: missing coverage cannot promote provisional output; this protection persists through unavailable refreshes and canonical identity changes.
