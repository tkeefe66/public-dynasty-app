# Railway weekly recap monitor

The Railway API hosts an opt-in monitor independently of the desktop app and
the existing fifteen-minute free-refresh scheduler. It starts no new AI work
itself. The existing generation gateway still owns every provider dispatch,
per-job allowance, combined edition/month cap, factual review and publication.
The API service must remain always running (`sleepApplication=false`). Its
minute timer only consults Postgres; sources are read when `next_check_at` is due.

## Configuration and cutover

Set these **on API**, never in committed source:

- `TRADE_GRADER_RECAP_MONITOR_ENABLED=true`
- `TRADE_GRADER_RECAP_MONITOR_CONFIG`: JSON containing `owner_id` (existing real
  admin), `series_ids` (the eight verified series), `first_season`, `first_week`,
  and an ISO `start_at` with timezone. The approved floor is 2026 Week 7. Scope is
  hashed into durable state; changing scope requires deliberate reconciliation.
- `RESEND_API_KEY`: existing authorized Resend account credential.
- `RECAP_MONITOR_FROM_EMAIL`: sender address on a verified Resend domain.

The recipient is the configured existing owner's current database email,
validated against the current admin allowlist; there is no arbitrary `to` field.
Each queued alert binds the recipient and exact sender/message envelope before
dispatch. No raw provider errors, source payloads, signed links, or credentials
are placed in email or monitor logs.

Deploy only the reviewed clean release commit to API; apply Alembic revision
`0021_recap_monitor`. With monitoring still disabled, run inside API:

```
python -m app.services.recap_monitor verify-email
python -m app.services.recap_monitor initialize
python -m app.services.recap_monitor dry-run
python -m app.services.recap_monitor verify-publications --season 2026 --week 6
```

`initialize` creates only scope-bound monitor state; it is idempotent and never
resets existing progress. `dry-run` reads sources through the same real owner
and may perform normal Yahoo credential/grant renewal; it cannot run recovery,
send email, create approvals, or force generation. `verify-email` proves key and
verified sender configuration, without sending a test message. It does not prove
inbox delivery. `verify-publications` checks current member-serving handler,
nonempty exact edition, current artifact, approved review receipts and delivered
outbox. Browser checks using the existing owner's signed-in session verify the
external member route without creating a synthetic user or minting credentials.

Enable monitoring, wait for its own `heartbeat_at` to advance in Postgres, verify
the configured next useful check and absence of new provider attempts/alerts,
then pause the existing desktop heartbeat through the supported automation tool.
Never leave two recovery monitors active after cutover. Restore the desktop
monitor only after disabling the cloud task if rollback is required.

## Schedule and recovery

The baseline is Monday 22:30 **America/Denver**, calculated using ZoneInfo across
DST. Qualification crosschecks the full NFL schedule and exact scoreboard event
inventory before any edition audit. Unfinished games defer to estimated finish
plus a minute; the estimate is never completion evidence. Multiweek rounds use
the existing scoring-period/bracket rules; a final round remains tracked after
the season ends. Unknown mappings/sources stay explicit and never select a
different owner's Yahoo account.

Eligible unfinished work is checked hourly. When only known retry/release times
remain, the next useful check follows that gate; Tuesday morning is not applied
to all text leagues. All delivered editions restore the next Monday automatically.
Postgres stores a CAS lease, fallback due time, progress fingerprints, immutable
alert identities and bounded recovery counters. Recovery and its counter commit
in the same transaction; stale workers cannot overwrite a newer lease.

At most two normal audited recovery actions are attempted per tracked period:
same free job retry, resume of its remaining approved calls, complete approved
receipt replay where the existing command permits it, or free saved publication
projection. Original actor/membership/Yahoo generation is rechecked. Four is the
normal maximum call allowance; stricter exact-job limits remain binding. The
monitor neither changes budgets/models/provider scope nor creates replacement
approvals, resets counters/breakers, expands sharing or backfills earlier weeks.
Code defects and unsupported/unsafe recovery produce a help request.

## Help-only delivery and limits

There is no routine progress, recovery, success, completion or test email.
Explicit approval/unsafe-recovery blockers notify once; eligible progress stalls
and persistent source failures require two consecutive hourly no-progress checks.
Fingerprints cover scope, series/period, cause and action. Cleared unsent help is
cancelled; ambiguous sending help is quarantined, not retried after resolution.
Sent and ambiguous identities are never reset. A definitively unsent cancelled
alert can reactivate if its blocker recurs.

Resend receives a stable idempotency key and exact envelope. Timeouts/429/5xx can
retry that same request only within a conservative 23-hour window, inside
Resend's documented 24-hour deduplication period. Authentication/validation
errors, changed envelopes/recipients or expired ambiguous outcomes quarantine
delivery. Never blindly clear these records; inspect provider evidence first.

Use `python -m app.services.recap_monitor status` and Railway API logs for
diagnostics. Email transport failure cannot report itself through the same broken
transport; Postgres/API/network outages similarly require Railway operational
monitoring. The monitor is not a hosted coding agent. A future scheduled cycle
and first real help email remain separate proof from deployment or dry-run.

Validation uses `api/tests/test_recap_monitor*.py`, existing generation gateway,
worker and budget tests, migration roundtrip, lint, and exact live revision checks.
