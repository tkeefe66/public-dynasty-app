# Yahoo scoring leaders implementation plan

**Goal:** Extend the existing scoring boards to authenticated Yahoo leagues of any roster-retention format.

**Architecture:** Keep scoring, completed-week selection, ranking and ownership in the shared service. Add an optional player-points verification capability to Yahoo, independent of matchups. Validate every eligible active player, including free agents, against league-context Yahoo points. Use existing caller-scoped connected clients and preserve owner mappings.

**Constraints:** No deployment, migrations, mapping changes, paid calls or AGENTS.md edits. Fail explicitly on missing identities, incomplete source data and scoring discrepancies.

- [x] Add failing adapter, service, route and UI regression tests.
- [x] Add Yahoo player-points verification with complete ID mapping and bounded batches; preserve authoritative totals.
- [x] Adapt shared service caches: version league outputs, scope ownership by mapping version, separate normalized stats, share unchanged NFL catalog/state. Reconcile before caching results.
- [x] Select authenticated clients and distinguish authentication, throttle, transport, unsupported input and reconciliation failures. Hide retries for permanent input failures.
- [x] Run relevant Python suites, web tests, lint and type checks. Inspect available live verification access without exposing credentials; report any unverified live behavior.
- [x] Review diff and prepare verified logical unit for local commit after mandatory skill gate.

Review focus: free-agent mapping, kicker/defense scoring, nonfinite actuals, stale cached validation with changed player sets, owner mapping revisions, Yahoo throttle during client creation, and historical weeks after fantasy playoffs.

Live acceptance remains blocked on Yahoo player identity coverage; see docs/yahoo-scoring.md for the 2,777 reconciled comparisons and precise remaining limitation. No complete Dads board was published.
