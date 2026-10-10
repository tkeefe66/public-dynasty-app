# Weekly recap video operations and release candidate

This package implements a gated weekly workflow, with API-owned spending and
publication authority. Local synthetic acceptance is runnable below. **Release
is held pending Railway runtime qualification, exact account/voice billing
proof, bounded paid calibration and explicit deployment authorization.** Test
calibration and emulated phone evidence confer no real rollout credit.

Record the approved release commit and immutable image digest in the release
record. The commit containing this runbook is the initial local candidate;
subsequent review fixes require affected checks and the final verification set.
API, Web and media worker Railway target service names have **not been verified**.
Tom must confirm all three targets before the first deployment. Do not infer them
from local directory names. No push, deployment, provider purchase, credential
creation, production access or live publication is authorized by this document.

## Final review workflow boundaries

Before the first paid video-script request, one immutable plan reserves every
allowed script call plus the qualified one-take narration maximum. The initial
envelope is **6,000 submitted characters**, including opening, closing, delivery
tags and join spaces, with at most 2,000 characters per request and 63 chunks.
This is a billing maximum, not a duration target or a replacement for spending
caps. Required owner/matchup coverage remains mandatory; oversized complete
scripts may use the existing bounded repair, never truncation or extra calls.
At 80 micro-USD per character, default script bounds plus narration reserve
2,909,952 micro-USD. Unknown or higher rates and intersecting written/video/app
obligations can prevent the first script send. Written publication remains
independent. Script success retains narration allowance; exact immutable chunks
replace it under the same admission lock and savepoint. A failed binding leaves
the envelope intact. Cancellation releases only never-submitted work. Original
envelope/rate/config and concrete-binding evidence remain in the financial
restore inventory; no applied migration or historical receipt is rewritten.

Reservation timestamps/months record provenance. Each physical request's durable
first dispatch-admission timestamp separately determines Denver recap spending
and UTC app spending. Binding captures time after lock acquisition and rechecks
both windows atomically. Unsent and unresolved exposure carries forward; late
receipts remain attributed to their original dispatch month.

An admitted episode can renew expired free metadata verification through
**Renew free voice verification**, including a finished preview reviewed after
an hour or a week rollover. Standing-policy orchestration reaches progressed
episodes too. Renewal checks current actor, policy, facts and configuration,
without treating the already admitted period as a new historical request.
Compatible paid checkpoints are reused; renewal itself never sends narration
or creates a new dispatch authority.

An explicitly scoped replacement can receive a new manual finished review once
all original and replacement charges reconcile. The disposed original remains
abandoned with its receipts; current/active/unrelated unknown outcomes still
hold publication. Selection and projection recheck the exact replacement
disposition and new manual review. Replacement episodes receive **no credit**
toward the three-episode automatic-rollout threshold. Their manual publication
does not relax rollout qualification. Budget panels show the selected week,
season and playoff round; the unchanged episode digest remains in technical
details.

The final fix report records the exact commit, fresh verification commands,
image identity and retained warnings for this candidate. Earlier task-12
measurements below remain chronological evidence, not verification of later
product changes. The eight external release gates remain unchanged.

1. Real ElevenLabs exact voice/account/model entitlement, metadata compatibility
   and all-in API billing rate.
2. Approved Cal Mercer delivery, profanity/humor, real multi-chunk continuity
   and real ASR ambiguity rates through bounded calibration and finished review.
3. Railway enforcement of user/mount/PID/network namespaces, cgroup and tmpfs
   limits for the confirmed target services.
4. Production private bucket/IAM, immutability/lifecycle/egress and ingress/log
   token redaction.
5. Actual configured league schedules, brackets and rules against live upstream
   regular/postseason evidence.
6. Physical phone playback/download/seeking and actual recipient message previews.
7. External quarantine of every production replica during restore and latest
   independently held consent/financial recovery evidence.
8. Real inference/infrastructure/subscription cost and production-scale render/
   idle performance. Local synthetic tests do not establish these measurements.

## Ownership and durable flow

The existing API scheduler collects free period evidence. Release is no earlier
than Tuesday 08:00 America/Denver (DST aware), with complete schedule/participant
coverage and two identical canonical competitive fingerprints at least 60 minutes
apart. Delayed games delay readiness. Regular periods use their week; postseason
uses the complete recognized scoring round and every constituent NFL week.
Unknown formats remain held. Current source identity discovery runs before prior
episode due filtering: a daily old-episode reconciliation cannot hide next
Tuesday or the next season. Reconcile through release-week Friday every 15
minutes, then daily; explicit refresh forces free collection. Observation does
not authorize historical paid work or bypass manual/paused/member gates.

The API admits written draft/review into the managed provider gateway, saves the
canonical artifact and projects the reader article through its durable outbox.
A video script waits for that actual published revision. Free voice/account
preflight precedes script spend. The script writer uses full saved claims and
article evidence, whole-script review and at most one bounded repair/review.
A fixed media plan creates narration chunks, independent speech verification,
render and raw media QA. The worker polls subordinate leases and exact-identity
recovery requests; the API alone selects and projects public content.

