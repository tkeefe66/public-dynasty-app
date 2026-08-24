from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.services.backup_service import _seconds_until, backup_loop


def _settings(hour=9):
    return Settings(
        backup_enabled=True, backup_hour_utc=hour, r2_account_id="a",
        r2_bucket="b", r2_access_key_id="k", r2_secret_access_key="s",
    )


def test_seconds_until_targets_today_when_the_hour_is_ahead():
    now = datetime(2026, 8, 12, 7, 0, tzinfo=timezone.utc)
    assert _seconds_until(9, now) == 2 * 3600


def test_seconds_until_rolls_to_tomorrow_once_the_hour_has_passed():
    now = datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc)
    assert _seconds_until(9, now) == 23.5 * 3600


def test_seconds_until_rolls_a_full_day_when_now_is_exactly_the_hour():
    now = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
    assert _seconds_until(9, now) == 24 * 3600


async def _noop_sleep(_seconds):
    return None


class RecordedStatus:
    """Stand-in for record_status, injected through the loop's ``_record`` seam.

    Without that seam the loop reaches the real record_status, which opens the
    module-level session_scope and writes backup.* rows into whatever database
    TRADE_GRADER_DATABASE_URL points at — poisoning the developer's /admin page
    with a backup error that never happened.
    """

    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, **kw):
        self.calls.append(kw)


@pytest.mark.asyncio
async def test_runs_when_past_the_hour_and_not_yet_run_today(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    runs = []
    status = RecordedStatus()

    async def fake_run(**kw):
        runs.append(kw)
        return {"run_id": "R1"}

    await backup_loop(
        cache, settings=_settings(), _run=fake_run,
        _sleep=_noop_sleep, _record=status,
        _now=lambda: datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
        _max_cycles=1,
    )
    assert len(runs) == 1
    assert (cache / "backup_last_run").read_text() == "2026-08-12"
    assert status.calls == [{"ok_at": "2026-08-12T10:00:00+00:00", "run_id": "R1"}]


@pytest.mark.asyncio
async def test_does_not_run_twice_on_the_same_day(tmp_path):
    """A redeploy must not re-trigger a backup that already succeeded today."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "backup_last_run").write_text("2026-08-12")
    runs = []
    status = RecordedStatus()

    async def fake_run(**kw):
        runs.append(kw)
        return {"run_id": "R1"}

    await backup_loop(
        cache, settings=_settings(), _run=fake_run, _sleep=_noop_sleep,
        _record=status,
        _now=lambda: datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
        _max_cycles=1,
    )
    assert runs == []
    assert status.calls == []


@pytest.mark.asyncio
async def test_does_not_run_before_the_scheduled_hour(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    runs = []
    status = RecordedStatus()

    async def fake_run(**kw):
        runs.append(kw)
        return {"run_id": "R1"}

    await backup_loop(
        cache, settings=_settings(), _run=fake_run, _sleep=_noop_sleep,
        _record=status,
        _now=lambda: datetime(2026, 8, 12, 7, 0, tzinfo=timezone.utc),
        _max_cycles=1,
    )
    assert runs == []
    assert status.calls == []


@pytest.mark.asyncio
async def test_a_failed_run_does_not_mark_the_day_or_raise(tmp_path):
    """The API must not fall over because R2 was unreachable, and tomorrow's
    catch-up must still see today as unbacked. The failure must also be
    recorded, or a silently-broken backup never reaches /admin."""
    cache = tmp_path / "cache"
    cache.mkdir()
    status = RecordedStatus()

    async def boom(**kw):
        raise RuntimeError("r2 unreachable")

    await backup_loop(
        cache, settings=_settings(), _run=boom, _sleep=_noop_sleep,
        _record=status,
        _now=lambda: datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
        _max_cycles=1,
    )
    assert not (cache / "backup_last_run").exists()
    assert status.calls == [{"error": "RuntimeError: r2 unreachable"}]


@pytest.mark.asyncio
async def test_a_marker_write_failure_still_records_the_run_as_successful(
    tmp_path, monkeypatch
):
    """The upload succeeded; a full or read-only volume must not turn that into
    a reported failure."""
    cache = tmp_path / "cache"
    cache.mkdir()

    def full_disk(*_a, **_kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(
        "app.services.backup_service._write_marker", full_disk
    )
    status = RecordedStatus()

    async def fake_run(**kw):
        return {"run_id": "R1"}

    await backup_loop(
        cache, settings=_settings(), _run=fake_run, _sleep=_noop_sleep,
        _record=status,
        _now=lambda: datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
        _max_cycles=1,
    )
    assert status.calls == [{"ok_at": "2026-08-12T10:00:00+00:00", "run_id": "R1"}]


@pytest.mark.asyncio
async def test_inert_when_not_configured(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    runs = []
    status = RecordedStatus()

    async def fake_run(**kw):
        runs.append(kw)

    await backup_loop(
        cache, settings=Settings(backup_enabled=False), _run=fake_run,
        _sleep=_noop_sleep, _record=status,
        _now=lambda: datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
        _max_cycles=1,
    )
    assert runs == []
    assert status.calls == []
