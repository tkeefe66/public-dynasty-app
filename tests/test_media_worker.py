"""Worker sandbox contracts without provider credentials or subprocesses."""
import asyncio
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("restricted_worker", Path(__file__).parents[1] / "media" / "worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


@pytest.mark.asyncio
async def test_unqualified_and_api_handlers_are_rejected(monkeypatch):
    # Mutation: handlers can register arbitrary source/publication kinds.
    async def unexpected(lease):
        raise AssertionError("API handler executed")
    monkeypatch.setattr(worker, "HANDLERS", {"publish": unexpected})
    for kind in ("publish", "analyst_refresh", "render", "narrate"):
        with pytest.raises(RuntimeError, match="not qualified"):
            await worker.run_stage({"capability": kind})


@pytest.mark.asyncio
async def test_heartbeat_loss_cancels_handler_without_completion(monkeypatch):
    # Mutation: ignore failed heartbeats and submit result after losing ownership.
    cancelled = asyncio.Event()
    async def render(lease):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    async def immediate(seconds):
        return
    class Client:
        paths = []
        async def post(self, path, **kwargs):
            self.paths.append(path)
            raise RuntimeError("Synthetic heartbeat unavailable")
    monkeypatch.setattr(worker, "HANDLERS", {"render": render})
    monkeypatch.setattr(worker.asyncio, "sleep", immediate)
    client = Client()
    with pytest.raises(RuntimeError, match="heartbeat"):
        await worker.run_claim(client, dict(capability="render", stage_id="stage", generation=1, epoch="epoch", input_digest="digest"))
    assert cancelled.is_set()
    assert client.paths == ["/api/internal/media/heartbeat"]


def test_renderer_env_excludes_provider_and_database_credentials(monkeypatch, tmp_path):
    # Mutation: copy parent environment into rendering subprocess.
    monkeypatch.setenv("ELEVENLABS_API_KEY", "synthetic-secret")
    monkeypatch.setenv("DATABASE_URL", "synthetic-db")
    assert worker.renderer_environment(tmp_path) == {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path), "LANG": "C.UTF-8"}


def test_render_install_targets_entrypoint_registry():
    # Mutation: import media.worker creates a second registry under python -m.
    from media.adapters import install
    registry = {}
    install(object(), registry)
    assert set(registry) == {"render", "media_check"}


@pytest.mark.asyncio
async def test_narration_handler_commits_identity_audio_receipt_once(monkeypatch):
    import base64
    import json
    from pathlib import Path
    import httpx
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "api"))
    from app.services.recap_video import elevenlabs as el
    from media import worker
    events = []
    request = {"model_id": "eleven_v4", "inputs": [{"voice_id": "synthetic-voice", "text": "Hi."}], "settings": {}}
    rate = {"unit": "character", "microusd_per_character": 7, "max_credits_per_character": "1", "source": "synthetic", "revision": "1"}
    def api(req):
        action = req.url.path.rsplit("/", 1)[-1]
        events.append(action)
        value = {"authorize-dispatch": {"attempt_id": "attempt", "dispatch_authority": "single-use", "request": request},
            "identity": {}, "assets": {"asset_id": "asset", "digest": __import__("hashlib").sha256(b"audio").hexdigest(), "size": 5},
            "receipt": {"state": "received"}}[action]
        return httpx.Response(200, json=value)
    def provider(req):
        events.append("provider")
        return httpx.Response(200, json={"audio_base64": base64.b64encode(b"audio").decode(),
            "alignment": {"characters": list("Hi."), "character_start_times_seconds": [0, .1, .2], "character_end_times_seconds": [.1, .2, .3]},
            "voice_segments": [{"voice_id": "synthetic-voice", "dialogue_input_index": 0}]},
            headers={"request-id": "synthetic-request", "character-cost": "3"})
    original = el.ElevenLabsTransport
    monkeypatch.setattr(el, "ElevenLabsTransport", lambda key, identity, audio: original(key, identity, audio, transport=httpx.MockTransport(provider)))
    monkeypatch.setattr(worker, "HANDLERS", {})
    async with httpx.AsyncClient(base_url="http://api", transport=httpx.MockTransport(api)) as client:
        worker.install_narration_handlers(client, api_key="synthetic-key", model_directory="/unused")
        result = await worker.run_stage({"stage_id": "stage", "generation": 1, "epoch": "epoch", "input_digest": "digest",
            "capability": "narrate", "input": {"paid": {"request": request, "rate_snapshot": rate, "max_microusd": 21}}})
    assert events == ["authorize-dispatch", "provider", "identity", "assets", "receipt"]
    assert result["status"] == "ok" and result["asset_ids"] == ["asset"]


