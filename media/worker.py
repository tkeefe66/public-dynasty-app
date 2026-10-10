"""Restricted worker runner. No database, source, prose or publication imports.

Deploy supervisor supplies only API URL + dedicated media credential. Narration
adapter may receive ElevenLabs key; rendering must get explicit allowlisted env.
Task7/8 install handlers; none qualify by default. Restart reconciles via API.
"""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

HANDLERS = {}
MEDIA_KINDS = frozenset({"preflight", "narrate", "speech_check", "render", "media_check"})


async def run_stage(lease: dict) -> dict:
    kind = lease.get("capability")
    if kind not in MEDIA_KINDS or kind not in HANDLERS:
        raise RuntimeError("Media handler is not qualified for this stage")
    # Paid handler must request one-time dispatch authority. Never recover authority
    # from disk, cache, result polling or retries. Lost response means reconciliation.
    return await HANDLERS[kind](lease)


async def run_claim(client, lease):
    fence = {key: lease[key] for key in ("stage_id", "generation", "epoch", "input_digest")}
    async def execute():
        from media.runtime import MediaProcessFailure
        try:
            return await run_stage(lease)
        except MediaProcessFailure as exc:
            data=json.dumps({**exc.report,"stage_kind":lease["capability"]}).encode()
            response=await client.post("/api/internal/media/assets",content=data,headers={
                "X-Media-Lease":json.dumps(fence),"X-Content-SHA256":hashlib.sha256(data).hexdigest(),"Content-Type":"application/json"})
            response.raise_for_status()
            identity=response.json()["asset_id"]
            return {"status":"input_failure","asset_ids":[identity],"report":{
                "issues":["process_"+exc.report["reason"]],"diagnostic_asset_id":identity}}
    task = asyncio.create_task(execute())
    async def heartbeat():
        while True:
            await asyncio.sleep(30)
            response = await client.post("/api/internal/media/heartbeat", json=fence)
            response.raise_for_status()
    pulse = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait((task, pulse), return_when=asyncio.FIRST_COMPLETED)
        if pulse in done:
            await pulse  # Any heartbeat failure cancels execution; never send completion.
        result = await task
        response = await client.post("/api/internal/media/complete", json={**fence, "result": result})
        response.raise_for_status()
    finally:
        for pending in (pulse, task):
            pending.cancel()
        await asyncio.gather(pulse, task, return_exceptions=True)


async def tick(client):
    """Claim only fixed server capabilities. Client transport must disable retries."""
    response = await client.post("/api/internal/media/claim", json={})
    response.raise_for_status()
    lease = response.json()
    if lease is None:
        return False
    await run_claim(client, lease)
    return True


def renderer_environment(work_dir):
    """Passed explicitly to subprocess; never copy API/provider/cloud environment."""
    return {"PATH": "/usr/bin:/bin", "HOME": str(work_dir), "TMPDIR": str(work_dir), "LANG": "C.UTF-8"}


def install_narration_handlers(client, *, api_key, model_directory, ffmpeg="/usr/bin/ffmpeg"):
    """Supervisor wiring only; provider key stays in this process, never ASR children.

    Deployment must package api/app/services/recap_video pure audio/provider modules
    on PYTHONPATH, plus worker-only dependencies and verified local model files.
    """
    from app.services.recap_video.elevenlabs import ElevenLabsTransport, canonical, preflight_voice

    async def post(path, **kwargs):
        response = await client.post("/api/internal/media/" + path, **kwargs)
        response.raise_for_status()
        return response.json()

    def fence(lease):
        return {key: lease[key] for key in ("stage_id", "generation", "epoch", "input_digest")}

    async def upload(lease, data, content_type):
        return await post("assets", content=data, headers={"X-Media-Lease": json.dumps(fence(lease)),
            "X-Content-SHA256": hashlib.sha256(data).hexdigest(), "Content-Type": content_type})

    async def preflight(lease):
        config = lease["input"]["config"]
        adapter = ElevenLabsTransport(api_key, None, None)
        async with adapter.client() as http:
            report = await preflight_voice(http, config["voice_id"], config["model_id"])
        return {"status": "ok", "asset_ids": [], "report": report}

    async def narrate(lease):
        authority = await post("authorize-dispatch", json=fence(lease))
        attempt_id = authority["attempt_id"]
        async def identity(value):
            await post("identity", json={"attempt_id": attempt_id, "identity": value})
        async def audio(data, sha):
            return await upload(lease, data, "audio/mpeg")
        # Persisted API request is authoritative, even if local lease input differs.
        paid = {**lease["input"]["paid"], "request": authority["request"]}
        receipt = await ElevenLabsTransport(api_key, identity, audio).send(paid)
        await post("receipt", json={"attempt_id": attempt_id, "receipt": receipt})
        if receipt["outcome"] != "received":
            return {"status": "input_failure", "asset_ids": [], "report": {"reason": receipt["error"]}}
        return {"status": "ok", "asset_ids": [receipt["asset"]["asset_id"]], "report": {"receipt_digest": canonical(receipt)}}

    async def speech(lease):
        with tempfile.TemporaryDirectory(prefix="recap-speech-") as temporary:
            root = Path(temporary)
            # Prerequisite chain is newest-first; narration chronological order is reverse.
            asset_ids = list(reversed(lease["allowed_assets"]))
            if len(asset_ids) != len(lease["input"]["chunks"]):
                raise RuntimeError("Speech check narration asset count mismatch")
            entries = []
            for index, asset_id in enumerate(asset_ids):
                async with client.stream("GET", "/api/internal/media/assets/" + asset_id,
                        headers={"X-Media-Lease": json.dumps(fence(lease))}) as response:
                    response.raise_for_status()
                    size = 0
                    with (root / f"chunk-{index}.mp3").open("wb") as file:
                        async for block in response.aiter_bytes():
                            size += len(block)
                            if size > 64 * 1024 * 1024:
                                raise RuntimeError("Speech input exceeds asset limit")
                            file.write(block)
                from media.timeline import digest_file
                entries.append(dict(asset_id=asset_id,sha256=digest_file(root/f"chunk-{index}.mp3")))
            (root / "chunk-inputs.json").write_text(json.dumps(entries))
            # Same per-chunk PCM decode as render; ASR timestamps must not use a
            # different MP3 concat-demuxer padding basis.
            await _bounded_process([sys.executable,"-m","media.audio_seams",str(root)],root,120)
            await _bounded_process([ffmpeg, "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(root / "audio.wav"),
                "-ac", "1", "-ar", "16000", str(root / "joined.wav")], root, 120)
            module = Path(__file__).resolve().parents[1] / "api/app/services/recap_video/audio.py"
            await _bounded_process([sys.executable, str(module), str(root / "joined.wav"),
                str(model_directory), str(root / "raw.json")], root, 600)
            data = (root / "raw.json").read_bytes()
            asset = await upload(lease, data, "application/json")
            from app.services.recap_video.audio import verify_speech
            checked = verify_speech(lease["input"]["script"], json.loads(data),
                reviewed_aliases=lease["input"]["speech_review"]["aliases"])
        return {"status": "ok" if checked["passed"] else "input_failure", "asset_ids": [asset["asset_id"]],
            "report": {"transcript_asset_id": asset["asset_id"], "audio_asset_ids": asset_ids, "issues": checked["issues"]}}

    HANDLERS.update(preflight=preflight, narrate=narrate, speech_check=speech)


