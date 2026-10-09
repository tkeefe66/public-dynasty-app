# Weekly recap video automation

Date: 2026-10-09
Status: reviewed proposal accepted in conversation; saved specification awaiting review.

## Purpose and approved decisions

Automatically produce a complete Dynasty Bitch weekly video recap after the
fantasy scoring period finishes, and publish it above the written recap on the
existing edition-scoped public URL. Keep routine operation free of manual steps
after qualification, with explicit holds for uncertain facts, provider outcomes,
or exceeded spending authority.

Tom accepted these decisions after reviewing the proposal and three independent
subagent critiques:

- Tuesday morning publication under the recommended readiness and correction
  policy. Earliest release is Tuesday at 08:00 in `America/Denver`, not a fixed
  UTC offset. Delayed games delay release automatically.
- Reasonable configurable spending caps, using the defaults below and conservative
  reservations before paid requests.
- Automatic generation and publication under standing policy after three
  reviewed weekly episodes pass qualification.

Creative choices are settled: fictional host Cal Mercer, The Gruff New Yorker,
angry and bitter local AM sports-radio delivery, natural profanity, full-league
coverage, useful variable length, and the approved animated-score visual design.
Do not reopen voice selection or impose the superseded 90-second limit.

This document records the accepted design. It does not activate production,
authorize a subscription purchase, create credentials, or submit paid media.
Exact voice/account qualification and deployment remain explicit release gates.
Do not alter `AGENTS.md` or replace the approved ignored pilot artifacts.

## Verified baseline

The investigation verified local HEAD, remote `main`, and successful Railway API
and Web deployments at `aacf3cca3abcdca0dd8e0a5e51f6751984a309ec`. The checkout was
clean before writing this specification. Reverify these facts before implementing
or releasing; they are an investigation snapshot, not a permanent assertion.

- Railway currently hosts API, Web, and Postgres. API has the persistent archive
  volume; no media worker or bucket exists yet.
- The published pilot is 137 seconds, attached to article revision 2, with MP4,
  MP3, poster, captions, and a revocable public share. Signed-out GET/HEAD checks
  confirmed its page, metadata, size and range support. Actual recipient preview
  appearance still needs qualification.
- `analyst_scheduler.py` submits free checks every 15 minutes. Current runtime
  uses private results packets followed by managed prose generation.
- Production Analyst policy is automatic, with Sonnet 4.6 draft/review and up to
  four calls. The monthly legacy AI cap is zero, meaning uncapped. No settings
  were changed during this investigation.
- `analyst.py` considers upstream week rollover and complete-looking scores,
  excludes fantasy playoffs, and does not continuously re-fetch archived weeks
  for corrections.
- Postgres already stores operations, leases, generation fences, provider
  receipts, content artifacts and a publication outbox. Operation success and
  successful reader projection are distinct.
- The current gateway is Anthropic-specific. Its budget check tests past known
  spend without reserving the next request. Provider hold/cooldown are global.
- Media attachment currently validates format signatures and sizes, copies an
  immutable bundle, and replaces a filesystem manifest. It does not decode
  assets or establish one DB transaction across article/share/media authority.
- The API has no ElevenLabs API key. The authenticated ElevenLabs UI showed
  Pay as you go, 2,058 used pilot credits and 7,942 remaining. This is not proof
  of shared-voice API entitlement or invoice pricing.

Relevant implementation: `api/app/services/analyst.py`, `analyst_scheduler.py`,
`generation/{models,policy,commands,worker,gateway,artifacts,publication}.py`,
`analyst_media.py`, `analyst_shares.py`, `api/app/routes/analyst_sharing.py`,
`web/components/RecapMedia.tsx`, and the public Analyst page/media proxy.

The current creative source is `.recap-pilot/active-voice-selection.json` and its
Gruff New Yorker reference, narration, receipt, timeline, verification, and v8
helpers. Earlier Reid locks and tracked 90-second pilot instructions are
historical. Keep real league/account/voice identifiers in protected configuration;
do not copy them into committed fixtures or this document.

