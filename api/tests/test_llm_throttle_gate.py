"""The LLM-pass gate: one decision for "reuse all cached prose this pass".

Two independent reasons to reuse: the time throttle (within
llm_min_interval_seconds of the last pass) and the offseason gate (incremental
reuse engaged: offseason + no new trades, so facts cannot have materially
moved). force=True defeats both. Brand-new trades still generate either way —
the generators only reuse entries that already have cached prose.
"""

from datetime import datetime, timedelta, timezone

from app.services.grader import llm_pass_throttled

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def test_offseason_gate_forces_reuse_even_with_stale_prev_pass():
    assert llm_pass_throttled(
        now=NOW,
        prev_llm_at=_iso(NOW - timedelta(days=30)),
        interval_seconds=20 * 3600,
        incremental_reuse=True,
        force=False,
    )


def test_offseason_gate_applies_without_any_prior_llm_timestamp():
    assert llm_pass_throttled(
        now=NOW, prev_llm_at=None, interval_seconds=20 * 3600,
        incremental_reuse=True, force=False,
    )


def test_force_defeats_offseason_gate_and_time_throttle():
    assert not llm_pass_throttled(
        now=NOW, prev_llm_at=_iso(NOW - timedelta(hours=1)),
        interval_seconds=20 * 3600, incremental_reuse=True, force=True,
    )


def test_time_throttle_within_interval():
    assert llm_pass_throttled(
        now=NOW, prev_llm_at=_iso(NOW - timedelta(hours=1)),
        interval_seconds=20 * 3600, incremental_reuse=False, force=False,
    )


def test_time_throttle_expired_interval_regenerates():
    assert not llm_pass_throttled(
        now=NOW, prev_llm_at=_iso(NOW - timedelta(hours=21)),
        interval_seconds=20 * 3600, incremental_reuse=False, force=False,
    )


def test_no_prior_pass_regenerates():
    assert not llm_pass_throttled(
        now=NOW, prev_llm_at=None, interval_seconds=20 * 3600,
        incremental_reuse=False, force=False,
    )


def test_interval_zero_disables_time_throttle_only():
    assert not llm_pass_throttled(
        now=NOW, prev_llm_at=_iso(NOW - timedelta(hours=1)),
        interval_seconds=0, incremental_reuse=False, force=False,
    )
    # ...but the offseason gate is independent of the interval setting.
    assert llm_pass_throttled(
        now=NOW, prev_llm_at=None, interval_seconds=0,
        incremental_reuse=True, force=False,
    )


def test_unparseable_prev_timestamp_regenerates():
    assert not llm_pass_throttled(
        now=NOW, prev_llm_at="not-a-date", interval_seconds=20 * 3600,
        incremental_reuse=False, force=False,
    )


def test_clock_skew_future_prev_pass_regenerates():
    # prev pass "in the future" (negative elapsed) must not throttle forever.
    assert not llm_pass_throttled(
        now=NOW, prev_llm_at=_iso(NOW + timedelta(hours=5)),
        interval_seconds=20 * 3600, incremental_reuse=False, force=False,
    )
