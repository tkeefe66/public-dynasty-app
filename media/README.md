# Restricted recap media worker

Media remains disabled until API qualification is explicitly installed. This package
does not grant publication authority. API owns source, prose, immutable script,
paid dispatch, object selection and publication; supervisor only receives dedicated
media API credentials and the narration provider key. Do not supply database,
bucket, general admin or publication credentials.

Build `docker build -f media/Dockerfile -t recap-media .`. Offline contract:

```sh
docker run --rm --network none --memory 2g --tmpfs /scratch:size=4g \
  --cap-add SYS_ADMIN --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
  -e BOUNDARY_SECRET=recap-boundary-sentinel -e RECAP_LINUX_TEST=1 -e TMPDIR=/scratch \
  recap-media python scripts/check_recap_media_runtime.py
```

These flags are tested local Docker capabilities, **not a Railway configuration**.
Default Docker restrictions cannot mount the child's private `/proc`; startup
refuses before claiming work. Railway release must demonstrate equivalent child
mount/user/PID/network separation and bounded scratch/memory. Do not replace that
gate with environment filtering or a whole-container network test. A credentialed
supervisor needs API/provider network while its children must have none.

`python -m media.worker` probes that boundary and verifies pinned ASR model files
in `/opt/model` before reading HTTPS `MEDIA_API_URL`, `MEDIA_WORKER_TOKEN` and
`ELEVENLABS_API_KEY`. Package only the four model files required by
`audio.verify_model_artifacts`; mount read-only. Never mount a developer checkout,
home, host root or `.recap-pilot` into the worker image. Existing ASR and FFmpeg
calls use the same sandbox as Chromium and QA. Every child sees only packaged
runtime, assigned work directory, fresh `/proc`, nonroot UID and no network.

One worker replica remains required. API serializes current render leases and the
worker holds a local flock; lease expiry does not physically fence a zombie in a
different replica. Each child deadline is at most 20 minutes, container memory
must be at most 2 GiB and scratch tmpfs at most 4 GiB. Uploads/downloads reject
objects above 64 MiB without truncation. Current 137-second/four-minute benchmarks
fit those bounds; benchmarks are not production capacity or voice qualification.

CLI: `node media/render/render.cjs --episode <json> --output <directory>`;
directory contains `audio.wav` with the episode's bound SHA256. Capture uses
`ceil(duration*30)` frames at 1280×720 and muxes H.264/AAC. `python -m media.qa
<directory>` measures full decode, actual decoded first timestamps, endings,
audio levels, caption bounds and retained decoded representative frames.

Two-second synthetic fixtures live in `api/tests/fixtures/recap_media` and can be
regenerated with the isolated image's `scripts/benchmark_recap_media.py short`
and a writable `/outputs` bind. Their tone is not speech-validation evidence.
Approved-script visual planning rejects ambiguous owner/result/status anchors
before paid narration; speech timing is independently verified afterward.
An ambiguous paid take stays available for explicit review/recovery.