## Architecture and ownership

Extend the existing generation controller with a registered media workflow and
explicit checkpoints. Use the existing Postgres queue and administrative control
surface. Do not introduce another scheduler, Redis, an event bus, or a general
workflow framework.

The API execution role owns source collection, prose generation, authorization,
share state, and reader publication. A separate Railway media service owns only
its assigned narration, verification and rendering stages. Claim filters must
enforce worker capability; starting another copy of the current unrestricted
worker is not sufficient. Only the API projector acknowledges reader archive
installation.

Use a restricted media-worker DB role or a narrow authenticated claim/heartbeat/
result API. Ordinary application database credentials would contradict the
worker's lack of publication authority. Renderer subprocesses receive approved
local inputs, packaged fonts/assets, no network, and a scrubbed environment.

Store new binary artifacts in a private Railway bucket. The API continues to
authorize and stream every public asset request. Do not expose public bucket
URLs or redirect to presigned URLs that bypass subsequent revocation checks.
Preserve the existing volume-hosted pilot through a compatible storage adapter.

Keep a global emergency stop, but scope provider credential failures, cooldowns,
rate limits and provider concurrency to provider/account. An ElevenLabs incident
holds media without blocking Anthropic prose. Aggregate budget ceilings still
apply across providers.

## Scoring-period readiness

Persist the season, fantasy week/round, constituent NFL weeks, participant
inventory, completion evidence, eligible release time and lifecycle of each
episode. An admitted period stays eligible after week or season rollover,
subject to current permissions and source revalidation. A newly requested
historical backfill still requires the existing historical authorization.

Release requires all of:

1. Expected NFL game inventory established independently of the current partial
   scoreboard response, with schedule revisions reconciled.
2. Relevant games final or subject to an authoritative league disposition.
3. Complete platform pairings, scores, starters and bracket/round evidence.
4. Two identical canonical competitive-facts fingerprints at least 60 minutes
   apart. Exclude observation timestamps and unrelated news from the fingerprint;
   include participants, pairings, scores, overrides and result-bearing state.
5. Tuesday 08:00 `America/Denver` reached, or later for delayed resolution.

The existing ESPN adapter must retain event IDs and status; it currently drops
them. Missing/partial/conflicting schedules, unresolved postponements and unknown
league dispositions hold without paid work. Two stable reads are a release
heuristic, not a promise against later stat corrections.

Fantasy playoffs are distinct from NFL postseason. Initial support targets the
configured league's actual rules. Every owner must have a verified status: title
path, placement/consolation game, bye, season finished, or unknown. Never pair
unmatched roster entries. Distinguish weekly points from aggregate round results
and do not declare a two-week championship decided halfway through. Unknown or
unsupported formats hold with a concrete reason rather than guessing.

## Facts, script and editorial contract

Retain full relevant source snapshots with provenance and original precision.
Compile a compact typed claim list for the show, with component player/owner
identities, source references, arithmetic and scope. The written recap's existing
trimmed starter packet is insufficient for some accepted pilot claims.

The coverage manifest comes from the verified participant inventory. Regular
weeks cover every matchup and owner. Playoff episodes include meaningful status
coverage for owners without a game; equal airtime and an individual roast quota
are not required.

Facts establish truth; the actually published roast provides revision/correction
context. Script and article must agree on overlapping factual claims but may
choose different highlights and jokes. Wait for reader publication, not just a
successful generation operation. A valid article publishes independently of
video availability. Private results packets never become public fallbacks.

Write a show with a strong league opening, varied transitions, meaningful
matchup context and a short callback. Maintain a small history of premises,
punchlines and targeted owners. Allow recurring catchphrases. Two to four minutes
is a planning estimate, not a duration requirement or permission to omit coverage.

Factual propositions embedded in jokes need evidence. Obvious figurative comedy
and Cal's exasperation do not. Do not invent personal anecdotes, medical context,
intentions or causal explanations. Counterfactual claims use legal lineup
calculations and distinguish a single substitution from a full optimal lineup.

