# Automatic recap corrections implementation plan

**Goal:** Keep valid weekly recaps readable and automatically correct materially changed facts within existing spending limits.

**Approved scope:** User authorized build, full weekly lifecycle testing, and Railway deployment; spending limits must not change.

**Architecture:** Persist a versioned text input contract for new canonical period recaps. Exclude unused bench evidence from that contract and from writer/reviewer inputs together. Compare exact sealed input facts, never infer absence of claims from prose keywords. Legacy recaps retain conservative full-source dependencies unless existing explicit review proves equivalence. Separate authenticated text authority from withdrawn media using validated artifact/outbox/source proof. Material changes create an idempotent correction candidate through the existing managed writer and reviewer, retaining original receipts and using only the original episode's unused call allowance plus unchanged monetary caps.

**Constraints:** No budget edits, no receipt replay with changed requests, no release of unknown obligations, no public-share enablement, no synthesized standings/history. Corrections use stable qualified source observations. Exhausted/unknown allowance remains explicit and alerts through the existing monitor.

## Implementation

- [x] Add text input contract and dependency comparison; tests distinguish unused bench, starter/result, rules, source outage, and legacy inputs.
- [x] Add exact text serving proof independent of media holds; preserve source/restore/head/review fences and explicit withdrawal. Test correction after media withdrawal and stale revisions.
- [x] Add stable, idempotent automatic correction candidates and original-call-allowance accounting through managed admission/dispatch/publication. Test repeated observations, rollover, unknown receipts, exhaustion, and pause.
- [x] Exercise full lifecycle through observation, generation, publication, changed evidence, correction, subsequent week, and repeated scheduler ticks with fake provider receipts.
- [ ] Run API and engine suites, lint, review diff, commit, deploy API/Web, verify exact release and live archives, read back unchanged caps.

## Review focus

Legacy artifacts must not acquire invented dependency proofs. Uncertain provider outcomes must never be retried as a new correction. Source changes while correction work runs must invalidate publication. Restored database epochs and revoked sharing remain blocked. Later-week dependencies must only be relaxed for a provably period-local input contract.
