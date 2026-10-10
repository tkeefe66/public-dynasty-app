"""API-owned immutable render selection and raw QA validation; no execution here."""
import asyncio
import hashlib
import io
import json
import wave

from app.services.generation.recap_models import RecapAsset, RecapStage
from app.services.generation.store import Held, dump
from app.services.recap_video.storage import configured_store

async def read(db, identity, *, stage=None, mime="application/json", maximum=2_000_000):
    asset = await db.get(RecapAsset, identity)
    if (not asset or asset.media_type != mime or asset.size > maximum or stage is not None and
            (asset.stage_id != stage.id or asset.generation != stage.generation)):
        raise Held("render_asset_invalid")
    data = await asyncio.to_thread(configured_store().read_range, asset.storage_key, 0, asset.size-1)
    if hashlib.sha256(data).hexdigest() != asset.digest:
        raise Held("render_asset_corrupt")
    return asset, data

async def bundle(db, stage, result):
    from media.timeline import build_episode
    try:
        identity = result["report"]["manifest_asset_id"]
        _, data = await read(db, identity, stage=stage)
        manifest = json.loads(data)
        files = manifest["files"]
        inputs = json.loads(stage.input_json)
        if (manifest["version"] != "recap-bundle-1" or manifest["script_digest"] != inputs["script_digest"]
                or result["asset_ids"] != [identity, *files.values()] or len(set(result["asset_ids"])) != len(result["asset_ids"])):
            raise ValueError()
        episode_asset, data = await read(db, files["episode.json"], stage=stage)
        episode = json.loads(data)
        speech = await db.get(RecapStage, stage.predecessor_id)
        if not speech or speech.kind != "speech_check" or speech.state != "succeeded" or speech.script_id != stage.script_id:
            raise ValueError()
        speech_evidence = json.loads(speech.evidence_json)
        _, data = await read(db, speech_evidence["transcript_asset_id"], stage=speech)
        raw = json.loads(data)
        audio, data = await read(db, files["audio.wav"], stage=stage, mime="audio/wav", maximum=64*1024*1024)
        with wave.open(io.BytesIO(data)) as wav:
            duration = wav.getnframes()/wav.getframerate()
        expected = build_episode(inputs, raw, speech_evidence["audio_asset_ids"], audio.digest, duration,
            aliases=speech_evidence["speech_review"]["aliases"],chunk_timing=episode['chunk_timing'])
        for chunk in episode['chunk_timing']:
            source=await db.get(RecapAsset,chunk['asset_id'])
            if not source or source.digest!=chunk['sha256']:
                raise ValueError()
        if expected != episode:
            raise ValueError()
        _, data = await read(db, files["render.json"], stage=stage)
        rendering = json.loads(data)
        if rendering["input_sha256"] != episode_asset.digest or rendering["layout_issues"]:
            raise ValueError()
        from pathlib import Path
        from media.timeline import digest_file
        package = Path(__file__).resolve().parents[4]/"media/render"
        if rendering["scripts"] != {name:digest_file(package/name) for name in ("render.cjs", "scene.js", "style.css", "index.html")}:
            raise ValueError()
        assets = {}
        for name, ident in files.items():
            asset = await db.get(RecapAsset, ident)
            if not asset or asset.stage_id != stage.id or asset.generation != stage.generation:
                raise ValueError()
            assets[name] = asset
        for frame in rendering["representative_frames"]:
            if assets[frame["file"]].digest != frame["sha256"] or assets[frame["file"]].media_type != "image/png":
                raise ValueError()
        if not rendering["representative_frames"] or assets["video.mp4"].media_type != "video/mp4":
            raise ValueError()
        return episode, assets
    except (KeyError, ValueError, TypeError, wave.Error):
        raise Held("render_bundle_invalid") from None

async def validate_render(db, stage, result):
    episode, assets = await bundle(db, stage, result)
    stage.evidence_json = dump({"renderer_version":episode["renderer_version"], "files":{k:v.id for k,v in assets.items()}})

async def validate_check(db, stage, result):
    from app.services.recap_video.contracts import require_media_measurements
    try:
        identity = result["report"]["qa_asset_id"]
        frames = result["report"]["frames"]
        if result["asset_ids"] != [identity,*frames.values()]:
            raise ValueError()
        _, data = await read(db, identity, stage=stage)
        report = json.loads(data)
        prior = await db.get(RecapStage, stage.predecessor_id)
        if not prior or prior.kind != "render" or prior.state != "succeeded" or prior.script_id != stage.script_id:
            raise ValueError()
        episode, assets = await bundle(db, prior, json.loads(prior.result_json))
        _,render_data=await read(db,assets['render.json'].id,stage=prior)
        if report['render']!=json.loads(render_data):
            raise ValueError()
        require_media_measurements(report, episode, assets)
        from media.public_package import DERIVATIVES, evidence_issues, captions_vtt
        if any(name in assets for name in DERIVATIVES):
            if not all(name in assets and assets[name].media_type == mime for name,mime in DERIVATIVES.items()):
                raise ValueError()
            if evidence_issues(report.get('public_derivatives', {}), episode,
                    {name:assets[name].digest for name in DERIVATIVES}):
                raise ValueError()
            _, captions = await read(db, assets['captions.vtt'].id, stage=prior, mime='text/vtt')
            if captions.decode('utf-8') != captions_vtt(episode):
                raise ValueError()
        for frame in report["measurements"]["representative_frames"]:
            asset, _ = await read(db, frames[frame["file"]], stage=stage, mime="image/png")
            if asset.digest != frame["sha256"]:
                raise ValueError()
        stage.evidence_json = dump({"qa_asset_id":identity, "renderer_version":episode["renderer_version"], "measurements":report["measurements"]})
    except (KeyError, TypeError, ValueError):
        raise Held("media_measurements_invalid") from None

def install_api():
    from app.services.recap_video.workflow import RESULT_VALIDATORS
    RESULT_VALIDATORS.update(render=validate_render, media_check=validate_check)
