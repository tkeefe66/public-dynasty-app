"""Offline renderer tests. Synthetic fixtures only; Linux integration is explicit."""
import copy
import importlib
import os
from pathlib import Path
import pytest


def test_sync_limit_is_measured():
    # Mutation: inclusive limit or one-sided subtraction accepts >100 ms drift.
    qa = importlib.import_module("media.qa")
    assert qa.check_sync(audio_start_ms=30, video_start_ms=0) == []
    assert qa.check_sync(audio_start_ms=100, video_start_ms=0) == []
    assert qa.check_sync(audio_start_ms=101, video_start_ms=0) == ["av_sync_exceeded"]
    assert qa.check_sync(audio_start_ms=0, video_start_ms=101) == ["av_sync_exceeded"]


def test_timeline_rejects_duplicate_chunk_and_wrong_score():
    # Mutation: trust worker graphics or ignore duplicate input audio identity.
    timeline = importlib.import_module("media.timeline")
    episode = timeline.synthetic_episode(2)
    assert timeline.validate_episode(episode) == []
    bad = copy.deepcopy(episode)
    bad["scenes"][1]["winner_points"] = "999"
    assert "score_graphic_mismatch" in timeline.validate_episode(bad)
    bad = copy.deepcopy(episode)
    bad["audio_chunks"] *= 2
    assert "duplicate_chunk" in timeline.validate_episode(bad)


def test_timeline_rejects_invalid_bounds():
    # Mutation: allow overlapping captions or scenes beyond the actual ending.
    timeline = importlib.import_module("media.timeline")
    bad = timeline.synthetic_episode(2)
    bad["captions"][0]["end"] = 3
    assert "caption_time_invalid" in timeline.validate_episode(bad)
    bad = timeline.synthetic_episode(2)
    bad["scenes"][-1]["end"] = 3
    assert "scene_time_invalid" in timeline.validate_episode(bad)


@pytest.mark.skipif(os.environ.get("RECAP_LINUX_TEST") == "1", reason="API contract runs in API suite")
def test_api_media_report_rejects_invented_pass_and_ending():
    # Mutation: trust passed=true without raw duration/hash/sync measurements.
    from app.services.recap_video.contracts import require_media_measurements
    from app.services.generation.store import Held
    with pytest.raises(Held):
        require_media_measurements({"passed": True}, {}, {})


@pytest.mark.skipif(os.environ.get("RECAP_LINUX_TEST") == "1", reason="API contract runs in API suite")
def test_api_accepts_measured_fixture_and_rejects_missing_frames_or_ending():
    # Mutation: accept empty representative-frame evidence or falsified endings.
    import json
    from types import SimpleNamespace
    from media.timeline import digest_file
    from app.services.recap_video.contracts import require_media_measurements
    from app.services.generation.store import Held
    root = Path(__file__).parent/"fixtures/recap_media"
    report = json.loads((root/"qa.json").read_text())
    episode = json.loads((root/"episode.json").read_text())
    assets = {name:SimpleNamespace(digest=digest_file(root/name),size=(root/name).stat().st_size)
        for name in ("video.mp4","audio.wav","render.json")}
    require_media_measurements(report,episode,assets)
    for field,value in (("representative_frames",[]),("audio_duration",.5),("peak_db",[float("nan")])):
        bad = copy.deepcopy(report);bad["measurements"][field]=value
        with pytest.raises(Held,match="media_measurements_invalid"):
            require_media_measurements(bad,episode,assets)
    for field in ('source_seams','encoded_seams','chunk_timing'):
        bad=copy.deepcopy(report);bad['measurements'][field]=[]
        with pytest.raises(Held,match='media_measurements_invalid'):
            require_media_measurements(bad,episode,assets)
    for corrupt in ('missing','nonfinite','partial'):
        bad=copy.deepcopy(report)
        if corrupt=='missing': bad['render']['geometry']=[]
        elif corrupt=='nonfinite': bad['render']['geometry'][0]['margins'][0]=float('nan')
        else: bad['render']['geometry'].pop(0)
        with pytest.raises(Held,match='media_measurements_invalid'):
            require_media_measurements(bad,episode,assets)


