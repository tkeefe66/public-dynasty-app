# Unattended recap operation implementation plan

**Goal:** Produce the weekly article and video under the owner's standing authorization, without routine approval or a laptop process.

**Architecture:** Keep the existing database scheduler, immutable attempts, budget reservations, and publication checks. A separate Railway controller manages one isolated render VM only while media work is pending. Provider receipts and source revisions remain authoritative.

**Scope:** Owner authorized recurring league scripts to ElevenLabs with the existing voice and $3/episode, $15/month generation limits. Never resend an ambiguous paid request. Existing paid audio must be reused for qualification.

- [x] Reproduce dialogue history recovery failure using a sanitized production response shape; match exact request, voice, text and history IDs.
- [x] Reproduce discounted credit false hold and malformed-credit exception; enforce the qualified ceiling and preserve immutable pricing.
- [x] Add a membership-independent, dedicated-worker-authenticated demand hint without leasing, exposing payloads or spending.
- [x] Add a Railway controller with persistent state, process lock, bounded VM lifetime, restart recovery and idle shutdown. Use the official pinned SDK and a dedicated project token, never the local CLI login token.
- [ ] Verify controller restart and ambiguous-create recovery with synthetic work before enabling paid generation.
- [ ] Reconcile billing and retained calibration evidence; retain actual recognition failures rather than fabricating a pass.
- [x] Replace routine rollout-review requirements with a separately audited owner standing authorization, retaining current-source, budget, content and media checks.
- [ ] Deploy current worker image/checkpoint and controller; activate current-season automatic policy after qualification.
- [ ] Exercise scheduler through publication, including restart and duplicate-tick checks; confirm API/Web/worker release identities and real playback.

## Review focus

Creation timeout must never launch two credentialed workers. A controller crash must leave enough durable state to reconnect. Idle shutdown must not interrupt a running stage. Provider format changes must not lead to duplicate narration. Article corrections must invalidate the old media selection.

## Verification and remaining activation gates

The full API suite passed 1,648 tests with 57 skips before the additional three
bootstrap tests. The controller's ten tests and TypeScript check passed. Separate
review found and verified fixes for idle shutdown racing a claim and demand
outages bypassing VM expiry. Mutation checks detect removal of member-media
privacy and worker draining. Production activation remains incomplete: a dedicated
Railway project credential is awaiting owner confirmation, and retained real
narration has not passed the independent speech qualification. No calibration
pass, deployment, active controller, or unattended end-to-end success is implied
by these unit-test results.
