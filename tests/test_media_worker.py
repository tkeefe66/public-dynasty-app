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
async def test_speech_handler_preserves_raw_evidence_and_holds_ambiguity(monkeypatch):
    import json
    import httpx
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "api"))
    from media import worker as runtime
    uploaded = []
    raw = {"text": "Avery lost.", "words": [{"word": "Avery", "start": 0, "end": .3, "probability": .99},
        {"word": "lost.", "start": .3, "end": .6, "probability": .99}]}
    async def process(argv, directory, timeout):
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
                "script": {"segments": [{"id": "s", "text": "Avery won."}]}}})
    assert uploaded == [raw]
    assert result["status"] == "input_failure"
    assert "result_verb_mismatch" in result["report"]["issues"]
    assert result["asset_ids"] == ["raw-evidence"]
