from types import SimpleNamespace

import pytest
from app.services.keeper_evidence import SeasonFormatStore

from ._grader_fixtures import _run_with_one_trade, _v2_entry


@pytest.mark.asyncio
async def test_reviewed_format_controls_pricing_and_capabilities_before_refresh(tmp_path):
    from app.services.grader import GraderService

    SeasonFormatStore(tmp_path).save("L", 2024, {
        "format": "keeper", "basis": "member confirmation",
        "evidence_sha256": "a" * 64, "future_picks_retained": False,
    })
    captured = {}
    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state={"season": "2026", "week": 7},
        league_format="redraft", captured=captured,
    )
    assert entry.capabilities["format"] == "keeper"
    assert entry.capabilities["roster_continuity"] is True
    assert entry.capabilities["future_picks"] is False
    assert captured["snapshot_store"].source == "dynasty"
    assert entry.chain[0]["format_evidence"]["future_picks_retained"] is False


def test_conflicting_provider_format_cannot_be_overridden(tmp_path):
    from app.services.keeper_evidence import resolve_season_formats

    store = SeasonFormatStore(tmp_path)
    store.save("L", 2026, {"format": "keeper", "basis": "member",
                           "evidence_sha256": "a" * 64})
    league = SimpleNamespace(league_id="L", season=2026, format="redraft", format_verified=True)
    resolved = resolve_season_formats([league], store)[0]
    assert resolved.effective_format_verified is False
    assert "conflict" in resolved.format_error.lower()


def test_current_and_all_do_not_use_unverified_or_stale_format():
    from app.services.franchise_redesign import live_ratings
    from app.services.season_ratings import rating_scope

    entry = _v2_entry(capabilities={"format": "redraft"})
    entry.chain = [{"league_id": "L", "season": 2026, "format": "redraft", "format_verified": False}]
    entry.current_rating_verification = {}
    assert live_ratings(entry) == {}
    entry.current_rating_verification = {"status": "ready", "format": "keeper"}
    assert live_ratings(entry) == {}
    entry.current_rating_verification = {"status": "unavailable", "format": "keeper",
                                         "reason": "Current roster prices are incomplete."}
    assert rating_scope(entry, "all")["reason"] == "Current roster prices are incomplete."


def test_missing_prices_and_unknown_yahoo_picks_never_become_zero_assets():
    from app.services.current_rating_verification import verify_current_assets

    league = SimpleNamespace(league_id="test.l.1", season=2026, format="keeper",
                             effective_format_verified=True, format_evidence={}, total_rosters=1)
    rosters = [SimpleNamespace(owner_id="u", players=["p"])]
    support = {"positions": {"p": "RB"}, "ktc_by_player_id": {}}
    result = verify_current_assets(league, rosters, support, picks_verified=True)
    assert result["status"] == "unavailable"
    support["ktc_by_player_id"]["p"] = SimpleNamespace(superflex_value=100)
    assert verify_current_assets(league, rosters, support, picks_verified=True)["status"] == "unavailable"
    league.format_evidence = {"future_picks_retained": False}
    assert verify_current_assets(league, rosters, support, picks_verified=True)["status"] == "ready"
    league.total_rosters = 2
    assert verify_current_assets(league, rosters, support, picks_verified=True)["status"] == "unavailable"


def test_owner_page_hides_unverified_asset_ranks_and_prose():
    from app.services.owner_view import build_owner_detail

    entry = _v2_entry(capabilities={"format": "keeper"})
    entry.current_rating_verification = {"status": "unavailable", "reason": "Missing prices"}
    entry.dynasty_outlooks = {"u1": {"unverified": True}}
    entry.franchise_blurbs = {"u1": {"blurb": "Stale assets prose"}}
    detail = build_owner_detail(entry, "u1")
    assert detail.roster_rank is None
    assert detail.outlook is None
    assert detail.franchise_blurb is None
    assert detail.unrated_reason == "unverified_data"


def test_discovery_uses_reviewed_format_and_does_not_guess_redraft(tmp_path):
    from app.services.yahoo_discovery import discovery_format

    store = SeasonFormatStore(tmp_path)
    assert discovery_format("L", 2026, {}, store) == "unverified"
    store.save("L", 2026, {"format": "keeper", "basis": "member", "evidence_sha256": "a" * 64})
    assert discovery_format("L", 2026, {}, store) == "keeper"
    assert discovery_format("L", 2026, {"is_keeper_league": 0}, store) == "unverified"


def test_sleeper_pick_prices_and_round_count_are_required():
    from app.services.current_rating_verification import verify_current_assets

    league = SimpleNamespace(league_id="L", season=2026, format="keeper",
                             effective_format_verified=True, total_rosters=1)
    rosters = [SimpleNamespace(owner_id="u", players=["p"])]
    support = {"positions": {"p": "RB"}, "ktc_by_player_id": {"p": SimpleNamespace(superflex_value=100)}}
    assert verify_current_assets(league, rosters, support, picks_verified=True)["status"] == "unavailable"


def test_asset_verification_does_not_hide_missing_current_results():
    from app.services.franchise_redesign import live_ratings

    entry = _v2_entry(capabilities={"format": "keeper"})
    entry.current_rating_verification = {"status": "ready", "format": "keeper"}
    entry.outcome_signals = {}
    assert live_ratings(entry) == {}


def test_legacy_current_cache_requires_verification_even_with_provider_format():
    from app.services.franchise_redesign import live_ratings

    entry = _v2_entry(capabilities={"format": "redraft"})
    entry.current_rating_verification = {}
    entry.chain = [{"league_id": "L", "season": 2026, "format": "redraft", "format_verified": True}]
    assert live_ratings(entry) == {}


def test_career_rating_cannot_reinclude_explicitly_excluded_results():
    from app.services.season_ratings import rating_scope

    entry = _v2_entry(capabilities={"format": "redraft"})
    entry.current_rating_verification = {"status": "ready", "format": "redraft"}
    entry.season_rating_inputs = {
        "2025": {"results_coverage": {"excluded_seasons": [
            {"season": 2023, "reason": "Unverified postseason participation"}]}},
        "2026": {"basis": "current", "version": 1, "status": "ready"},
    }
    assert rating_scope(entry, "all")["status"] == "unavailable"
    assert "2023" in rating_scope(entry, "all")["reason"]
    assert rating_scope(entry, 2026)["status"] == "unavailable"
    # Rejected evidence leaves only a durable requirement on refresh.
    entry.season_rating_inputs = {"2023": {"status": "unavailable", "requires_results_coverage": True}}
    assert rating_scope(entry, "all")["status"] == "unavailable"
    assert "2023" in rating_scope(entry, "all")["reason"]


@pytest.mark.asyncio
async def test_failed_historical_rebuild_blocks_current_rating(tmp_path, monkeypatch):
    from app.services.grader import GraderService
    from app.services.season_ratings import rating_scope

    def fail(*args, **kwargs):
        raise OSError("Coverage store unreadable")

    monkeypatch.setattr("app.services.season_ratings.build_season_rating_inputs", fail)
    entry = await _run_with_one_trade(GraderService(), cache_dir=tmp_path,
                                      nfl_state={"season": "2026", "week": 7})
    assert entry.current_rating_verification["status"] == "unavailable"
    assert "Historical Results verification failed" in rating_scope(entry, "all")["reason"]
