# Cloudflare R2 backup — design

*2026-08-12*

## Problem

The app keeps state in two independent stores, and neither is backed up.

**Postgres** (Railway managed, currently 18.4) holds the only data that has no
other source: `users`, `league_memberships`, `app_settings`, `page_events`,
`side_bets`. A side-bet ledger is money between real people and the code goes to
some length never to destroy a row (void replaces delete) — that care is wasted
if the database itself can vanish.

**The cache volume** (`api-volume`, mounted at `/data/sleeper-dynasty/cache`,
0.2 GB used of 4.9 GB) is mostly rebuildable: every `chain_<id>.json` regenerates
from Sleeper on the next refresh. Three things on it do not:

- **Dated price snapshots** — `KtcSnapshotStore`, `AdpSnapshotStore`
  (`adp/daily/YYYY-MM-DD.json`), `RatingSnapshotStore`,
  `StandingsSnapshotStore`. KTC and FantasyCalc publish no historical endpoint,
  so `capture()` can only ever write *today*. This is why at-trade and aged
  valuation work "going forward only" — the file **is** the history. Lose it and
  it cannot be re-derived at any price.
- **Cached LLM prose** — trade stories, GM blurbs, franchise outlooks. These
  regenerate, but at real Anthropic cost, and the throttle exists specifically
  to stop them regenerating.
- **`llm_costs.jsonl`** — the spend record the monthly budget gate reads.

So the backup has to cover both stores, and a restore has to put both back.

## Constraints that shape the design

- **A Railway volume attaches to exactly one service.** Only the `api` container
  can read the cache dir. Any backup job that covers both stores must run inside
  that container; an external runner could only ever reach Postgres.
- **Postgres is 18.4; the API image is `python:3.11-slim` (Debian bookworm),
  whose default `postgresql-client` is 15.** A `pg_dump` that works needs the
  pgdg apt repo pinned to client 18, and re-pinning every time Railway bumps the
  server major.
- **The schema is five tables of plain scalars** — `String`, `Integer`,
  `Boolean`, `Date`, `DateTime(timezone=True)`. No JSONB, no bytea, no enums, no
  sequences (every primary key is a UUID string). There is nothing for a logical
  dump to get wrong.

## Approach

**A daily in-process job in the API that dumps Postgres in pure Python, tars the
cache dir, and writes both to R2.**

Rejected alternatives:

- **`pg_dump` binary.** The right default for a schema you don't control. Here it
  buys no fidelity the reflection dumper lacks, and costs the pgdg apt repo, ~40 MB
  of image, and a version coupling that breaks silently on a server upgrade.
- **External GitHub Actions cron.** Zero production surface area, but it cannot
  reach the volume without a new authenticated bulk-download endpoint — a worse
  thing to own than a backup job.

A consequence worth stating plainly: because the dumper goes through SQLAlchemy
rather than a Postgres binary, it runs identically against the SQLite dev
database. The restore path is therefore rehearsable on a laptop with no Postgres,
which is what makes "verify the restore" a routine step instead of an event.

## Components

### `api/app/services/backup_service.py`

Mirrors `refresh_service.py`'s shape: the work and the loop in one module.

- `dump_database(session) -> bytes` — reflects `Base.metadata`, reads every table
  inside a single `REPEATABLE READ` transaction, emits gzipped JSONL with one
  object per row tagged by table. Point-in-time consistent by construction.
  The isolation level is set only on Postgres — SQLite's single-writer model
  already gives a consistent read, and asking it for `REPEATABLE READ` errors.
- `archive_cache(cache_dir) -> Path` — a `tar.gz` of the whole cache directory,
  streamed to a temp file rather than held in memory.
- `build_manifest(...) -> dict` — per-table row counts, tar member count and
  byte size, the current alembic revision, `ChainCache.SCHEMA_VERSION`, and the
  git SHA. This is what makes a restore *checkable* rather than hopeful.
- `run_backup()` — assembles the three, uploads, records the outcome, returns it.
- `backup_loop()` — the scheduler (below).

### `api/app/services/r2.py`

The only module that knows R2 exists: a thin boto3 client against
`https://<account>.r2.cloudflarestorage.com` with a single `put_object(key, data)`,
called through `asyncio.to_thread` so the event loop is never blocked. R2's
single-`PUT` ceiling is ~5 GB and our largest object is a compressed 0.2 GB
directory, so no multipart handling is needed.

Keeping the S3 seam in one file is what would let a different object store be
swapped in without touching the backup logic.

### `scripts/restore.py`

Takes an explicit target database URL and cache directory. Downloads a run
(latest by default, or a named prefix), verifies the payloads against the
manifest, runs `alembic upgrade head`, and inserts rows in
`metadata.sorted_tables` order so foreign keys resolve. Refuses to write to a
target that looks like production without an explicit override flag.

### Object layout

One prefix per run:

```
backups/2026-08-12T09-00-00Z/
  postgres.jsonl.gz
  cache.tar.gz
  manifest.json
```

## Atomic writes (a fix this forces)

Every JSON store on the volume truncates and rewrites in place:

- `api/app/services/chain_cache.py:164` — `open(path, "w")` + `json.dump`
- `adp_snapshot_store.py:73,124`, `rating_snapshot_store.py:52`,
  `ktc_snapshot_store.py:46`, `standings_snapshot_store.py:46,52`,
  `league_raw_cache.py:54` — `path.write_text(json.dumps(...))`
