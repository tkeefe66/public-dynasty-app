"""Restricted worker runner. No database, source, prose or publication imports.

Deploy supervisor supplies only API URL + dedicated media credential. Narration
adapter may receive ElevenLabs key; rendering must get explicit allowlisted env.
Task7/8 install handlers; none qualify by default. Restart reconciles via API.
"""
import asyncio

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
    task = asyncio.create_task(run_stage(lease))
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
