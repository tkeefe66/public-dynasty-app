import json
from pathlib import Path

import httpx
import pytest
from app.services.chain_cache import ChainCacheEntry
from app.services.historical_backfill import EvidenceClient
from app.services.historical_backfill_run import prepare
from app.services.historical_rating_assets import (
    HistoricalAssetStore,
    HistoricalRatingAssets,
)


@pytest.fixture
def season_source():
    """Synthetic ownership, real sanitized schedule shape, two complete teams."""
    players = {
        f"p{i}": {"birth_date": "2000-01-01", "position": "RB"} for i in range(50)
    }
    rosters = [
        {
            "roster_id": rid,
            "owner_id": uid,
            "players": [f"p{i}" for i in indices],
            "settings": {
                "wins": 17 * wins,
                "losses": 17 * (1 - wins),
                "ties": 0,
                "fpts": 17 * score,
                "fpts_against": 17 * opponent,
            },
        }
        for rid, uid, indices, wins, score, opponent in [
            (1, "a", range(25), 1, 120, 100),
            (2, "b", range(25, 50), 0, 100, 120),
        ]
    ]
    matchups = [
        {
            "roster_id": r["roster_id"],
            "players": r["players"],
            "matchup_id": 1,
            "points": r["settings"]["fpts"] / 17,
        }
        for r in rosters
    ]
    board = {
        "format": "non_sf_dynasty",
        "tep": "std",
        "asOf": "2025-01-06",
        "total": 49,
        "rankings": [
            {"id": f"p{i}", "position": "RB", "value": 100 + i} for i in range(49)
        ],
    }
    league = {
        "season": "2024",
        "status": "complete",
        "previous_league_id": None,
        "roster_positions": ["QB", "RB", "WR", "TE"],
        "settings": {
            "type": 2,
            "playoff_week_start": 18,
            "last_scored_leg": 18,
            "draft_rounds": 1,
            "playoff_teams": 2,
        },
    }
    schedule = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/historical_cutoff_scoreboard.json"
        ).read_text()
    )
    entry = ChainCacheEntry(
        league_id="league",
        chain=[
            {
                "league_id": "league",
                "season": 2024,
                "status": "complete",
                "format": "dynasty",
            }
        ],
        resolved_trades=[],
        grades={},
        owners={"a": {"name": "A"}, "b": {"name": "B"}},
        playoff_weeks_by_league={},
        roster_to_user_by_league={"league": {1: "a", 2: "b"}},
        league_name_by_id={"league": "Fixture"},
        league_season_by_id={"league": 2024},
        cached_at="2026-10-24T00:00:00+00:00",
    )
    mutations = {}

    def handler(request):
        path = request.url.path
        if "scoreboard" in path:
            data = schedule
        elif path.endswith("/rankings"):
            data = board
        elif path.endswith("/trades/evaluate"):
            body = json.loads(request.content)
            data = {
                "sideA": {
                    "assets": [
                        {"id": pid, "found": True, "asOf": board["asOf"], "value": 100}
                        for pid in body["sideA"]
                    ]
                }
            }
        elif path.endswith("/players/nfl"):
            data = players
        elif path.endswith("/rosters"):
            data = rosters
        elif "/matchups/" in path:
            data = matchups
        elif path.endswith("/winners_bracket"):
            data = [{"r": 1, "m": 1, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1}]
        elif (
            path.endswith(("/losers_bracket", "/traded_picks"))
            or "/transactions/" in path
        ):
            data = []
        else:
            data = league
        if mutations.get("incomplete_board") and path.endswith("/rankings"):
            data = {**board, "total": 50}
        return httpx.Response(200, json=data)

    return entry, handler, mutations


def test_full_prepare_offline_replay_import_and_scope(tmp_path, season_source):
    # Mutation: compute a separate preview formula, lose attribution, or skip import binding.
    from app.services.historical_backfill_run import rank_preview
    from app.services.season_ratings import rating_scope

    entry, handler, _ = season_source
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        report = prepare(
            entry,
            EvidenceClient(tmp_path / "receipts", http=http),
            2024,
            tmp_path / "output",
        )
    replay = prepare(
        entry,
        EvidenceClient(tmp_path / "receipts", offline=True),
        2024,
        tmp_path / "replay",
    )
    assert report == replay
    assert report["status"] == "validated" and len(report["scenarios"]) == 2
    assert set(report["rankings"]) == {"a", "b"}
    raw = json.loads((tmp_path / "output/manifest.json").read_text())
    store = HistoricalAssetStore(tmp_path / "cache", "league")
    store.import_verified(raw)
    assets, reason = store.load(
        season=2024,
        season_league_id="league",
        owners=["a", "b"],
        format="dynasty",
        identity_version="",
        through_week=18,
        cutoff_date="2025-01-07",
    )
    assert assets is not None and reason is None
    from app.services.historical_backfill_run import collect

    _, _, supporting = collect(
        EvidenceClient(tmp_path / "receipts", offline=True), entry, 2024
    )
    assert rank_preview(entry, supporting, raw) == report["rankings"]
    from app.services.season_ratings import build_season_rating_inputs

    entry.season_rating_inputs = build_season_rating_inputs(
        entry, supporting, asset_store=store
    )
    scope = rating_scope(entry, 2024)
    assert scope["valuation_source"] == "stats_guy"
    assert "49/50" in scope["valuation_note"]
    raw["players"][0]["value"] += 1
    with pytest.raises(ValueError, match="validated preview"):
        store.import_verified(raw)