Each physical provider attempt has one durable identity and immutable pricing.
Receipt persistence precedes parsing/settlement; unknown responses retain their
reservation and cannot be blindly resent. Restarts reuse completed prose/audio.
Free recovery reruns speech/render/QA from retained audio. An explicit bounded
replacement dispositions named unrecoverable content, reserves a complete take
under the original episode budget, and retains uncertain earlier charges.
Repurchasing scripts, another scheduler, Redis and general workflow engines are
not part of this design.

A finished preview approval binds exact facts/article/script, selected stages,
assets, receipts, module versions and policy. Three distinct reviewed current
season episodes can establish standing authority only with current calibration,
automatic policies, epochs and future sharing consent. Repeated approval of one
episode does not count twice. Material correction withdraws affected content
before repair; any article revision requires reviewed media reattachment.
Conservative dependencies include every earlier observed same-series period in
the current season. This can withdraw more later episodes than strictly needed;
narrower dependency claims require typed evidence before changing that policy.

## Exact settings and spending limits

The four defaults are intersecting ceilings, all revisions combined, represented
as integer micro-USD (1 USD = 1,000,000). They are not additive allowances.

| API cap field | Default |
| --- | ---: |
| `video_episode_microusd` | 3,000,000 ($3) |
| `video_month_microusd` | 15,000,000 ($15) |
| `combined_episode_microusd` | 5,000,000 ($5) |
| `combined_month_microusd` | 25,000,000 ($25) |

Admin → AI writing → Settings → individual league exposes persisted caps,
known/reserved/uncertain exposure and exact episode recovery. Saving lower caps
blocks the next admission transaction even for previously reserved plans; it
never erases charges. Below-obligation changes require acknowledgment. Cap edits
do not enable media. App-wide AI cap is another independent ceiling; recap months
use Denver dates while the app ledger uses UTC. Unknown historical exposure
remains a hold, not zero spending. Existing provider auth/credit/cooldown holds
remain independent of budget availability.

| Owner | Configuration (protected values stay outside Git) |
| --- | --- |
| API | `TRADE_GRADER_DATABASE_URL`, `TRADE_GRADER_CACHE_DIR`, `TRADE_GRADER_AUTH_BACKEND_SECRET`, `TRADE_GRADER_ADMIN_EMAILS` |
| API execution | `TRADE_GRADER_GENERATION_EXECUTION_EPOCH`, `TRADE_GRADER_GENERATION_EMERGENCY_PAUSE` |
| API serving | `TRADE_GRADER_RECAP_PUBLICATION_MODE` (`legacy`, `database`, `quarantine`), `TRADE_GRADER_RECAP_SERVING_EPOCH` |
| API restore | `TRADE_GRADER_RECAP_RESTORE_EPOCH`, `TRADE_GRADER_RECAP_RESTORE_EVIDENCE_DIGEST` |
| API media principal | `TRADE_GRADER_MEDIA_WORKER_TOKEN`, `TRADE_GRADER_MEDIA_WORKER_ID`, `TRADE_GRADER_MEDIA_WORKER_CAPABILITIES` |
| API private media | `TRADE_GRADER_MEDIA_ASSET_ROOT` for isolated local storage, or `TRADE_GRADER_MEDIA_BUCKET` and `TRADE_GRADER_MEDIA_BUCKET_ENDPOINT` with private S3 client credentials |
| API narrator binding | `TRADE_GRADER_ELEVENLABS_VOICE_ID`, `TRADE_GRADER_ELEVENLABS_ACCOUNT_IDENTITY_DIGEST`, `TRADE_GRADER_ELEVENLABS_ACCOUNT_ALIAS`, `TRADE_GRADER_ELEVENLABS_DIALOGUE_SETTINGS` |
| Worker supervisor | HTTPS `MEDIA_API_URL`, dedicated `MEDIA_WORKER_TOKEN`, `ELEVENLABS_API_KEY`; verified four-file ASR model mounted read-only at `/opt/model` |
| Web | `API_URL`, `AUTH_SECRET`, `AUTH_BACKEND_SECRET`, public origin `AUTH_URL` |

The voice remains Cal Mercer / The Gruff New Yorker with explicit `eleven_v4`.
No fallback voice or model is allowed. Exact provider voice identifier/account
identity and entitled settings belong in protected configuration; no real
identifier is committed. Direct-provider equivalence to the approved performance
remains unverified. `eleven_v4` support visible in metadata is insufficient proof
of this account's entitlement, rate or complete spoken performance.

## API/operator surface

All admin routes below require real current admin authentication; episode
mutations require revision/preview CAS and an audit reason. Member article
sharing remains separate from media approval.

