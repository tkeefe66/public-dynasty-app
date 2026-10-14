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

The five-minute cron starts the controller. Idle demand creates no VM. During work
it checks every 30 seconds, and after five idle minutes it requests a worker drain.
The worker acknowledges only after its current tick completes and never claims
again afterward. Only that acknowledgement permits idle destruction. A controller
restart resumes the same draining or destroying identity. Ambiguous VM creation
is recovered using its unique nonce; it is never blindly repeated.

The controller permits at most two launches in a rolling day and a one-hour VM
lifetime. These are infrastructure bounds, separate from generation spending
caps. The hard lifetime can interrupt a stuck stage; the API must reconcile its
durable receipt before any replacement. A ten-minute idle VM timeout limits
orphan lifetime if the controller itself is unavailable. API demand outages do
not bypass reconciliation of an existing VM or authorize another launch.

Before activating weekly generation, verify a real restart/drain/destruction
cycle, the current image's isolated Linux runtime, provider billing and voice
qualification, database publication reconciliation, and the owner's member-only
standing authorization. Deploying this controller does not grant any of those
authorities. Existing public recap links remain governed independently.

Validation: `npm ci`, `npm test`, and `npm run check` in this directory. Python
bootstrap and worker-drain tests run with the API test suite.