- `name_override_store.py:32`, `profile_store.py:35`, `src/sleeper_dynasty/cache.py:41`

A tar taken while the auto-refresh scheduler is mid-write captures a truncated
file, so the backup would silently contain corrupt entries. The same window is
already a latent production bug: a crash or OOM mid-write leaves a corrupt cache
that the API then fails to load.

Fix at the source with one shared helper — `src/sleeper_dynasty/util/atomic.py::write_json_atomic`
(write to a temp file in the same directory, `os.replace`) — and convert all ten
call sites. A reader then sees either the old file or the new one, never a
partial one, and the tarball inherits that property for free.

`llm_costs.jsonl` is append-only and stays as it is; the worst case is a torn
final line, which the reader already tolerates.

## Scheduling

A fixed UTC hour, not an interval. An interval-from-boot loop (the auto-refresh
pattern) would give zero backups or several depending on when deploys land.

`backup_loop()` sleeps until the next `backup_hour_utc`, runs, and records the
date in a marker file on the volume; on wake it skips if that date is already
recorded, so a redeploy inside the same day does not re-run the backup. Started
from `main.py`'s lifespan alongside `auto_refresh_loop`, cancelled the same way.

If the service ever runs multiple replicas, each would take its own backup. The
run prefixes are timestamped so the objects do not collide — the cost is
duplicate uploads, not corruption. Not worth coordinating for a single-instance
service.

## Credentials and retention

- `api/app/services/r2.py` contains **no delete and no list call**, and must not
  gain one. That is hygiene — the app cannot erase or enumerate backup history by
  accident — but it is **not an access control**: an attacker holding the
  credential does not run our code.
- **R2 issues no put-only permission group.** The token UI offers Admin Read &
  Write / Object Read & Write / Object Read only, so the narrowest write-capable
  credential the operator can actually create is **Object Read & Write**, which
  can delete and overwrite. Assume the app's credential can do both.
- The real protection is therefore a **bucket lock rule** (a required setup step),
  not versioning: **R2 does not support object versioning** — it is a standing
  feature request, not a shipped feature, so any plan resting on it is void.
  A bucket lock prevents deletion *and* overwriting of objects under a prefix for
  a retention period, and **lock rules take precedence over lifecycle rules**, so
  a locked object cannot be reaped early. Set the lock's retention equal to the
  lifecycle's expiry (30 days) and backup history becomes genuinely immutable for
  its whole life, against our own credential as much as an attacker's. Even a
  hypothetical put-only token could overwrite an existing key, so the lock is
  load-bearing either way.
- Timestamped run prefixes do make a *blind* overwrite hard for something that
  cannot list — it would have to guess a run id — but that is an obstacle, not a
  guarantee.
- **Retention is an R2 bucket lifecycle rule**, not application code. Nothing in
  the app deletes a backup.
- Restore uses a **separate read-scoped token that lives on the operator's
  laptop**, never in Railway.

Config follows the existing DSN-gated pattern (`env_prefix="TRADE_GRADER_"`):
`backup_enabled` (default `False`), `backup_hour_utc` (default `9`),
`r2_account_id`, `r2_bucket`, `r2_access_key_id`, `r2_secret_access_key`. The job
is inert unless enabled *and* all four R2 values are present.

Volume: 0.2 GB raw, and JSON compresses hard — roughly 1 GB for 30 dailies, inside
R2's 10 GB free tier.

## Failure handling and visibility

A backup that broke three weeks ago and told nobody is the standard failure mode,
and it is discovered at restore time. So:

- A failed backup logs at ERROR and reports to Sentry. It never propagates —
  the API must not fall over because R2 was unreachable.
- Last success and last error are written to the existing `app_settings` table
  (keys `backup.last_ok_at`, `backup.last_error`) — no migration — and surfaced
  in the `/admin` Usage section.

## Testing

- **Round-trip.** Seed all five tables against SQLite, dump, restore into a fresh
  database, assert row-for-row equality including timezone-aware datetimes.
- **Column-type guard.** Reflect `Base.metadata` and fail if any column type falls
  outside the supported set. The day someone adds a JSONB column the build goes
  red, instead of the backups going quietly lossy.
- **Archive.** `archive_cache` members match the source directory.
- **Upload.** A faked R2 client asserts key layout and manifest contents.
- **Scheduler.** The marker prevents a second run the same day; an upload failure
  is swallowed and recorded rather than raised.
- **Atomic writes.** A reader observing a store mid-write never sees a partial
  file.
- **Restore dry run.** Pull a real backup, restore into a scratch Postgres and
  scratch cache dir, boot the API against it, load a league page. An unverified
  backup is not a backup, so this is a completion criterion, not a follow-up.

## Out of scope

- Point-in-time recovery. Daily granularity; up to 24 hours of loss is accepted.
- Backing up anything derived from a backup (no cross-region replication).
- Encrypting objects beyond R2's at-rest encryption.
- Automated restore drills on a schedule. The dry run is manual and one-time.

## Open item

The R2 account id and bucket name are needed before implementation; the secret
goes directly into Railway variables and never into the repo. Whether the
existing token is already write-only, or needs re-scoping, is to be confirmed —
re-scoping is the recommendation.