| Route under `/api` | Purpose |
| --- | --- |
| `GET/PUT /admin/generation/recap-budgets/{series_id}` | Read/save caps; GET accepts `episode_id`; PUT uses `expected_revision`, `caps`, `reason`, `acknowledge_overcommitted` |
| `GET /admin/generation/recap-episodes?series_id=…` | Saved episode inventory |
| `GET /admin/generation/recap-episodes/{episode_id}` | Exact stage, evidence, qualification, recovery and spend |
| `POST /admin/generation/recap-episodes/{episode_id}/actions` | `prepare_preview`, `resume_free`, `resume_recovered_audio`, `reconcile_request`, `reassign_worker`, `skip_video`, `restore_access`, `disable_future_sharing`, `review_correction` |
| `POST …/{episode_id}/preview` | Verify current finished bundle; return preview digest |
| `POST …/{episode_id}/approve` | Persist finished review, then separately select publication |
| `GET/POST …/{episode_id}/replacement` | Preview/approve exact original attempt identities, request count and maximum |
| `GET/HEAD …/{episode_id}/preview/{media_id}/{name}` | Authenticated private preview; ranges preserved through Next proxy |
| `POST /internal/media/claim`, `/heartbeat`, `/complete`, `/authorize-dispatch` | Restricted media principal, exact lease fencing and one-use paid authority |
| `POST /internal/media/identity`, `/receipt`, `/recovery-receipt`; `GET /internal/media/attempts/{attempt_id}/recovery`; `POST /internal/media/attempts/{attempt_id}/audio` | Owned attempt identity, receipt and exact retrieval evidence (see route methods in `api/app/routes/media_worker.py`) |
| `POST /internal/media/recovery-claim`, `/recovery-complete` | Original-worker bounded recovery queue |
| `GET/POST /internal/media/assets` | Lease-restricted immutable bytes; GET uses `/{asset_id}` |
| `GET /public/analyst/{token}` | Current authorized public article and selected media |
| `GET/HEAD /public/analyst/{token}/media/{bundle}/{name}` | Per-request authority, Range/HEAD/download transport |

Public names are only `video.mp4`, `audio.mp3`, `poster.jpg`, `captions.vtt`.
Facts packets, scripts, episode JSON, raw transcripts, manifests, diagnostics and
QA are private. No public bucket, public object URL or presigned redirect exists.
Every new request rechecks current share/publication authority. Revocation cannot
recall already downloaded bytes or a recipient's cached preview. Current article
and media selection hashes must agree with reader bytes before release.

## Migrations and service lifecycle

Apply additive API migrations in order after backup/fingerprints, while media
execution is paused and serving gates are configured. Never rewrite an already
applied migration. Existing users/accounts/shares and numeric-stage prose
receipts must survive unchanged.

| Revision | Addition |
| --- | --- |
| 0011 `recap_budget` | League episode/month cap policy |
| 0012 `recap_budget_ledger` | Plans and allocations |
| 0013 `recap_workflow` | Episodes, observations, schedule inventory |
| 0014 `recap_media_leases` | Worker stages/assets/provider attempts and provider controls |
| 0015 `recap_receipt_recovery` | Early provider identity and recovery receipts |
| 0016 `recap_speech_reviews` | API-owned spelling review provenance |
| 0017 `recap_publication` | Publication authority, approvals, selections, consent and serving control |
| 0018 `recap_qualification` | Calibration/reviews/standing grants, dependencies and recovery; execution revisions |
| 0019 `recap_retention` | Recovery-point pins, deferred object deletion and restore reports |

API runs its existing scheduler/projector; Web handles session/JWT proxying; one
media worker runs `python -m media.worker`. `media/railway.json` selects the worker
Dockerfile and one replica with bounded restart attempts. It does **not** solve
target namespace/model/scratch provisioning. It is a release configuration
candidate, not proof of a deployed service.

To stop paid work: use existing admin global pause/emergency deployment setting,
then stop the worker and every uploader before maintenance. A pause does not
cancel a provider request already dispatched. Reconcile its exact receipt/unknown
exposure before granting further work. To start: verify target runtime/model,
private storage, current epochs/qualification and worker scope, then explicitly
activate approved execution. Merely restarting processes must not reset holds.
One worker replica is required: DB render lease exclusion plus local flock cannot
physically kill a zombie in another host. Verify old process termination before
replacement starts.

Worker children use Bubblewrap fresh user/mount/PID/network namespaces, nonroot
UID 65534, dropped capabilities, cleared environment, curated read-only runtime
and scratch-only writes. The supervisor alone holds API/provider credentials.
It must have network access while children cannot. Default unsupported local
Docker correctly refuses before claiming work. Target Railway support remains
unresolved; do not weaken this boundary to make a deployment start.

Measured local Linux visual benchmarks (Task8; not target sizing or speech proof):

| Input | Frames | Render wall time | Peak bytes | Scratch bytes | MP4 bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Approved visual benchmark, 137s | 4,110 | 87.053s | 704,380,928 | 236,278,919 | 3,488,804 |
| Synthetic 240s | 7,200 | 139.427s | 724,582,400 | 332,044,382 | 5,234,301 |