Store approved spoken numeric renderings alongside exact values. Compute before
rounding; preserve outcomes, ranks, thresholds and close margins. Bounded writing
allows draft/review and at most one repair/review. Unresolved factual issues hold.

## Voice, audio and renderer

Use direct authenticated ElevenLabs with the exact approved voice and explicit
`eleven_v4` model selection. No browser automation, preset-ID translation, or
fallback voice. Preflight exact account/voice/model availability and rate before
each episode; capture only necessary metadata, not unrelated account details.

Official documentation currently supports v4 Text to Dialogue. Its timestamp
endpoint recommends at most 2,000 characters across text inputs. Start with that
conservative per-request bound, split at natural narrative boundaries, and count
the final submitted text including supported tags. Qualify model-specific
continuity settings. Do not split setup/punchline or number/unit pairs.

API access to this particular voice, account billing, voice rate adjustments and
equivalence to the approved delivery remain launch gates. After separate bounded
calibration authorization, test a realistic multi-chunk seam and full joined
performance. The approved voice itself is not up for reselection.

Record receipt identity promptly, save audio to private immutable storage, and
retain compact receipt metadata and hashes in Postgres. Separate response receipt,
audio persistence and usage reconciliation. Do not store base64 audio or secrets
in generic raw receipt JSON.

Preserve independent raw transcription. Compare semantic numbers, names,
negations, result verbs, ordering and completeness with the approved script.
Document orthographic aliases without silently correcting a spoken factual error.
Ambiguity holds for review. Forced alignment repairs timing only after spoken
content verification; it is not proof of what was said.

Port the approved visual design to deterministic frame-at-time Linux Chromium
rendering and FFmpeg muxing. Graphics derive from typed claims; captions derive
from approved words and verified audio timing. Pin renderer, fonts and assets.
Bound process runtime, memory, scratch space and concurrency; terminate and clean
up subprocesses on cancellation. Benchmark these limits before production.

QA checks complete decode, intact ending, synchronization within 100 ms, caption
bounds/readability, scene continuity, exact scores and full coverage, chunk seams,
unexpected silence/clipping and representative frames. Store measured results,
never copied success booleans. Phone playback/seeking/download and actual message
preview qualification remain required. Automated QA cannot prove subjective humor.

## Spending policy

Defaults accepted for this design:

| Scope | Maximum |
| --- | ---: |
| Video generation for one weekly episode, all revisions combined | $1.00 |
| Video generation for this league per calendar month | $5.00 |
| Written recap plus video for one weekly episode | $2.00 |
| Written recap plus video for this league per calendar month | $10.00 |

These are intersecting ceilings, not additive allowances. Use USD integer units.
Monthly policy windows use `America/Denver`; keep provider billing-cycle windows
separate. Existing application caps, when nonzero, also constrain admission.
Unrelated trade/profile work is outside these new league-recap subcaps, while any
configured app-wide cap still includes its applicable spending. Do not silently
change unrelated production settings while adding this feature.

Reserve the conservative maximum for the authorized episode plan transactionally
before its first paid request. Include all allowed script calls, narration chunks,
known rate adjustments and any authorized replacement. If the estimate cannot fit,
hold before purchasing; do not drop owners, truncate speech or exceed the cap.

At the observed normal base v4 rate, 2,000-4,000 narration characters cost
$0.16-$0.32 before voice/account adjustments. Planning estimates are $0.10-$0.35
for video writing/review and $0.10-$0.40 for the existing written recap. These are
estimates, not invoices. Request/token/chunk limits must make worst-case admission
enforceable. Unknown pricing prohibits dispatch.

Track provider/account, billing product, native units, rate evidence and immutable
price version. Separate reserved cost, calculated usage value, provider-reported
usage, included allowance consumption and confirmed invoice cost. Track credits
only if the actual account meters them. The pilot's Creative-credit receipt does
not establish API dollar pricing. Do not depend on introductory promotions.

