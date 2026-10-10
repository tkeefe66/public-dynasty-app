"""Fixed lease render adapters. Only supervisor exchanges API assets."""
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
import wave

from media.runtime import run, MediaProcessFailure
from media.timeline import build_episode, digest_file

LIMIT = 64 * 1024 * 1024

def fence(lease):
    return {k: lease[k] for k in ("stage_id", "generation", "epoch", "input_digest")}

async def download(client, lease, identity, target):
    if identity not in lease["allowed_assets"]:
        raise RuntimeError("Unleased media asset refused")
    async with client.stream("GET", "/api/internal/media/assets/" + identity,
            headers={"X-Media-Lease": json.dumps(fence(lease))}) as response:
        response.raise_for_status()
        size = 0
        with target.open("wb") as stream:
            async for block in response.aiter_bytes():
                size += len(block)
                if size > LIMIT:
                    raise RuntimeError("Media asset exceeds 64 MiB; revise resource qualification, never truncate")
                stream.write(block)

async def upload(client, lease, path, mime):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as checked:
        info = os.fstat(checked.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= LIMIT:
            raise RuntimeError("Media output invalid or exceeds 64 MiB; revise resource qualification, never truncate")
        sha = hashlib.file_digest(checked, "sha256").hexdigest()
    async def chunks():
        with path.open("rb") as file:
            while block := file.read(1024*1024):
                yield block
    response = await client.post("/api/internal/media/assets", content=chunks(), headers={
        "X-Media-Lease":json.dumps(fence(lease)), "X-Content-SHA256":sha, "Content-Type":mime})
    response.raise_for_status()
    return response.json()["asset_id"]

def install(client, handlers):
    async def render(lease):
        with tempfile.TemporaryDirectory(prefix="render-", dir="/scratch") as temporary:
            root = Path(temporary)
            allowed = lease["allowed_assets"]
            if len(allowed) != len(lease["input"]["chunks"])+1:
                raise RuntimeError("Render prerequisite inventory mismatch")
            await download(client, lease, allowed[0], root/"transcript.json")
            audio_ids = list(reversed(allowed[1:]))
            for index, identity in enumerate(audio_ids):
                await download(client, lease, identity, root/f"chunk-{index}.mp3")
            spec=[dict(asset_id=identity,sha256=digest_file(root/f"chunk-{i}.mp3")) for i,identity in enumerate(audio_ids)]
            (root/"chunk-inputs.json").write_text(json.dumps(spec))
            await run(["/opt/venv/bin/python","-m","media.audio_seams","/work"],root,120)
            timing=json.loads((root/"chunks.json").read_text())
            with wave.open(str(root/"audio.wav")) as wav:
                duration = wav.getnframes()/wav.getframerate()
            try:
                episode = build_episode(lease["input"], json.loads((root/"transcript.json").read_text()), audio_ids,
                    digest_file(root/"audio.wav"), duration, aliases=lease["input"]["speech_review"]["aliases"], chunk_timing=timing)
            except ValueError as exc:
                # Original paid audio/raw speech remain in immutable prerequisites.
                return {"status":"input_failure", "asset_ids":[], "report":{"issues":[str(exc).split(":")[0]]}}
            (root/"episode.json").write_text(json.dumps(episode))
            try:
                await run(["/usr/bin/node", "/opt/recap/media/render/render.cjs", "--episode", "/work/episode.json", "--output", "/work"], root)
            except MediaProcessFailure as exc:
                if exc.report['reason']!='exit_nonzero' or not (root/"render-error.json").exists():
                    raise
                diagnostic=json.loads((root/"render-error.json").read_text())
                diagnostic['process_failure']=exc.report
                (root/"render-error.json").write_text(json.dumps(diagnostic))
                identity = await upload(client, lease, root/"render-error.json", "application/json")
                assets=[identity]
                if (root/"geometry-error.json").exists():
                    assets.append(await upload(client,lease,root/"geometry-error.json","application/json"))
                return {"status":"input_failure", "asset_ids":assets,
                    "report":{"issues":["render_failed"], "diagnostic_asset_id":identity}}
            await run(["/opt/venv/bin/python", "-m", "media.public_package", "/work"], root, 120)
            from media.public_package import DERIVATIVES
            files = {"video.mp4":"video/mp4", "audio.wav":"audio/wav", "episode.json":"application/json", "render.json":"application/json", **DERIVATIVES}
            rendered = json.loads((root/"render.json").read_text())
            files.update({frame["file"]:"image/png" for frame in rendered["representative_frames"]})
            if len(files) > 63:
                raise RuntimeError("Representative frame inventory exceeds lease asset bound")
            mapping = {name:await upload(client, lease, root/name, mime) for name,mime in files.items()}
            manifest = {"version":"recap-bundle-1", "files":mapping, "script_digest":lease["input"]["script_digest"]}
            (root/"manifest.json").write_text(json.dumps(manifest))
            identity = await upload(client, lease, root/"manifest.json", "application/json")
            return {"status":"ok", "asset_ids":[identity,*mapping.values()], "report":{"manifest_asset_id":identity}}

    async def check(lease):
        with tempfile.TemporaryDirectory(prefix="check-", dir="/scratch") as temporary:
            root = Path(temporary)
            await download(client, lease, lease["allowed_assets"][0], root/"manifest.json")
            manifest = json.loads((root/"manifest.json").read_text())
            files = manifest["files"]
            for name in ("video.mp4", "audio.wav", "episode.json", "render.json"):
                await download(client, lease, files[name], root/name)
            from media.public_package import DERIVATIVES
            for name in DERIVATIVES:
                if name in files:
                    await download(client, lease, files[name], root/name)
            try:
                await run(["/opt/venv/bin/python", "-m", "media.qa", "/work"], root)
            except MediaProcessFailure as exc:
                if (exc.report['reason']!='exit_nonzero' or not (root/"qa.json").exists()
                        or not json.loads((root/"qa.json").read_text()).get('issues')):
                    raise
            report = json.loads((root/"qa.json").read_text())
            frames = {}
            for frame in report["measurements"].get("representative_frames", []):
                frames[frame["file"]] = await upload(client, lease, root/frame["file"], "image/png")
            identity = await upload(client, lease, root/"qa.json", "application/json")
            return {"status":"input_failure" if report["issues"] else "ok", "asset_ids":[identity,*frames.values()],
                "report":{"qa_asset_id":identity, "issues":report["issues"], "frames":frames}}
    handlers.update(render=render, media_check=check)
