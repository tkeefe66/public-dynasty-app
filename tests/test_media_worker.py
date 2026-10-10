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