Runtime bounds: at most 2 GiB cgroup memory, at most 4 GiB scratch tmpfs, 20-minute
child deadline, 64 MiB per object, one render lease. Actual target CPU/architecture,
ASR resources, startup and storage costs require measurement. Saved benchmark
speech had unresolved ASR spans/low confidence and is not a qualified voice take.

## Private storage, retention and restore

API owns private media object read/write/delete with explicit reference checks.
Workers have no ordinary DB, bucket, admin or publication credentials. Backup
credentials remain write-only from the live application; offline operators own
backup read/list verification and lifecycle administration separately. Qualify
bucket permissions, versioning and the repository's 30-day backup lifecycle on
the actual target. Never grant live API backup list/delete just to simplify GC.

Failed/cancelled/superseded unreferenced takes become candidates at 90 days.
Unreferenced disposable renderer/check PNGs become candidates at seven days.
Selected/approved masters remain retained after revoke/withdraw; those actions
are not removal consent. Facts/script/receipt/QA evidence remains for edition
life. Unknown obligations, current/recovered paid ancestors, approvals and
unretired backup references pin objects. There is no implicit edition-removal
policy. Cleanup checks references transactionally, records pending deletion,
then performs storage I/O outside the control lock; retries are explicit.

Run maintenance from the API's trusted operator environment, with protected
configuration and target variables supplied independently:

```sh
python scripts/recap_maintenance.py --database-url "$RECAP_DATABASE_URL" status
python scripts/recap_maintenance.py --database-url "$RECAP_DATABASE_URL" cleanup --configured-media-store
python scripts/recap_maintenance.py --database-url "$RECAP_DATABASE_URL" abandon-backup --run-id "$RECAP_BACKUP_RUN" --uploader-stopped
python scripts/recap_maintenance.py --database-url "$RECAP_DATABASE_URL" retire-backup --run-id "$RECAP_BACKUP_RUN" --bucket "$RECAP_BACKUP_BUCKET" --uploader-stopped
```

Production-looking targets additionally require `--allow-production`, and actual
production use requires authorization. `abandon-backup` fences a stopped crashed
uploader but retains pins. `retire-backup` requires complete exact-prefix absence;
403/partial/failed listing or age alone cannot release pins. Delayed lifecycle
cleanup costs retained storage and operator time. Schedule ownership of status,
crashed-uploader disposition and cleanup retries explicitly; no new automation
was installed by this work.

Restore procedure (all-instance external coordination is mandatory):

1. Stop **every** worker and uploader; externally set every API replica to
   `quarantine`, emergency pause and a fresh common restore epoch. Verify every
   instance/deployment, not only a load-balanced health response. Prevent old
   replicas from serving or dispatching during replacement.
2. Export current authority if available, retain it privately and independently
   pin its digest in deployment configuration. Never treat the older backup as
   evidence of current consent, publication binding, caps or provider holds.
3. Restore exact DB/cache/private objects into quarantined destinations using
   `scripts/restore.py --database-url … --cache-dir … --configured-media-store
   --quarantine-api-url … --expected-restore-epoch … --current-authority …`.
   Supply the authorized backup run/bucket. Verify sizes and full-byte hashes.
4. `scripts/recap_maintenance.py --database-url … export-authority
   --quarantine-api-url … --expected-restore-epoch … --output …` exports private
   current evidence before restore. `reconcile --manifest … --current-authority …
   --configured-media-store --quarantine-api-url … --expected-restore-epoch …`
   compares exact objects, current publication/share authority and financial
   ledgers, including newer caps and legacy provider holds/cooldowns/breakers.
5. Review failed hashes, held publications and financial differences. Missing
   current evidence leaves old permissions/publications disabled. Recover exact
   evidence; do not fabricate reconciliation or clear unknown charges.
6. Explicit `reopen --report-digest … --actor … --quarantine-api-url …
   --expected-restore-epoch …` accepts only the current reconciled report. Verify
   every instance again, switch external serving to `database`, and separately
   authorize a fresh execution epoch/activation. Never return to `legacy` after
   restore. Reopening serving does not activate spending.

Legacy migration is dry-run-first from `api`: `python -m
app.reconcile_recap_publication --cache-dir "$TRADE_GRADER_CACHE_DIR"`. After
external quarantine, apply with `--apply --expected-digest "$RECAP_DRY_RUN_DIGEST"
--serving-epoch "$RECAP_SERVING_EPOCH"` against the unchanged inventory.
Preserve article/master bytes, token hashes, tombstones and opt-outs. In database
mode, DB outage/missing activation/withdrawal cannot fall back to stale files.

## Reusable local acceptance

Install pinned repository dependencies using `uv sync --frozen --all-packages
--all-extras` and `npm ci` in `web`. The local execution used root `.venv/bin/python`
(the equivalent existing environment). Tests in `tests/` and `api/tests/` must
run in separate roots because both are Python packages named `tests`.

Build the **current** worker image; an older task image is not final evidence:

```sh
docker build -f media/Dockerfile --build-arg VCS_REF="$(git rev-parse HEAD)" -t recap-media:acceptance .
docker run --rm --network none --memory 2g --tmpfs /scratch:rw,size=4g \
  --cap-add SYS_ADMIN --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
  -e BOUNDARY_SECRET=recap-boundary-sentinel -e RECAP_LINUX_TEST=1 -e TMPDIR=/scratch \
  recap-media:acceptance python scripts/check_recap_media_runtime.py
docker run --rm --network none --memory 2g --tmpfs /scratch:rw,size=4g \
  recap-media:acceptance python scripts/check_recap_media_runtime.py --expect-refusal
```

Those relaxed **outer local Docker flags** are measurement conditions only, not
Railway provisioning instructions. The child boundary still drops privileges and
cannot access the supervisor. Never mount credentials, a developer checkout,
home or the approved pilot into this container.

Start a dedicated disposable PostgreSQL 16 database ending `_tests` on loopback:

```sh
docker run -d --name recap-acceptance-postgres -p 127.0.0.1:57542:5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=local-recap-tests \
  -e POSTGRES_DB=recap_tests postgres:16-alpine
# After acceptance/review no longer needs it (only the container you created):
docker stop recap-acceptance-postgres
docker rm recap-acceptance-postgres
```

Do not run start/stop examples over an already-owned test listener. The
existing local acceptance uses task-owned `codex-recap-tests` on port 57542. Supply
`GENERATION_TEST_DATABASE_URL` explicitly. The fixture **drops/recreates its test
schema**. Never point it at production; never run PG suites concurrently. Run
from `api`:

```sh
RECAP_ACCEPTANCE=1 RECAP_ACCEPTANCE_IMAGE=recap-media:acceptance \
  GENERATION_TEST_DATABASE_URL="$RECAP_TEST_DATABASE_URL" \
  ../.venv/bin/python -m pytest tests/test_recap_video_end_to_end.py -q \
  --basetemp=/tmp/recap-acceptance
```

On macOS set `RECAP_ACCEPTANCE_CHROME` to the installed Chrome executable. CI
installs its lockfile-selected Playwright Chromium. No browser/account fallback
is allowed. The harness owns unique localhost listeners, copies Next plus local
design assets into test scratch, excludes **all** `.env*`, uses fixed throwaway
NextAuth/backend secrets, mints the existing test JWE session, exercises real
middleware/JWT/admin authorization, and tears down its own API/Next processes.
No auth bypass is shipped. The test-only DB dependency is the real Postgres
session factory; all authentication dependencies run normally.

Synthetic seams are explicit: saved source evidence and reviewed article/script
payloads, provider HTTP responses/physical-send counters, and ASR words against a
synthetic tone. The harness invokes the managed gateway and artifact publication
with those fixture payloads; it does not test real LLM composition quality. The
TopBar NFL-state source is synthetic and browser API traffic refuses non-local
hosts. Real
code owns readiness, gateway reservations/replay, script receipt validation,
narration transport and settlement, immutable private storage, speech validators,
worker adapters, pinned Linux rendering/QA, approval/qualification, publication,
HTTP streaming and frontend cap persistence. Every admitted narration identity
has one physical send. Prose receipt replay performs no second send. Crash
contracts cover unknown transport, raw-receipt settlement, free-stage expiry and
completed checkpoints. Synthetic ASR text cannot qualify actual recognition,
voice performance, physical devices or message previews.

Evidence includes `acceptance-evidence.json`, raw render/QA exchange, browser
logs and 390px screenshots under the printed test directory. CI retains only
synthetic summary/screenshots/logs for seven days. The browser edits/saves/reloads
a cap; the next real DB admission must reject against that lower cap. Signed-out
readers receive selected media only, with seek/range/HEAD and revocation checks.

Complete verification from separate roots:

```sh
# repository root
.venv/bin/python -m pytest tests -q
# api directory, normal sandbox (PG suites are separate)
env -u GENERATION_TEST_DATABASE_URL ../.venv/bin/python -m pytest -q
# web directory
npx vitest --config tests/vitest.config.ts run
npx tsc --noEmit
npm run lint
npm run build
# repository root, intended files staged
git diff --check
python3 scripts/check_publication.py
```

Also run every disposable PG suite sequentially with the explicit approved test
URL. Do not describe skipped PG tests as passing. No Python linter is configured;
none was added. Retain the existing Dashboard ref-cleanup warning and dependency
warnings separately from failures. Final commit verification is recorded in the
acceptance report; review fixes invalidate affected prior checks.

## Release approval package and external holds

Before requesting release, provide Tom the exact commit/image digests, terminal
check results, proposed API/Web/media target names, migration head 0019, backup
and share fingerprints, private bucket access/lifecycle design, target isolation
probe and measured resources. Verify existing legacy signed-out playback, new
synthetic media, frontend budgets, range/HEAD and revoked requests after all
three exact-commit deployments reach terminal success. Use a disposable edition
for revoke tests; never revoke the real approved pilot just to test it.