@pytest.mark.asyncio
@pytest.mark.parametrize("spoken,status", [("Averie won.", "ok"), ("Averie lost.", "input_failure")])
async def test_speech_handler_preserves_raw_evidence_and_holds_ambiguity(monkeypatch, spoken, status):
    import json
    import httpx
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "api"))
    from media import worker as runtime
    uploaded = []
    raw = {"text": spoken, "words": [{"word": "Averie", "start": 0, "end": .3, "probability": .99},
        {"word": spoken.split()[1], "start": .3, "end": .6, "probability": .99}]}
    processes=[]
    async def process(argv, directory, timeout):
        processes.append(argv)
        if argv[-1].endswith("raw.json"):
            Path(argv[-1]).write_text(json.dumps(raw))
    def api(req):
        if req.method == "GET":
            return httpx.Response(200, content=b"saved-audio")
        uploaded.append(json.loads(req.content))
        return httpx.Response(200, json={"asset_id": "raw-evidence"})
    monkeypatch.setattr(runtime, "_bounded_process", process)
    monkeypatch.setattr(runtime, "HANDLERS", {})
    async with httpx.AsyncClient(base_url="http://api", transport=httpx.MockTransport(api)) as client:
        runtime.install_narration_handlers(client, api_key="", model_directory="/synthetic-model")
        result = await runtime.run_stage({"stage_id": "stage", "generation": 1, "epoch": "epoch", "input_digest": "digest",
            "capability": "speech_check", "allowed_assets": ["audio"], "input": {"chunks": [{}],
                "speech_review": {"aliases": {"avery": ["averie"]}},
                "script": {"segments": [{"id": "s", "text": "Avery won."}]}}})
    assert processes[0][1:3]==['-m','media.audio_seams']
    assert any(str(arg).endswith('/audio.wav') for arg in processes[1])
    assert uploaded == [raw]
    assert result["status"] == status
    if status == "input_failure":
        assert "result_verb_mismatch" in result["report"]["issues"]
    assert result["asset_ids"] == ["raw-evidence"]

@pytest.mark.asyncio
async def test_render_alignment_ambiguity_holds_without_repeating_paid_work(monkeypatch, tmp_path):
    # Mutation: ambiguous timing throws out of the handler instead of durable hold.
    import tempfile
    import wave
    from media import adapters
    original = tempfile.TemporaryDirectory
    monkeypatch.setattr(adapters.tempfile, 'TemporaryDirectory', lambda **kw: original(dir=tmp_path))
    async def download(client,lease,identity,target):
        target.write_text('{}')
    async def run(argv,root,timeout):
        (root/'chunks.json').write_text('[]')
        with wave.open(str(root/'audio.wav'),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*16000)
    def ambiguous(*args,**kwargs):
        raise ValueError('scene_timing_ambiguous:synthetic')
    monkeypatch.setattr(adapters,'download',download)
    monkeypatch.setattr(adapters,'run',run)
    monkeypatch.setattr(adapters,'build_episode',ambiguous)
    registry={};adapters.install(object(),registry)
    result=await registry['render']({'allowed_assets':['raw','narration'],'input':{'chunks':[{}],'speech_review':{'aliases':{}}}})
    assert result=={'status':'input_failure','asset_ids':[],'report':{'issues':['scene_timing_ambiguous']}}

@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['timeout','exit_nonzero'])
async def test_process_failure_is_uploaded_and_completed_under_current_lease(monkeypatch, reason):
    import json
    from media.runtime import MediaProcessFailure
    async def fail(lease):
        raise MediaProcessFailure('ffmpeg', reason, 7 if reason=='exit_nonzero' else None, 1)
    monkeypatch.setattr(worker,'HANDLERS',{'render':fail})
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'asset_id':'diagnostic'}
    class Client:
        calls=[]
        async def post(self,path,**kwargs):
            self.calls.append((path,kwargs));return Response()
    client=Client()
    await worker.run_claim(client,dict(capability='render',stage_id='stage',generation=1,epoch='epoch',input_digest='digest'))
    assert [c[0] for c in client.calls]==['/api/internal/media/assets','/api/internal/media/complete']
    raw=json.loads(client.calls[0][1]['content'])
    assert raw['reason']==reason and raw['process']=='ffmpeg' and raw['stage_kind']=='render'
    assert client.calls[1][1]['json']['result']['asset_ids']==['diagnostic']
    assert client.calls[1][1]['json']['result']['status']=='input_failure'


@pytest.mark.asyncio
async def test_explicit_recovery_poll_never_claims_paid_work_and_reports_unavailable_history():
    # Mutation: recovery polling falls through to a new paid claim or retries missing history.
    import httpx,json
    paths=[]
    def api(request):
        paths.append(request.url.path)
        if request.url.path.endswith('recovery-claim'):
            return httpx.Response(200,json={'recovery_id':'lookup','attempt_id':'original','generation':1})
        assert json.loads(request.content)=={'recovery_id':'lookup','generation':1,'error':'history_unavailable','status':404}
        return httpx.Response(200,json={'state':'held'})
    async def recover(attempt):
        assert attempt=='original'
        response=httpx.Response(404,request=httpx.Request('GET','http://synthetic/history/original'))
        response.raise_for_status()
    async with httpx.AsyncClient(base_url='http://api',transport=httpx.MockTransport(api)) as client:
        assert await worker.tick(client,recovery=recover)
    assert paths==['/api/internal/media/recovery-claim','/api/internal/media/recovery-complete']
