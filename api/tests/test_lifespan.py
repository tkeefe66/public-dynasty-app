from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.db.engine import dispose_engine as real_dispose_engine
from app.main import create_app


def test_lifespan_starts_and_shuts_down_cleanly_with_both_schedulers(
    monkeypatch, tmp_path
):
    """The shared ``client`` fixture in conftest.py does ``yield TestClient(app)``
    rather than ``with TestClient(app) as client:``, so Starlette never sends the
    ASGI lifespan startup/shutdown events for the other tests in this suite —
    ``init_engine``, ``auto_refresh_loop``, ``backup_loop``, and
    ``dispose_engine`` are never exercised there, and neither is the
    cancel-then-await shutdown path this task added for the two background
    tasks.

    This test forces BOTH ``auto_refresh`` and ``backup_configured`` on (via
    env vars, read fresh by every ``Settings()`` instantiation — including
    ``init_engine``'s own internal ``get_settings()`` call, so the identity DB
    stays isolated under ``tmp_path`` rather than touching the real cache
    dir), then substitutes recording stand-ins for ``auto_refresh_loop`` and
    ``backup_loop`` plus a spy on ``dispose_engine`` so the test can observe,
    not just infer, that both loops were scheduled and both were cancelled
    *by the app's own shutdown code* — not merely swept up afterward.

    A bare "was each name cancelled by the time the `with` block exits" check
    is NOT sufficient here: Starlette's ``TestClient`` runs the app on a
    dedicated event loop via an anyio blocking portal, and closing that
    portal cancels every still-pending task on the loop as a final sweep
    (the same blanket cleanup ``asyncio.run()`` does) — independent of
    whether the *app's own lifespan* ever awaited it. Verified empirically:
    reverting `main.py` to the classic overwrite bug (`task = None` reused
    for both `if` branches, so the second assignment orphans the first task)
    still gets BOTH stand-ins marked "entered" and "cancelled" by exit time,
    because the portal's teardown cancels the orphaned one anyway, after the
    ASGI shutdown has already completed.

    What the overwrite bug actually breaks is ORDER: only the referenced task
    is cancelled and awaited *inside* the lifespan's own `finally` block,
    before `dispose_engine()` runs; the orphaned task's cancellation happens
    later, at portal teardown, after `dispose_engine()` has already run. So
    the real assertion is that both `"...:cancelled"` events land strictly
    before `"dispose:start"` in one shared ordered event log — that only
    holds when the app's own shutdown code awaited every task itself.

    Patches ``app.main``'s module-level names (not the source modules in
    ``app.services.*`` / ``app.db.engine``) because `main.py`'s lifespan
    resolves them as bare names from its own module globals at call time.
    """
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("TRADE_GRADER_AUTO_REFRESH", "true")
    monkeypatch.setenv("TRADE_GRADER_BACKUP_ENABLED", "true")
    monkeypatch.setenv("TRADE_GRADER_BACKUP_HOUR_UTC", "9")
    monkeypatch.setenv("TRADE_GRADER_R2_ACCOUNT_ID", "a")
    monkeypatch.setenv("TRADE_GRADER_R2_BUCKET", "b")
    monkeypatch.setenv("TRADE_GRADER_R2_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("TRADE_GRADER_R2_SECRET_ACCESS_KEY", "s")

    events: list[str] = []

    async def fake_auto_refresh_loop(*args, **kwargs):
        events.append("auto_refresh:entered")
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("auto_refresh:cancelled")
            raise

    async def fake_backup_loop(*args, **kwargs):
        events.append("backup:entered")
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("backup:cancelled")
            raise

    async def spy_dispose_engine(*args, **kwargs):
        events.append("dispose:start")
        await real_dispose_engine(*args, **kwargs)
        events.append("dispose:done")

    monkeypatch.setattr("app.main.auto_refresh_loop", fake_auto_refresh_loop)
    monkeypatch.setattr("app.main.backup_loop", fake_backup_loop)
    monkeypatch.setattr("app.main.dispose_engine", spy_dispose_engine)

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200

    # Both loops were actually scheduled as distinct tasks.
    assert "auto_refresh:entered" in events
    assert "backup:entered" in events

    # Both tasks were cancelled AND awaited by the lifespan's OWN shutdown
    # code, strictly before dispose_engine runs — not merely orphaned and
    # swept up later by the test harness. This is what the overwrite bug
    # actually breaks: the orphaned task's cancellation lands after
    # "dispose:start" instead of before it.
    dispose_start = events.index("dispose:start")
    assert events.index("auto_refresh:cancelled") < dispose_start
    assert events.index("backup:cancelled") < dispose_start