The calibration request is **blocked pending account evidence and authorization**.
Concrete bounded proposal: one approved script covering one synthetic full-league
weekly episode, one narration take, at most three explicit chunks of at most
2,000 submitted characters each (total <=6,000); include a real two-chunk seam and
full joined playback. Provider is ElevenLabs text-to-dialogue with timestamps,
explicit `eleven_v4`, protected exact approved voice/config, no alternate model,
no retakes, no auto top-up/subscription/credential creation. No public release of
the calibration output; private human review only. Maximum aggregate provider
charge is the lesser of **$3.00** and available video/combined episode and monthly
allowances after writing/script charges and all outstanding/unknown obligations.
The full immutable price snapshot must prove all chunks fit that maximum before
first dispatch. If exact rate, entitlement, continuity or remaining cap is absent
or the full plan exceeds it, submit **zero** requests and return for a revised
bounded approval. This is a proposed maximum, not a quote or authorization.

Required evidence: account identity/voice entitlement, actual rate and billing
terms/metering, all approved settings/continuity, full performance, pinned target
runtime/model. Reconcile actual per-request charges/reservations afterward.
Then qualify three real distinct reviewed weekly episodes with actual physical
phone playback and actual recipient message-preview evidence. Do not send a
message for Tom without separate explicit authorization. Standing automatic
operation remains held until those reviews, current bindings/versions/season,
future consent and explicit rollout approval all pass. Local mocked success
cannot activate production calibration or automation.

## Chronological decisions and costs

This appendix preserves decisions from the implementation ledger so operating
knowledge survives removal of ignored task scratch. Task numbers identify order,
not deployed versions. Parent task/whole-branch reviews are separate from the
implementer's self-check; release evidence must identify their final commit.

