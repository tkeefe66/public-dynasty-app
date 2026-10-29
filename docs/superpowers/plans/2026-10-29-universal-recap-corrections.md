# Universal recap correction rollout

Goal: enable source-bound weekly recap corrections for all active supported leagues and future activations, including Yahoo postseason, without changing spending limits.

Architecture: use the existing shared collector, review, publication and correction allowance. Default text reconciliation on independently of video. Migrate the legacy opt-in field only; preserve feature authorization, pauses, activation boundaries and every budget. Yahoo supplies weekly playoff result evidence directly instead of fabricating Sleeper bracket edges. A complete scoreboard proves that an omitted owner has no scheduled matchup, not that they were eliminated or received a bye.

User authorized implementation and deployment after CI and full lifecycle verification. No paid AI calls during implementation or verification.

1. Add default/migration regression tests, implement audited policy migration and preserve explicit future opt-out.
2. Test Yahoo playoff normalization: authoritative winner, tie-break winner, consolation/placement, unscheduled teams, incomplete/duplicate/wrong-week evidence. Preserve exact weekly scores and starter identity.
3. Integrate weekly Yahoo postseason periods into shared collection and participant validation. Missing source evidence remains held; corrections to earlier periods remain independent of new-period discovery errors.
4. Exercise weekly publication through playoff publication, correction, repeat collection and season rollover with fake provider transport; assert budgets unchanged and no real provider calls.
5. Review changes, run full CI without pushing main (production auto-deploys main), then deploy verified commit and inspect migrations, effective policies, preserved articles and provider-attempt count.

Review focus: old full policy JSON overrides; explicitly paused leagues; missing Yahoo scoreboard entries; tied playoff scores with provider winner; older regular-season episodes during playoff discovery.