def test_incomplete_provider_board_cannot_create_publishable_manifest(
    tmp_path, season_source
):
    # Mutation: treat a partial reply as the absent-player floor.
    entry, handler, mutations = season_source
    mutations["incomplete_board"] = True
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(ValueError, match="Incomplete"),
    ):
        prepare(entry, EvidenceClient(tmp_path / "receipts", http=http), 2024, tmp_path / "output")
    assert not (tmp_path / "output/manifest.json").exists()


def test_sensitivity_checks_simultaneous_missing_values(monkeypatch):
    # Mutation: test each absent player individually but miss the joint reversal.
    from app.services.historical_backfill_run import validate_sensitivity

    def rank(entry, supporting, raw):
        changed = sum(p["value"] for p in raw["players"]) > 1
        return {"a": {"rank": 2 if changed else 1, "grade": "B", "rating": 1500}}

    monkeypatch.setattr("app.services.historical_backfill_run.rank_preview", rank)
    _, scenarios, stable = validate_sensitivity(
        None,
        None,
        {"players": [{"player_id": "a", "value": 0}, {"player_id": "b", "value": 0}]},
        {"unranked_upper_bounds": {"a": 1, "b": 1}},
    )
    assert len(scenarios) == 4 and stable is False
    assert scenarios[-1]["changed_owners"] == ["a"]


def test_stats_guy_manifest_requires_validation_attestation(tmp_path, season_source):
    entry, handler, _ = season_source
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        prepare(
            entry,
            EvidenceClient(tmp_path / "receipts", http=http),
            2024,
            tmp_path / "output",
        )
    raw = json.loads((tmp_path / "output/manifest.json").read_text())
    del raw["validation"]
    with pytest.raises(ValueError, match="validated preview"):
        HistoricalRatingAssets.model_validate(raw)


def test_truncated_championship_blocks_publication(tmp_path, season_source):
    # Mutation: let the engine infer a champion from a truncated highest round.
    entry, handler, _ = season_source

    def truncated(request):
        response = handler(request)
        if request.url.path.endswith("/winners_bracket"):
            game = response.json()[0]
            del game["p"]
            return httpx.Response(200, json=[game])
        return response

    with (
        httpx.Client(transport=httpx.MockTransport(truncated)) as http,
        pytest.raises(ValueError, match="bracket"),
    ):
        prepare(entry, EvidenceClient(tmp_path / "receipts", http=http), 2024, tmp_path / "output")
    assert not (tmp_path / "output/manifest.json").exists()


def test_changed_results_cannot_reuse_validated_assets(tmp_path, season_source):
    # Mutation: refresh accepts a corrected bracket without revalidating ranking stability.
    from app.services.historical_backfill_run import collect
    from app.services.season_ratings import build_season_rating_inputs

    entry, handler, _ = season_source
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        prepare(
            entry,
            EvidenceClient(tmp_path / "receipts", http=http),
            2024,
            tmp_path / "output",
        )
    raw = json.loads((tmp_path / "output/manifest.json").read_text())
    store = HistoricalAssetStore(tmp_path / "cache", "league")
    store.import_verified(raw)
    _, _, supporting = collect(
        EvidenceClient(tmp_path / "receipts", offline=True), entry, 2024
    )
    supporting["winners_bracket_by_league"]["league"][0].update(w=2, l=1)
    snapshot = build_season_rating_inputs(entry, supporting, asset_store=store)["2024"]
    assert snapshot["status"] == "unavailable"
    assert "results changed" in snapshot["reason"]


def test_toilet_bowl_advances_low_score_but_title_bracket_does_not():
    # Mutation: reject valid toilet evidence or accept a reversed title result.
    from app.services.historical_backfill_run import validate_brackets

    matchups = {
        ("fixture", 17, rid): {"opponent_roster_id": opponent, "team_points": points}
        for rid, opponent, points in [(1, 2, 100), (2, 1, 90), (3, 4, 60), (4, 3, 80)]
    }
    winners = [{"m": 1, "r": 1, "p": 1, "w": 1, "l": 2}]
    losers = [{"m": 1, "r": 1, "p": 1, "w": 3, "l": 4}]
    kwargs = {
        "matchups": matchups,
        "league_id": "fixture",
        "playoff_start": 17,
        "final_week": 17,
    }
    validate_brackets(winners, losers, [1, 2, 3, 4], 2, toilet_bowl=True, **kwargs)
    with pytest.raises(ValueError, match="disagrees"):
        validate_brackets(winners, losers, [1, 2, 3, 4], 2, toilet_bowl=False, **kwargs)
    winners[0].update(w=2, l=1)
    with pytest.raises(ValueError, match="disagrees"):
        validate_brackets(winners, losers, [1, 2, 3, 4], 2, toilet_bowl=True, **kwargs)


@pytest.mark.parametrize("mutation", ["owner", "regular_points", "pick_date"])
def test_inconsistent_source_evidence_blocks_manifest(tmp_path, season_source, mutation):
    # Mutation: accept identity drift, inconsistent season totals, or undated picks.
    entry, handler, _ = season_source

    def altered(request):
        data = handler(request).json()
        if request.url.path.endswith("/rosters"):
            if mutation == "owner":
                data[0]["owner_id"] = "unknown-owner"
            elif mutation == "regular_points":
                data[0]["settings"]["fpts"] += 1
        elif request.url.path.endswith("/trades/evaluate") and mutation == "pick_date":
            data["sideA"]["assets"][0]["asOf"] = "2026-01-01"
        return httpx.Response(200, json=data)

    with (
        httpx.Client(transport=httpx.MockTransport(altered)) as http,
        pytest.raises(ValueError),
    ):
        prepare(entry, EvidenceClient(tmp_path / "receipts", http=http), 2024, tmp_path / "output")
    assert not (tmp_path / "output/manifest.json").exists()