| Task / decision | Reason and tradeoff |
| --- | --- |
| Preflight 1–3 | Cap API initially reports inactive enforcement until ledger exists; one UI response contract and independent league fetch fencing avoid false balances. Full bounded request plan must fit caps; do not weaken caps to fit. |
| Preflight 4–5 | Source adapters hold until qualified; engine types remain independent from API imports. Fixture success cannot establish source completeness. |
| Preflight 6–8 | Preserve global stop and old provider holds; exact voice requires real calibration; Linux capability probe must refuse unsupported isolation. Costs are explicit holds rather than implicit fallback. |
| Preflight 9–12 | Reconcile legacy reads before DB activation; three distinct current approvals, no pilot credit; external restore authority protects newer revocations; local work ends before paid/deployment steps. Costs are migration/operational review. |
| Execution / schema | Sequential fresh implementers plus independent task reviews due coupled interfaces; extra review time. Migrations are additive and use next free number, never rewrite applied revisions. |
| 1 restore fixtures | Extend all-table backup/restore fixtures with each schema addition; targeted checks before task review, integrated full run later. Cost: maintaining realistic registered rows. |
| 2 pricing bound | Conservative ASCII serialized bytes include tool schemas and bounded wrapper; no chars/4 estimate. Actual receipt exceeding assumptions holds and records excess. This is not an invoice guarantee; full-context reservations would falsely block normal requests. |
| 2 episode identity | Stable digest of series/season/period, cross-check nested edition. Corrections/models do not create fresh budgets; playoff adapter owns round IDs. |
| 3 error/navigation | Structured ApiError detail and selected-league hold navigation avoid message parsing; small frontend scope expansion. Budget panel remains sibling to policy form, with inline anchor; slight scroll cost avoids nested forms. Dirty drafts survive unrelated refreshes. |
| 4 collection | Dedicated collector and admission/publication rechecks enforce readiness beyond a pure evaluator; extra integration surface requires actual-boundary tests. |
| 4 playoff rounds | Complete recognized scoring round, final NFL week archive key. No interim multiweek-final winner; ambiguous formats hold. |
| 4 optional context | Omit unsupported optional news/bets/standings while retaining full mandatory owner/results coverage and raw snapshots. Fewer optional beats until sourced. |
| 4 verification environment | Broad API tests use ordinary restricted environment; PG runs separately. External free-source timeouts under escalation are not proof of test failure or pass. |
| 5 provenance | Retain immutable source observation but compare canonical competitive facts and relevant metadata/article revision. Harmless timestamps/news should not force repeat spending; true fact changes must invalidate. |
| 5 selected premises | API-owned selected script IDs in authoritative publication order, deduplicated latest six episodes. Generated artifacts/lifecycle are insufficient publication history; earlier task callers deliberately used no history until authority existed. |
| 5 historical eligibility | Current reserve/taxi roster cannot prove past lineup legality. Only week-scoped eligible-player evidence permits counterfactual claims; fewer lineup jokes until sourced. |
| 6 free preflight | Exact account/voice/rate/qualification before script spend. Reuse free RecapStage lease infrastructure without a script only for preflight; small special case avoids extra queue/API key exposure. Compatible fresh evidence reuses paid script/checkpoints. |
| 7 early receipts | Add 0015 early identity and separate recovery receipt because one immutable final receipt cannot cover both. Preserve conflicts and stale content fences; extra protocol surface. |
| 7 spelling review | Add 0016 API-owned review, safe same-person/name/series/season reuse rebound per artifact. No worker/LLM aliases or text-only cross-person inference; extra provenance table. |
| 8 child isolation | Bubblewrap fresh namespaces for all children; curated runtime/model, scratch only. If target cannot isolate, launch remains held rather than weakening credentials/network boundary. |
| 8 narrated alignment | Multiple deterministic claim/status scenes anchored to approved words; never equally split time or infer narration order from claims. Ambiguity may require recovery review but must not display another matchup score. |
| 8 restore test | Add synthetic speech-review row and restored-value checks to all-table fixture. Preserve strong table coverage; no product behavior change. |
| 8 physical capacity | DB render lease exclusion plus local flock; one worker replica because an expired lease cannot kill a remote zombie. Some queue delay, physical fencing still unqualified. |
| 8 PCM consistency | Speech and renderer share independent chunk decoding and canonical PCM concatenation before ASR resampling. Prevent MP3 padding/timestamp divergence; target ASR/seams still require qualification. |
| 9 derivatives | Produce MP3/JPG/VTT deterministically in free packaging and validate before selection. Extra encoding work; never expose private manifests or mislabel WAV as MP3. |
| 9 serving gate | Explicit legacy mode exists only for transition. Database mode never falls back on missing activation/outage/quarantine/revocation; possible availability hold protects withdrawn content. |
| 9 CLI | New publish requires checked stage plus persisted scoped approval. Old folder flags yield migration guidance, not a bypass; deliberate operator workflow change. |
| 9 identity adoption | CAS same-edition legacy-only row adoption preserves tokens, tombstones, opt-outs/history/outbox and budget identity. Extra migration logic avoids missed immediate withdrawal after canonical ID appears. |
| 9 member sharing | Explicit member POST may bootstrap already-published valid article-only content; never fabricates media review/future consent. Additional narrow authority path preserves existing Share behavior. |
| 10 dependencies | Bind all earlier observed same-series/current-season periods until typed narrower historical operands exist. Conservative extra withdrawals/reviews are accepted; unchanged evidence must remain valid. |
| 10 execution revision | Whole-take replacements share original script/episode budget, preserve all attempts and old valid public take. Extra chain query complexity; no script repurchase or hidden earlier exposure. |
| 10 unknown content | Audited exact-attempt unrecoverable disposition fences original content while retaining financial uncertainty. Fresh bounded replacement can cost another charge, included in ceiling; active/unrelated holds still block. |
| 10 recovery queue | Existing original-worker loop consumes durable exact-identity recovery request. Extra narrow lease protocol makes UI recovery actionable without resend/new scheduler. |
| 10 recovered audio | Verify exact identity/full chunk set/bytes outside lock, CAS attach, then rerun only free ASR/render/QA. Missing provider timestamps alone cannot demand paid regeneration; unknown charges remain reserved. |
| 10 test teardown | Unmount before restoring mocks to prevent post-action effects calling undefined `.then`. Full-suite repeat confirms narrow test lifecycle repair; do not mislabel intermittence as baseline. |
| 11 external restore | All-instance deployment quarantine/fresh epoch handshake; no invented shared authority file. Extra operator coordination/unavailability; old DB alone cannot establish current consent. |
| 11 backup authority | Keep live backup credentials write-only. Offline complete exact-prefix absence after uploader fenced releases pins; 403/partial/age do not. Extra storage/manual maintenance protects recoverability without live backup erasure privilege. |
| 12 isolated harness | Disposable guarded PG, copied env-free Next, owned ports, throwaway real auth fixture, fake counted providers/ASR, real Linux/API validators. More setup yields integration evidence without production or paid access. |
| 12 period discovery | Lightweight current season/period discovery precedes due filtering; historical snapshots only when due, current season only. Daily previous period cannot suppress next Tuesday/new season; manual/paused/member gates remain independent. |
| 12 preview transport | Narrow authenticated preview forwards Range/If-Range, keeps lengths, HEAD bodylessness and caller abort. Preserve streaming/JWT authority; no object redirect or buffering. |
| 12 historical fixtures | Full PG sweep exposed latest-ORM fields in old-schema receipts and head downgrade crossing guarded migrations. Build actual old schemas, seed historical columns, roundtrip only reversible 0013 and assert later downgrade refusal; no product migration/constraint change. |
| 12 automatic preflight | Persist the free challenge in its own savepoint before checking for its completed result. Otherwise the expected readiness hold rolls back the queued stage forever. Repeated ticks retain one claimable challenge; unauthorized work still fails current policy/actor fences. |
| 12 selected-content idempotence | Automatic advancement skips exact already-selected current media without changing lifecycle or delivery. The existing outbox still owns checks/retries, including pending and policy-held projections; prevents false review attention without claiming content was delivered. |
| 12 catch-up test readiness | A final full Web run reproduced one disabled-button click race. Deferred record loading proves the ignored click; await enabled before clicking, with no timeout increase or product workaround. Full rerun required. |
| 12 sibling identity | Namespace episode/budget React keys. Duplicate series keys repeatedly remounted real populated panels and hid cap controls; unit collision check plus real saved-cap acceptance cover the defect. |

