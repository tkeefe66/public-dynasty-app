import asyncio
import logging

import pytest


@pytest.mark.asyncio
async def test_drain_waits_for_inflight_tick_and_never_claims_again(tmp_path, monkeypatch):
    from media import worker
    claimed = asyncio.Event()
    finish = asyncio.Event()
    calls = []

    async def tick(*args, **kwargs):
        calls.append('claim')
        claimed.set()
        await finish.wait()
        return True

    monkeypatch.setattr(worker, 'tick', tick)
    task = asyncio.create_task(worker.serve(None, None, root=tmp_path, log=logging.getLogger('test')))
    try:
        await asyncio.wait_for(claimed.wait(), 1)
        (tmp_path / 'drain').touch()
        await asyncio.sleep(0)
        assert not (tmp_path / 'drained').exists()
        finish.set()
        await asyncio.sleep(0)
        assert (tmp_path / 'drained').exists()
        await asyncio.sleep(0)
        assert calls == ['claim'] and not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
