# Generation controls: rollout and recovery

The application starts with paid work held. Free provider refreshes continue. Dollar caps are a separate policy decision; the existing nonzero monthly budget still stops new requests.

## Finding the controls

Open **Admin → AI writing**. The status at the top accounts for league-specific settings, global holds, the deployment pause, and feature safety stops. **Tracked AI spend** is the managed request ledger total across all leagues; it excludes earlier spending and unknown charges.

- **Needs your review** lists stopped and held jobs separately from recent activity. **Review problem** explains the recorded reason, requests used, known cost, and the available recovery actions. Older generic failures explicitly say their exact cause was not recorded.
- **Approve new content** requires selection, a reason, an exact preview, and a separate **Approve paid writing** action. Viewing and previewing content makes no AI requests.
- **Settings** applies **Off**, **Ask me first**, or **Automatic** to all leagues, a league type, or a single league. Choosing **Use shared default** removes that override; the current saved value is not a preview of the inherited replacement. Reasons are entered beside each change.
- **Recent activity** shows readable jobs and their saved request costs. **Advanced** contains AI requests and costs, saved content, change history, publication delivery, and activation/recovery controls. Only record types supported by the API offer a league filter.

## Release sequence

1. Confirm the Railway project, environment, API service, Web service, database and volume. Record the approved commit for both services.
2. Pause the old scheduler and remove/revoke its AI provider credential. Stop and drain every old API worker, one-off CLI process and previous deployment. Verify provider activity has stopped. New database flags cannot control old software that bypasses them.
3. Take a complete database and volume backup. Retain its manifest, table counts, and hashes of original Analyst editions, revisions and share bindings. Rehearse restore in an isolated target first.
4. Deploy the matched API and Web commit with generation held and the provider credential absent. The API deploy command applies additive migrations 0009 and 0010; neither migration authorizes work. Do not run a destructive downgrade.
5. Run free refreshes for managed leagues to establish provider-verified season links and capabilities. These refreshes import existing prose before rebuilding disposable caches. Keep leagues with unknown identity/capabilities pending.
6. Run `python scripts/reconcile_generation.py --cache-dir <volume-cache-path>` using the explicitly configured `TRADE_GRADER_DATABASE_URL`. Retain the JSON report. Repeat once: source and artifact hashes/counts must match. Unregistered cache identities and conflicting revisions are reported and cause a nonzero exit; resolve them before activation. The command makes no provider requests.
7. Compare identity records, memberships, side bets, grants and archive/share fingerprints with the backup. Confirm both Railway services have terminal successful deployments at the intended commit and verify member login, dashboard, refresh/polling, owner history, Analyst original/revision and existing share URLs.
8. Assign profiles and activate only verified current league series in Admin. Configure an execution epoch outside the database backup using `TRADE_GRADER_GENERATION_EXECUTION_EPOCH`. Issue the new credential only to the managed API. Keep app policy paused while reviewing settings.
9. Use the owner activation control with the recorded worker-drain evidence in its reason. Remove the app policy pause deliberately. Activation/resume resets future-work watermarks and holds accumulated candidates; it never authorizes a backlog. Start with one reviewed subject, reconcile the physical provider request with the saved receipt, cost and artifact, then select automatic modes where wanted.

At launch, global and per-series paid concurrency are one. One blurb/story allows at most two calls, Analyst at most four. A profile or series cannot raise the application's concurrency ceiling or defeat an inherited pause.

## Pausing and uncertain attempts

Use **Pause all AI writing** for ordinary incidents. For deployment-level shutdown, set `TRADE_GRADER_GENERATION_EMERGENCY_PAUSE=true` and revoke the provider credential. An already admitted HTTP request may finish and be billed; its late receipt is still retained. Pausing prevents subsequent stages and publication.

For a timeout or lost response, inspect the immutable request/receipt and provider request ID. Do not infer “not sent” from elapsed time. Stop the original sending process first. Record provider evidence, then either record proven non-submission or abandon the uncertain attempt while leaving cost explicitly unknown. Both actions cancel the original job; replacement needs a new exact campaign preview and approval. Never reset an attempt's call allowance.

If a successful late receipt settles the original attempt, **Resume after receipt review** replays its saved response and continues only the original remaining allowance. Unsettled attempts still block resume. Local receipt/accounting or artifact-storage failures and graceful worker shutdown hold the job for recovery; after storage is healthy and saved receipts reconcile, **Resume remaining work** reuses completed stages. Resume is audited, reruns validation, and rechecks permission and publication gates. It cannot revive cancelled or restored authorizations.

A failed file projection can retry the same saved artifact from **Advanced → Publication delivery**. This makes zero AI calls. A content correction is proposed from **Advanced → Saved content**, with a reason; preview and approval create a separate bounded authorization. Original Analyst editions and existing revision/share addresses remain intact.

## Restore

Use `scripts/restore.py` against an empty migrated target. A pristine migration bootstrap row is allowed; other populated targets are refused. Restore commits a global quarantine and fences restored jobs in the same transaction as data loading. Raw receipts, artifacts and revisions remain unchanged.

Keep workers stopped and the provider credential revoked during restore. A restored snapshot cannot know which calls happened afterward. Reconcile provider activity since the snapshot; cancel/review all restored paid authorizations. Rotate the separately configured execution epoch to a **new value**. Admin refuses activation with the backed-up epoch, including after a pause action. Explicit activation and new candidate approvals are required. Resume never revives restored paid jobs.

Raw database snapshot restores performed outside this tool require the same external credential revocation, fresh epoch and quarantine procedure. Database flags alone cannot prove that a restored database is newer than provider billing.

## Rollback

Retain the additive tables and all receipts. If a release is unhealthy, pause and roll forward with a repair, or deploy a compatible version that keeps the managed gateway and quarantine checks. Never restore a pre-gateway executable while a paid credential is available. Serving existing saved prose is the safe degraded mode.

## Local verification

Use a disposable PostgreSQL database ending in `_tests` for race and migration tests. They drop their test schema. Run engine and API suites separately; both contain a Python package named `tests`. CI consumes `uv.lock` and runs a credential-free fake-provider contract inside the built API container with networking disabled.