@pytest.mark.skipif(os.environ.get("RECAP_LINUX_TEST") == "1", reason="API speech tokenizer")
def test_multiple_results_follow_narration_anchors_and_ambiguity_holds():
    # Mutation: display claim-list order/equal time instead of narrated owner anchors.
    from media.timeline import scene_plan
    claims = {"owners":[{"id":x,"name":x.title()} for x in ("alpha","bravo","charlie","delta")],
        "claims":[{"id":"first","kind":"result","owner_ids":["alpha","bravo"]},
                  {"id":"second","kind":"result","owner_ids":["charlie","delta"]}]}
    script = {"segments":[{"id":"s","text":"Charlie defeated Delta. Alpha beat Bravo.", "claim_ids":["first","second"]}]}
    assert [c["claim"]["id"] for c in scene_plan(script,claims)["s"]] == ["second","first"]
    script["segments"][0]["claim_ids"] = ["second","first"]
    assert [c["claim"]["id"] for c in scene_plan(script,claims)["s"]] == ["second","first"]
    script["segments"][0]["text"] = "Alpha and Charlie beat Bravo and Delta."
    with pytest.raises(ValueError, match="scene_anchor_ambiguous"):
        scene_plan(script,claims)


@pytest.mark.skipif(os.environ.get("RECAP_LINUX_TEST") == "1", reason="API speech tokenizer")
def test_status_scene_requires_actual_status_anchor():
    # Mutation: owner mention alone invents a bye/season-finished graphic.
    from media.timeline import scene_plan
    claims = {"owners":[{"id":"alpha","name":"Alpha"}], "claims":[
        {"id":"status","kind":"owner_status","owner_ids":["alpha"],"status":"bye"}]}
    script = {"segments":[{"id":"s","text":"Alpha has a bye.","claim_ids":["status"]}]}
    assert scene_plan(script,claims)["s"][0]["claim"]["status"] == "bye"
    script["segments"][0]["text"]="Alpha finished the season."
    with pytest.raises(ValueError, match="status_anchor_missing"):
        scene_plan(script,claims)
    claims["owners"].append({"id":"bravo","name":"Bravo"})
    claims["claims"].append({"id":"other","kind":"owner_status","owner_ids":["bravo"],"status":"finished"})
    script["segments"][0].update(text="Alpha finished the season. Bravo has a bye.",claim_ids=["status","other"])
    with pytest.raises(ValueError,match="status_anchor_missing"):
        scene_plan(script,claims)