Corrections/replacements remain attached to the original episode's budget identity.
Unknown outcomes retain their maximum exposure after cancellation and month
rollover. Release reservations only on evidence of settlement/non-submission or
an explicit audited financial reconciliation. Classify historical unknowns
separately; do not call cancelled unknown receipts active pending jobs or free.

No automatic paid retakes in the initial qualification phase. After qualification,
ordinary approved first takes may run under standing policy; ambiguous outcomes
or additional paid replacement attempts require a concrete bounded decision.

The estimated incremental operating envelope is approximately $9-$15/month if a
$6 Starter subscription is needed and worker idle use stays small. Included usage
must not be counted twice. This is not an enforced infrastructure cap. Measure
render and idle resources, storage and egress; provider upgrades and auto top-ups
are not automatically authorized. Do not use a project-wide hard infrastructure
stop that unexpectedly disables existing playback.

## Durable execution and recovery

One weekly episode identity spans media revisions, retries and renderer versions.
Unique admission prevents deployments or changed templates from repurchasing a
completed episode. Each checkpoint binds immutable source/article/script/policy
digests and stage identity. Paid replacements receive new authorized attempt
identities; do not reinterpret existing numeric-stage prose receipts.

Leases, heartbeats and execution epochs fence stale workers. Recheck current
policy and authority before each provider call and final publication. Existing
completed paid stages are reused after a crash. Artifact installation can retry
without generation. Transient free failures use bounded backoff; deterministic
failures stop rather than repeatedly testing unchanged input.

Never blindly resend an uncertain provider request. Reconcile by exact request/
history identity and retained artifacts; balance movement alone is insufficient.
If no unique recoverable result exists, display the uncertain exposure and request
one bounded replacement decision. Provider exactly-once execution is not promised.

## Publication, corrections and sharing

Use one authoritative DB publication record binding article revision, facts digest,
approval/policy revision, sharing decision/version, withdrawal status and selected
media pointer. Upload/hash/verify objects before the short conditional publication
transaction. Do not hold the global control lock during network transfer or render.

Public reads enforce current authority. Filesystem manifests/outbox projections
cannot independently expose withdrawn or superseded content. Check pause,
correction and revocation races between upload, selection and projection.

Keep one normal no-login URL per edition. Replacements preserve that URL; weeks
remain edition-scoped. Standing policy may create a new edition link only for the
approved league/season. It does not authorize sending texts or other messages.
Manual edition revocation persists as an opt-out tombstone. A separate control
disables future league sharing. Automatic jobs cannot undo either decision;
explicit authorized manual action is required to re-enable access.

Reconcile fresh competitive facts through Friday after release, then at lower
frequency through the season and during relevant refreshes. Track dependencies
on prior weeks' standings/streak/bracket evidence. A material contradiction
withdraws affected content from new public reads immediately, with a correction
status at the same URL. Withdrawal must not wait for a paid correction to succeed.
Correct article and media under the same caps and validation rules.

Initially every article revision requires reviewed media reattachment. Defer an
automatic typo-equivalence system. Revocation cannot recall downloads, buffered
playback, already-started responses or cached message previews. Redact share-token
URL paths in application/proxy/access logs and telemetry.

## Retention and restore

| Material | Retention |
| --- | --- |
| Published episodes and approved masters | Until explicitly removed |
| Facts, scripts, receipts and QA reports | Life of edition |
| Failed/superseded takes | 90 days; longer while unresolved |
| Disposable render frames | 7 days |
| Unreferenced uploads | Reconciled garbage collection with a grace period |
| Objects referenced by retained backups | Until those recovery points expire |

Provider history retention is compatible with request reconciliation; do not
promise enterprise zero-retention and history recovery simultaneously. Limit
provider payloads to approved content. Protect private facts, drafts and receipts
from public metadata/routes.

Back up DB references, legacy files, required object keys/hashes and revocation
state. Restore into execution and public-serving quarantine. Reconcile all sets
before reopening. If later revocations cannot be recovered, affected old tokens
stay disabled rather than resurrecting access from an older backup.

## Operator experience