Proposed skill candidate (not created): project-scoped
`.Codex/skills/recap-release-evidence/SKILL.md`, triggered when changing recap
provider admission, publication, restore or local acceptance. It would collect
this repository's isolated test/runtime and external release gates; nothing
moves from AGENTS.md. Scope test: this description/body would not be safe in an
unrelated repository, so it belongs here rather than global skills. The runbook
remains directly usable without creating a skill.

## Final-review fix verification (2026-10-10)

The integrated product fixes passed 1,348 root tests, 1,570 normal API tests
(57 environment-gated skips), all 969 Web tests across 100 files, and 69
sequential disposable PostgreSQL tests. Twenty targeted boundary tests include
late dispatch/receipts in both calendars, atomic envelope conversion,
cross-episode reservation competition, delayed finished review after renewal,
and the actual authorized replacement through publication. Deleting or changing
the replacement disposition after finished approval blocks both selection and
projection. Two deliberate
mutations were killed and source restored byte-for-byte. TypeScript, Web lint
and production build exited zero; the existing Dashboard ref warning and Python
dependency warnings remain. No Python linter is configured. Publication scan
found no leaks; all 324 pilot hashes were unchanged. The final-fix report binds
these checks and the subsequent exact-image Linux/browser acceptance to their
actual commit/image identity. These are local synthetic measurements only.

## Earlier Task12 candidate evidence (2026-10-10)

The Task12 candidate was verified locally with root Python 3.12, existing Node/
Playwright and installed macOS Chrome, PostgreSQL 16, and the pinned Linux media
image built from the candidate tree. The final release commit/image identity must
be recorded again after independent parent reviews; this record is not deployment
proof. CI runs the same contracts but has not been executed remotely by this task.

- Root engine: 1,346 passed. Normal API: 1,550 passed, 56 environment-gated skips.
  Full Web: 969 passed across 100 files before a later full run exposed a
  catch-up test clicking its still-disabled control. Deferred record loading
  reproduces it; the test now waits for enabled state; full rerun passes all 969. The earlier undefined-then
  teardown failure did not recur. TypeScript, lint and build passed; existing Dashboard ref-cleanup
  warning and API dependency warnings remain. No Python linter is configured.
- Dedicated PG sweep: 68 passed, including exact historical migrations,
  concurrency, budgets, receipt recovery, publication and quarantined restore.
  Two initial fixture failures were fixed without changing product migrations.
- Integrated PG/Linux/Next acceptance: six passed; three distinct synthetic
  reviewed episodes then a fourth episode admitted and published by the existing
  automatic loop without another manual review. Sixteen unique admitted prose
  physical submissions and four unique admitted narration submissions. Saved receipt replay sent zero new requests.
  One unknown prose attempt remained one physical send across three new Gateway
  instances. Supplementary crash contracts cover raw receipt, unknown response,
  free-stage expiry and durable checkpoint restart.
- Real Linux contract: nine passed; five API-only tests intentionally skipped in
  image and covered by normal API suite. Unsupported default Docker refused
  before claim. Supported run tested actual isolated render/decode, failures,
  cancellation, two-chunk PCM seams and raw geometry/QA validation.
- Real authenticated 390×844 touch browser: edit $3.00 video cap to $0.01, save,
  reload, then real API `reserve_plan` of $0.02 rejects with
  `recap_budget_video_episode`. Private preview full/range/HEAD/416, signed-out
  denial, browser decode/seek, public decode/seek and no horizontal page overflow.
  All four public formats match selected SHA256 and exact range bytes; public
  article equals selected public projection. Revoke blocks new requests; explicit
  restore rotates token; material correction withdraws media immediately.
- `.recap-pilot`: all 324 original file hashes unchanged; AGENTS unchanged.

Failures exposed by integration: previous daily cadence suppressed new Tuesday/
season discovery; private authenticated proxy dropped Range/length/HEAD semantics;
nonempty episode and budget panels shared a React key, repeatedly remounting and
hiding cap controls; automatic preflight was rolled back by its own expected
readiness hold; repeated ticks on manual selections created false attention. Each has a regression and actual boundary evidence. Harness
adjustments (env-free copy needs local fonts, synthetic future clock, rotated token,
Node Headers versus jsdom, historical schema fixtures) are not product defects.

Retain complete command output outside Git; no private pilot, secret or raw log
snapshot belongs in this document. Reproduce summary JSON/screenshots with the
commands above. The test emits actual immutable Docker image ID plus admitted
attempt identities; screenshots include full admin, focused saved cap and public
player. Independent review, real source qualification, exact provider account/rate,
full voice/seam performance, target isolation/storage, actual device/recipient
preview and authorized deployment remain external release gates.