async def _bounded_process(argv, directory, timeout):
    from media.runtime import run
    # Translate assigned host scratch to the only writable child mount.
    translated = [str(value).replace(str(directory), "/work") for value in argv]
    await run(translated, directory, timeout)


async def recover_narration(client, attempt_id, *, api_key):
    """Explicit free recovery of existing identity. No claim/dispatch/completion."""
    from app.services.recap_video.elevenlabs import ElevenLabsTransport
    response = await client.get("/api/internal/media/attempts/" + attempt_id + "/recovery")
    response.raise_for_status()
    saved = response.json()
    if saved["recovery_receipt"]:
        return saved["recovery_receipt"]
    async def identity(value):
        result = await client.post("/api/internal/media/identity", json={"attempt_id": attempt_id, "identity": value})
        result.raise_for_status()
    async def audio(data, sha):
        result = await client.post("/api/internal/media/attempts/" + attempt_id + "/audio", content=data,
            headers={"Content-Type": "audio/mpeg", "X-Content-SHA256": sha})
        result.raise_for_status()
        return result.json()
    receipt = await ElevenLabsTransport(api_key, identity, audio).recover(saved["request"], saved["identity"])
    result = await client.post("/api/internal/media/recovery-receipt", json={"attempt_id": attempt_id, "receipt": receipt})
    result.raise_for_status()
    return receipt


async def main():
    """Single-claim supervisor. Runtime admission occurs before credentials/network."""
    import fcntl
    import logging
    import httpx
    from urllib.parse import urlparse
    from media.runtime import probe
    from media.adapters import install
    from app.services.recap_video.audio import verify_model_artifacts
    log = logging.getLogger("recap.worker")
    logging.basicConfig(level=logging.INFO)
    lock = open("/scratch/worker.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with tempfile.TemporaryDirectory(prefix="probe-", dir="/scratch") as temporary:
        probe(Path(temporary))
    verify_model_artifacts(Path("/opt/model"))
    tempfile.tempdir = "/scratch"
    url, token = os.environ.get("MEDIA_API_URL", ""), os.environ.get("MEDIA_WORKER_TOKEN", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or not token:
        raise RuntimeError("Worker API configuration invalid; set HTTPS API origin and dedicated worker token")
    # No DB, bucket or publication settings are accepted by this entrypoint.
    async with httpx.AsyncClient(base_url=url, headers={"Authorization":"Bearer "+token},
            transport=httpx.AsyncHTTPTransport(retries=0), follow_redirects=False, timeout=120) as client:
        install_narration_handlers(client, api_key=os.environ.get("ELEVENLABS_API_KEY", ""), model_directory="/opt/model")
        install(client, HANDLERS)
        while True:
            try:
                if not await tick(client):
                    await asyncio.sleep(5)
            except (httpx.HTTPError, RuntimeError):
                # Original lease/attempt remains server-owned. Do not resend paid
                # requests; reconciliation is explicit through saved receipts.
                log.error("Media stage stopped; API unavailable, ownership lost, or runtime refused. Inspect durable stage evidence.")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