Extend Admin -> AI writing with the episode, exact stage, known/reserved/uncertain
cost, concrete failure and recommended action. Provide review-and-publish, resume
free work, restore access, reconcile request, approve bounded replacement, skip
video and disable sharing. No generic retry that silently authorizes another
purchase. No repeated notifications for unchanged 15-minute observations.

During qualification, one finished-preview approval per episode is sufficient;
do not ask for approval at every stage. After qualification, routine episodes
require no user action. Ambiguous audio, unresolved facts, exceeded caps and
unqualified playoff formats retain explicit holds.

## Qualification and implementation boundaries

1. Readiness: preserve private approved assets, verify exact provider metadata
   and rate, define the league's fixtures and enforce unknown-state holds.
2. Offline production: reproduce the pilot with saved audio; verify correctness,
   resource limits, duplicate prevention, crashes, worker routing and restoration
   without paid calls.
3. Reviewed rollout: separately authorize a bounded API calibration, then produce
   three full weekly episodes with one finished-preview approval each. Require
   factual/coverage/performance acceptance, reconciled receipts and real mobile/
   message-preview checks. No silent advancement on unresolved findings.
4. Automatic mode: after those gates pass, apply the accepted standing policy for
   this league/current season. New seasons and material provider/template changes
   require requalification. First unqualified postseason/championship formats
   retain review. Confirm Railway target services before the first deployment.

Acceptance tests must include late/postponed games, partial/empty schedules,
canonical stability, stat corrections, two unmatched owners, placement games,
ties and unfinished multi-week rounds; numeric rounding/thresholds; wrong spoken
score, missing negation, duplicated chunk and omitted closing sentence; unknown
provider outcomes and cost reservations across cancellation/month rollover;
worker capability isolation; article/pause/revoke races; signed-out ranges and
downloads; and restore after post-snapshot revocation. Three successful episodes
are qualification evidence, not proof that future content cannot contain errors.

## Alternatives and review reconciliation

The separate media worker isolates Chromium/FFmpeg CPU and memory from readers.
A same-host subprocess saves setup but couples availability. Browser automation
retains the pilot's session/download failure modes; an all-in-one generated-video
service adds cost and risks approved style drift. Article-only adaptation loses
facts; facts-only production can miss article corrections. The combined contract
uses facts as authority and pins the published article revision.

Independent architecture, editorial and cost/security reviews changed the draft:

- Added worker routing and API-owned archive projection.
- Replaced vague atomic publication with explicit DB authority and read gates.
- Added durable period eligibility and restore serving quarantine.
- Required full-source claim evidence, not the article's trimmed facts.
- Distinguished transcription/content verification from forced alignment.
- Scoped failures by provider and metering by actual account/product.
- Kept correction allowances under the original episode cap.
- Deferred automatic typo equivalence and generalized workflow infrastructure.

Remaining technical gates are authenticated exact-voice entitlement/rate,
representative API performance, reliable expected-game inventory, supported league
format fixtures, enforceable worker/storage permissions and measured resources.
These are investigation/qualification requirements, not reopened creative choices.

## Research sources

- [ElevenLabs models](https://elevenlabs.io/docs/overview/models)
- [Dialogue with timestamps](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert-with-timestamps)
- [Voice Library eligibility](https://elevenlabs.io/docs/eleven-creative/voices/voice-library)
- [Voice metadata](https://elevenlabs.io/docs/api-reference/voices/get)
- [ElevenAPI pricing](https://elevenlabs.io/pricing/api)
- [Sleeper stat corrections](https://support.sleeper.com/en/articles/2441282-stat-corrections)
- [Sonnet 4.6 pricing](https://platform.claude.com/docs/en/models/sonnet-4-6/overview)
- [Railway pricing](https://docs.railway.com/pricing/plans)
- [Railway private storage](https://docs.railway.com/storage-buckets)
- [Bucket billing](https://docs.railway.com/storage-buckets/billing)

Prices and account behavior were inspected on 2026-10-09. Recheck exact authenticated
terms before purchases; catalog prices and the observed pilot credit balance do
not prove the eventual invoice.