@pytest.mark.skipif(os.environ.get("RECAP_LINUX_TEST") == "1", reason="API database contract")
@pytest.mark.asyncio
async def test_api_rederives_bundle_and_rejects_changed_score(maker, tmp_path, monkeypatch):
    # Mutation: accept a worker's internally consistent but wrong score timeline.
    import hashlib
    import io
    import json
    import uuid
    import wave
    from app.services.generation.models import ContentArtifact
    from app.services.generation.recap_models import RecapStage, RecapAsset
    from app.services.generation.store import Held, dump
    from app.services.recap_video.rendering import validate_render
    from app.services.recap_video.storage import LocalPrivateMediaStore
    from media.timeline import build_episode, digest_file
    from tests.test_recap_audio import transcript
    from tests.test_recap_speech_reviews import reviewed_artifact
    episode_id, speech_id = await reviewed_artifact(maker,tmp_path,monkeypatch)
    monkeypatch.setenv("TRADE_GRADER_MEDIA_ASSET_ROOT",str(tmp_path/"objects"))
    store = LocalPrivateMediaStore(tmp_path/"objects")
    raw = transcript("Welcome. Avery and Blake tied. That is all.")
    audio = io.BytesIO()
    with wave.open(audio,"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b"\0\0"*32000)
    async with maker.begin() as db:
        artifact = await db.get(ContentArtifact,"script")
        payload = json.loads(artifact.payload_json)
        inputs = dict(script=payload["script"],claims=payload["claims"],script_digest=artifact.digest)
        speech = await db.get(RecapStage,speech_id)
        from sqlalchemy import select
        stage = await db.scalar(select(RecapStage).where(RecapStage.episode_id==episode_id,RecapStage.kind=="render"))
        stage.generation=1;stage.input_json=dump(inputs);stage.predecessor_id=speech_id
        async def save(data, mime, owner):
            key, ident = str(uuid.uuid4()), str(uuid.uuid4())
            sha = hashlib.sha256(data).hexdigest();store.put_verified(key,data,sha)
            db.add(RecapAsset(id=ident,stage_id=owner.id,generation=owner.generation,storage_key=key,digest=sha,size=len(data),media_type=mime))
            await db.flush();return ident
        speech = await db.get(RecapStage,speech_id)
        speech.state="succeeded"
        raw_id=await save(json.dumps(raw).encode(),"application/json",speech)
        source_id=await save(audio.getvalue(),"audio/mpeg",speech)
        speech.evidence_json=dump(dict(transcript_asset_id=raw_id,audio_asset_ids=[source_id],speech_review={"aliases":{}}))
        episode = build_episode(inputs,raw,[source_id],hashlib.sha256(audio.getvalue()).hexdigest(),2)
        package=Path(__file__).resolve().parents[2]/"media/render"
        async def result(value):
            episode_data=json.dumps(value).encode()
            graphic=b"synthetic-frame"
            render=dict(input_sha256=hashlib.sha256(episode_data).hexdigest(),layout_issues=[],
                scripts={name:digest_file(package/name) for name in ("render.cjs","scene.js","style.css","index.html")},
                representative_frames=[dict(file="frame-0000000.png",sha256=hashlib.sha256(graphic).hexdigest())])
            files={}
            for name,data,mime in (("episode.json",episode_data,"application/json"),("audio.wav",audio.getvalue(),"audio/wav"),
                    ("render.json",json.dumps(render).encode(),"application/json"),("video.mp4",b"synthetic-video","video/mp4"),("frame-0000000.png",graphic,"image/png")):
                files[name]=await save(data,mime,stage)
            manifest=await save(json.dumps(dict(version="recap-bundle-1",script_digest=artifact.digest,files=files)).encode(),"application/json",stage)
            return dict(asset_ids=[manifest,*files.values()],report=dict(manifest_asset_id=manifest))
        await validate_render(db,stage,await result(episode))
        changed=copy.deepcopy(episode);changed["scenes"][1]["winner_points"]="999"
        with pytest.raises(Held,match="render_bundle_invalid"):
            await validate_render(db,stage,await result(changed))


@pytest.mark.skipif(os.environ.get("RECAP_LINUX_TEST") != "1", reason="Linux image integration")
def test_real_media_guards(tmp_path):
    # Mutation: skip decode, ending, layout, font, or timestamp measurement.
    from scripts.check_recap_media_runtime import media_contract
    media_contract(tmp_path)


@pytest.mark.skipif(os.environ.get("RECAP_LINUX_TEST") != "1", reason="Linux image integration")
def test_supervisor_boundary_and_cancellation(tmp_path):
    # Mutation: env-only sandbox, parent /proc visibility, or orphan on cancel.
    from scripts.check_recap_media_runtime import isolation_contract
    isolation_contract(tmp_path)


@pytest.mark.skipif(os.environ.get("RECAP_LINUX_TEST") != "1", reason="Linux image integration")
def test_actual_render_and_media_check_lease_adapters(tmp_path):
    # Mutation: wrong predecessor order, ignored uploaded asset, or missing handler.
    from scripts.check_recap_media_runtime import adapter_contract
    adapter_contract(tmp_path)


def test_raw_geometry_and_seam_evidence_are_required():
    from media.geometry import geometry_issues
    from media.audio_seams import seam_issues
    assert geometry_issues([], {'captions':[{'text':'Hello'}],'scenes':[{}]}) == ['geometry_missing']
    assert seam_issues([], [{'frames':44100,'sample_rate':44100},{'frames':44100,'sample_rate':44100}]) == ['seam_evidence_missing']
    assert seam_issues({},[{'frames':44100}]) == ['seam_evidence_invalid']


@pytest.mark.skipif(os.environ.get('RECAP_LINUX_TEST') != '1', reason='Linux image integration')
def test_real_multichunk_seams_and_runtime_failures(tmp_path):
    from scripts.check_recap_media_runtime import seam_contract, failure_contract
    seam_contract(tmp_path)
    failure_contract(tmp_path)
