# On-demand media worker controller

This Railway cron service owns one isolated render VM while media work is pending.
It never generates narration itself. The API retains the stage leases, immutable
provider attempts, generation budget, and publication authority.

Deploy from the monorepo root using `media/controller/railway.json`, attach one
persistent volume at `/state`, and keep one replica. Do not add a public domain.
The process lock and atomic state file survive cron runs and deployments.

Required service variables:

| Variable | Source |
| --- | --- |
| `RAILWAY_TOKEN` | Dedicated project token for the production environment |
| `RAILWAY_ENVIRONMENT_ID` | Target environment configuration |
| `RECAP_WORKER_CHECKPOINT` | Credential-free, tested worker VM checkpoint |
| `RECAP_WORKER_IMAGE` | Exact Docker image ID, `sha256:` plus 64 hex digits |
| `MEDIA_CONTROL_API_URL` | API private origin, including its configured port |
| `MEDIA_API_URL` | Worker HTTPS gateway origin |
| `MEDIA_WORKER_TOKEN` | Dedicated API worker credential |
| `ELEVENLABS_API_KEY` | Existing approved provider account credential |

Never copy a developer's Railway login token into this service. Checkpoints must
contain no worker or provider credentials. Only after the controller persists the
new VM's identity does it send credentials over exec stdin to its supervisor.
Neither renderer child processes nor ASR child processes inherit them.
The checkpoint must contain the four checksum-pinned speech model files in
`/opt/recap-model`; bootstrap mounts that directory read-only at `/opt/model`.
Worker admission verifies every checksum before making any API claim.

The five-minute cron starts the controller. Idle demand creates no VM. During work
it checks every 30 seconds, and after five idle minutes it requests a worker drain.
The worker acknowledges only after its current tick completes and never claims
again afterward. Only that acknowledgement permits idle destruction. A controller
restart resumes the same draining or destroying identity. Ambiguous VM creation
is recovered using its unique nonce; it is never blindly repeated.

The controller permits at most two launches in a rolling day and a one-hour VM
lifetime. These are infrastructure bounds, separate from generation spending
caps. Creation attempts reserve a launch before the cloud request; failed or
unconfirmed attempts still count, even if no running VM is found. When demand
exceeds that limit, the cron exits successfully with `waiting_daily_limit`, the
attempt count, and `next_eligible_at` in UTC. The next scheduled run at or after
that time can resume queued work; no counter reset or manual retry is needed.
The hard lifetime can interrupt a stuck stage; the API must reconcile its
durable receipt before any replacement. A ten-minute idle VM timeout limits
orphan lifetime if the controller itself is unavailable. API demand outages do
not bypass reconciliation of an existing VM or authorize another launch.

Failures emit `recap_controller_failure` with the operation (`cloud.create`,
`cloud.start`, `store.read`, etc.), last saved phase, allowlisted error type/code,
HTTP or transport status, and a reconciliation instruction. Worker startup/drain
failures include exit code and timeout status. Messages, response bodies, command
arguments, and credentials are never logged. Unknown creation outcomes retain
their nonce and quota reservation; the next cron reconciles instead of resending.

Before activating weekly generation, verify a real restart/drain/destruction
cycle, the current image's isolated Linux runtime, provider billing and voice
qualification, database publication reconciliation, and the owner's member-only
standing authorization. Deploying this controller does not grant any of those
authorities. Existing public recap links remain governed independently.

Validation: `npm ci`, `npm test`, and `npm run check` in this directory. Python
bootstrap and worker-drain tests run with the API test suite.
# Independent recap monitor watchdog

The controller also checks the authenticated `/api/internal/media/recap-monitor-health`
endpoint independently of media demand. Enable `RECAP_WATCHDOG_ENABLED=true` and set
`RECAP_WATCHDOG_TO`, `RECAP_WATCHDOG_FROM`, and `RECAP_WATCHDOG_RESEND_API_KEY` on the
controller service. The sender and mail credential can use Railway references to the
API's existing verified sender and Resend key. Never put their values in the repository.

Each five-minute cron checks API reachability, monitor configuration, heartbeat,
stalled cycles, and overdue checks. Ten minutes of unsuccessful watchdog observations
opens one email incident. Brief restarts and normal weekly idle remain silent.
Incident state persists separately at `/state/recap-watchdog.json`; retries reuse the
same email payload and idempotency key. Healthy observations silently rearm it.
This watchdog runs separately from the API, but still depends on Railway and Resend;
a simultaneous platform or mail-provider outage requires an external monitoring service.
