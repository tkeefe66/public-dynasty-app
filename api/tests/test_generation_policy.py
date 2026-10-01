"""Mutation targets: strict booleans, hard pause intersection, stale revision CAS."""
import pytest
from app.services.generation.policy import Policy, effective, paid_capabilities
from pydantic import ValidationError


def test_defaults_require_explicit_activation():
    assert Policy().paused is True
    assert Policy().max_concurrency == 1
    assert Policy().features["analyst"].max_calls == 4


@pytest.mark.parametrize("value", ["false", "true", 0, 1])
def test_truthy_string_is_not_a_boolean(value):
    with pytest.raises(ValidationError):
        Policy.model_validate({"paused": value})


def test_series_cannot_override_app_pause():
    result = effective([("app", {"paused": True}), ("series", {"paused": False})])
    assert result["policy"]["paused"] is True
    assert "app_paused" in result["blocked_by"]


def test_series_can_override_ordinary_feature_setting():
    result = effective([
        ("app", {"paused": False}),
        ("profile:dynasty", {"features": {"trade_story": {"mode": "manual"}}}),
        ("series", {"features": {"trade_story": {"mode": "automatic"}}}),
    ])
    assert result["policy"]["features"]["trade_story"]["mode"] == "automatic"
    assert result["sources"]["features.trade_story.mode"] == "series"


@pytest.mark.parametrize("raw", [None, {}, {"format": "redraft"}, {
    "format": "dynasty", "future_picks": "false", "roster_continuity": True,
    "multiyear_history": True,
}])
def test_missing_or_malformed_capabilities_are_not_paid_permission(raw):
    assert paid_capabilities(raw) is None


def test_redraft_evidence_remains_redraft():
    caps = paid_capabilities({"format": "redraft", "future_picks": False,
                              "roster_continuity": False, "multiyear_history": True})
    assert caps["format"] == "redraft"
    assert caps["future_picks"] is False


def test_unknown_features_and_unbounded_limits_rejected():
    for raw in ({"features": {"invented": {}}}, {"max_concurrency": 0},
                {"features": {"analyst": {"max_calls": 400}}}):
        with pytest.raises(ValidationError):
            Policy.model_validate(raw)


@pytest.mark.asyncio
async def test_stale_settings_write_cannot_resume_app(maker):
    from app.services.generation.store import Conflict, resolve_policy, save_policy
    async with maker.begin() as db:
        await save_policy(db, "app", {"paused": True}, 0, "owner", "pause")
    async with maker.begin() as db:
        with pytest.raises(Conflict):
            await save_policy(db, "app", {"paused": False}, 0, "owner", "stale form")
    async with maker() as db:
        assert (await resolve_policy(db))["policy"]["paused"] is True


@pytest.mark.asyncio
async def test_verified_season_renewal_inherits_series_hold(maker):
    from types import SimpleNamespace

    from app.services.generation.models import LeagueSeries
    from app.services.generation.registry import register_entry
    caps = {"format": "dynasty", "future_picks": True,
            "roster_continuity": True, "multiyear_history": True}
    def entry(lid, chain):
        return SimpleNamespace(league_id=lid, chain=chain, capabilities=caps,
            league_name_by_id={lid: "Same name"}, league_season_by_id={}, week_recap={})
    async with maker.begin() as db:
        first = await register_entry(db, entry("old", [
            {"league_id": "old", "season": 2025, "format_verified": True}]), verified=True)
        series = await db.get(LeagueSeries, first.series_id)
        series.hold = "owner_paused"
    async with maker.begin() as db:
        new = await register_entry(db, entry("new", [
            {"league_id": "new", "season": 2026, "format_verified": True},
            {"league_id": "old", "season": 2025, "format_verified": True}]), verified=True)
        other = await register_entry(db, entry("unrelated", [
            {"league_id": "unrelated", "season": 2026, "format_verified": True}]), verified=True)
        assert new.series_id == first.series_id
        assert other.series_id != new.series_id
        assert (await db.get(LeagueSeries, new.series_id)).hold == "owner_paused"


@pytest.mark.asyncio
async def test_captured_missing_format_payload_cannot_activate(maker):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from app.services.generation.registry import register_entry, set_series
    raw = json.loads((Path(__file__).parents[2] / "tests/fixtures/league_meta.json").read_text())
    entry = SimpleNamespace(league_id=raw["league_id"], chain=[raw], capabilities={},
        league_name_by_id={raw["league_id"]: raw["name"]}, league_season_by_id={}, week_recap={})
    async with maker.begin() as db:
        season = await register_entry(db, entry, verified=True)
        with pytest.raises(ValueError, match="verify"):
            await set_series(db, season.series_id, expected_revision=1, lifecycle="active",
                profile="dynasty", actor="owner", reason="activate", activate=True)
def test_lower_scope_cannot_raise_app_concurrency_and_reports_true_pause_origin():
    from app.services.generation.policy import effective
    result = effective([("app", {"paused": True, "max_concurrency": 1}),
        ("profile:dynasty", {"paused": False, "max_concurrency": 4})])
    assert result["policy"]["max_concurrency"] == 1
    assert result["sources"]["paused"] == "app"
    assert result["sources"]["max_concurrency"] == "app"
def test_profile_cannot_raise_default_app_concurrency():
    from app.services.generation.policy import effective
    resolved = effective([("app", {"paused": False}), ("profile:dynasty", {"max_concurrency": 4})])
    assert resolved["policy"]["max_concurrency"] == 1
    assert effective([("app", {"paused": False, "max_concurrency": 4})])["policy"]["max_concurrency"] == 4
