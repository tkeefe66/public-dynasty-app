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


def seven_team_evidence():
    fixture = Path(__file__).resolve().parents[3] / "tests/fixtures/seven_team_bracket.json"
    winners = json.loads(fixture.read_text())
    losers = json.loads(fixture.read_text())
    for game in losers:
        for key in ("w", "l", "t1", "t2"):
            game[key] += 7
    matchups = {}
    for game in winners + losers:
        for rid, opponent, score in [(game["w"], game["l"], 100), (game["l"], game["w"], 90)]:
            matchups["fixture", 14 + game["r"], rid] = {
                "opponent_roster_id": opponent, "team_points": score,
            }
    return winners, losers, {
        "matchups": matchups, "league_id": "fixture", "playoff_start": 15, "final_week": 17,
    }


def test_complete_seven_team_brackets_accept_elimination_proven_seventh():
    # Mutation: p=None title count and explicit-only placement count reject valid 7-team evidence.
    from app.services.historical_backfill_run import validate_brackets
    winners, losers, kwargs = seven_team_evidence()
    validate_brackets(winners, losers, list(range(1, 15)), 7, **kwargs)


def test_seven_team_bracket_does_not_invent_absent_participant():
    # Mutation: inferring missing roster placement from league population would allow missing evidence.
    from app.services.historical_backfill_run import validate_brackets
    winners, losers, kwargs = seven_team_evidence()
    with pytest.raises(ValueError, match="postseason bracket"):
        validate_brackets(winners, losers, list(range(1, 16)), 7, **kwargs)


def test_seven_team_bracket_requires_consolation_elimination_evidence():
    # Mutation: assign seventh to the leftover roster even without the decisive elimination game.
    from app.services.historical_backfill_run import validate_brackets
    winners, losers, kwargs = seven_team_evidence()
    winners.pop(5)
    winners[-1].pop("t2_from")
    with pytest.raises(ValueError, match="postseason bracket"):
        validate_brackets(winners, losers, list(range(1, 15)), 7, **kwargs)


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


@pytest.mark.parametrize("exclude_idp", [False, True])
def test_full_prepare_offline_replay_import_and_scope(
    tmp_path, season_source, exclude_idp
):
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
    if exclude_idp:
        source = entry.season_rating_inputs["2024"]["asset_source"]
        source["valuation_policy"]["version"] = "stats-guy-offense-v2"
        scope = rating_scope(entry, 2024)
        assert scope["valuation_source"] == "stats_guy"
        assert "individual defensive players" in scope["valuation_note"]
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
        prepare(
            entry,
            EvidenceClient(tmp_path / "receipts", http=http),
            2024,
            tmp_path / "output",
        )
    assert not (tmp_path / "output/manifest.json").exists()


@pytest.mark.parametrize("resolution", ["idp", "drop"])
def test_prepare_explicit_asset_resolutions_preserve_evidence_checks(
    tmp_path, season_source, resolution
):
    entry, handler, _ = season_source

    def adjusted(request):
        data = handler(request).json()
        if resolution == "idp" and request.url.path.endswith("/players/nfl"):
            data["p49"]["position"] = "DE"
        if resolution == "drop" and request.url.path.endswith("/rosters"):
            data[1]["players"].remove("p49")
        if resolution == "drop" and request.url.path.endswith("/transactions/18"):
            data = [
                {
                    "transaction_id": "synthetic-drop",
                    "status": "complete",
                    "status_updated": 1736200000000,
                    "drops": {"p49": 2},
                }
            ]
        return httpx.Response(200, json=data)

    with httpx.Client(transport=httpx.MockTransport(adjusted)) as http:
        client = EvidenceClient(tmp_path / "receipts", http=http)
        with pytest.raises(ValueError):
            prepare(entry, client, 2024, tmp_path / "blocked")
        kwargs = (
            {"exclude_idp": True}
            if resolution == "idp"
            else {
                "verified_pre_cutoff_drops": [
                    {
                        "player_id": "p49",
                        "roster_id": 2,
                        "transaction_id": "synthetic-drop",
                    }
                ]
            }
        )
        report = prepare(entry, client, 2024, tmp_path / "resolved", **kwargs)
    manifest = json.loads((tmp_path / "resolved/manifest.json").read_text())
    assert "p49" not in {p["player_id"] for p in manifest["players"]}
    assert report["status"] == "validated"
    if resolution == "idp":
        assert report["policy"]["version"] == "stats-guy-offense-v2"
    else:
        assert (
            report["verified_pre_cutoff_drops"] == kwargs["verified_pre_cutoff_drops"]
        )
        with pytest.raises(ValueError, match="Verified pre-cutoff drop"):
            prepare(
                entry,
                client,
                2024,
                tmp_path / "bad",
                verified_pre_cutoff_drops=[
                    {
                        **kwargs["verified_pre_cutoff_drops"][0],
                        "transaction_id": "wrong",
                    }
                ],
            )


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
        prepare(
            entry,
            EvidenceClient(tmp_path / "receipts", http=http),
            2024,
            tmp_path / "output",
        )
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
def test_inconsistent_source_evidence_blocks_manifest(
    tmp_path, season_source, mutation
):
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
        prepare(
            entry,
            EvidenceClient(tmp_path / "receipts", http=http),
            2024,
            tmp_path / "output",
        )
    assert not (tmp_path / "output/manifest.json").exists()


@pytest.mark.parametrize("round_type", [1, 2])
def test_multiweek_brackets_use_every_leg_and_aggregate_winner(round_type):
    # Mutation: validate only the first leg, or silently accept a missing second leg.
    from app.services.historical_backfill_run import validate_brackets

    winners = [{"m": 1, "r": 1, "p": 1, "w": 1, "l": 2}]
    losers = [{"m": 1, "r": 1, "p": 1, "w": 3, "l": 4}]
    matchups = {
        ("fixture", week, rid): {"opponent_roster_id": opponent, "team_points": score}
        for week, scores in [(16, [80, 100, 100, 80]), (17, [130, 100, 60, 100])]
        for rid, opponent, score in zip([1, 2, 3, 4], [2, 1, 4, 3], scores)
    }
    kwargs = {
        "matchups": matchups,
        "league_id": "fixture",
        "playoff_start": 16,
        "final_week": 17,
        "playoff_round_type": round_type,
        "toilet_bowl": True,
    }
    validate_brackets(winners, losers, [1, 2, 3, 4], 2, **kwargs)
    matchups.pop(("fixture", 17, 1))
    with pytest.raises(ValueError, match="disagrees"):
        validate_brackets(winners, losers, [1, 2, 3, 4], 2, **kwargs)


def test_median_standings_count_extra_game_without_doubling_points():
    # Mutation: omit median games, count median ties as wins, or add median points to PF/PA.
    from app.services.historical_backfill_run import historical_standings

    matchups = {
        ("fixture", 1, rid): {"team_points": score, "opponent_points": opposing}
        for rid, score, opposing in [
            (1, 120, 110),
            (2, 110, 120),
            (3, 100, 90),
            (4, 90, 100),
        ]
    }
    mapping = {i: str(i) for i in range(1, 5)}
    rows = historical_standings(
        matchups,
        league_id="fixture",
        playoff_start=2,
        roster_to_user=mapping,
        median_game=True,
    )
    actual = {
        r.roster_id: (r.wins, r.losses, r.ties, r.points_for, r.points_against)
        for r in rows
    }
    assert actual == {
        1: (2, 0, 0, 120, 110),
        2: (1, 1, 0, 110, 120),
        3: (1, 1, 0, 100, 90),
        4: (0, 2, 0, 90, 100),
    }
    matchups[("fixture", 1, 2)].update(team_points=100)
    rows = historical_standings(
        matchups,
        league_id="fixture",
        playoff_start=2,
        roster_to_user=mapping,
        median_game=True,
    )
    assert {r.roster_id: r.ties for r in rows} == {1: 0, 2: 1, 3: 1, 4: 0}
    matchups.pop(("fixture", 1, 4))
    with pytest.raises(ValueError, match="incomplete"):
        historical_standings(
            matchups,
            league_id="fixture",
            playoff_start=2,
            roster_to_user=mapping,
            median_game=True,
        )


def test_collect_accepts_verified_keeper_median_settings(tmp_path, season_source):
    # Mutation: reject keeper/median formats wholesale instead of reconciling their records.
    entry, handler, _ = season_source
    entry.chain[0]["format"] = "keeper"

    def adjusted(request):
        data = handler(request).json()
        if request.url.path.endswith("/league/league"):
            data["settings"].update(type=1, league_average_match=1)
        if request.url.path.endswith("/rosters"):
            for row in data:
                row["settings"]["wins"] *= 2
                row["settings"]["losses"] *= 2
        return httpx.Response(200, json=data)

    with httpx.Client(transport=httpx.MockTransport(adjusted)) as http:
        from app.services.historical_backfill_run import collect

        _, _, supporting = collect(
            entry=entry,
            client=EvidenceClient(tmp_path / "receipts", http=http),
            season=2024,
            results_only=True,
        )
    assert supporting["roster_records_by_league"]["league"][1]["wins"] == 34
    # The same verified Results must not authorize dynasty rookie-pick pricing.
    with pytest.raises(ValueError, match="Keeper/redraft assets require"):
        collect(
            entry=entry,
            client=EvidenceClient(tmp_path / "receipts", offline=True),
            season=2024,
        )


@pytest.mark.parametrize("opponent_points", [None, float("nan"), float("inf")])
def test_median_cannot_hide_missing_head_to_head_evidence(opponent_points):
    # Mutation: validate only team scores, then silently skip an incomplete H2H game.
    from app.services.historical_backfill_run import historical_standings

    matchups = {
        ("fixture", 1, 1): {"team_points": 120, "opponent_points": opponent_points},
        ("fixture", 1, 2): {"team_points": 100, "opponent_points": 120},
    }
    with pytest.raises(ValueError, match="incomplete or invalid"):
        historical_standings(
            matchups,
            league_id="fixture",
            playoff_start=2,
            roster_to_user={1: "a", 2: "b"},
            median_game=True,
        )


def test_exact_approved_points_resolution_is_bound_to_observed_values(
    tmp_path, season_source
):
    from app.services.historical_backfill_run import collect

    entry, handler, _ = season_source

    def adjusted(request):
        data = handler(request).json()
        if request.url.path.endswith("/rosters"):
            data[0]["settings"]["fpts"] += 1
        return httpx.Response(200, json=data)

    with httpx.Client(transport=httpx.MockTransport(adjusted)) as http:
        client = EvidenceClient(tmp_path / "receipts", http=http)
        with pytest.raises(ValueError, match="disagree"):
            collect(client, entry, 2024, results_only=True)
    approval = {
        "season": 2024,
        "roster_id": 1,
        "field": "points_for",
        "provider": 2041,
        "recomputed": 2040,
    }
    client = EvidenceClient(
        tmp_path / "receipts", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    _, _, support = collect(
        client, entry, 2024, results_only=True, approved_points_resolutions=[approval]
    )
    assert support["roster_records_by_league"]["league"][1]["points_for"] == 2040
    assert support["source_roster_records_by_league"]["league"][1]["points_for"] == 2041
    assert (
        support["evidence_discrepancies"][0]["resolution"] == "approved_weekly_scores"
    )
    for bad in (
        {**approval, "provider": 2042},
        {**approval, "field": "wins"},
        {**approval, "roster_id": 2},
    ):
        with pytest.raises(ValueError):
            collect(
                client,
                entry,
                2024,
                results_only=True,
                approved_points_resolutions=[bad],
            )


@pytest.mark.parametrize("excluded", [False, True])
@pytest.mark.parametrize("blocked", [None, "record", "postseason", "selected_record"])
def test_prior_year_points_policy_preserves_hard_gates(
    tmp_path, season_source, blocked, excluded
):
    from app.services.historical_backfill_run import collect

    entry, handler, _ = season_source
    entry.league_season_by_id["prior"] = 2023
    entry.roster_to_user_by_league["prior"] = {1: "a", 2: "b"}

    def adjusted(request):
        prior = "/prior" in request.url.path
        data = handler(
            httpx.Request("GET", str(request.url).replace("/prior", "/league"))
        ).json()
        if prior and request.url.path.endswith("/prior"):
            data["season"] = "2023"
        if prior and request.url.path.endswith("/rosters"):
            data[0]["settings"]["fpts_decimal"] = 1
            if blocked == "record":
                data[0]["settings"]["wins"] -= 1
        if (
            not prior
            and blocked == "selected_record"
            and request.url.path.endswith("/rosters")
        ):
            data[0]["settings"]["wins"] -= 1
        if (
            prior
            and blocked == "postseason"
            and request.url.path.endswith("/winners_bracket")
        ):
            data = []
        return httpx.Response(200, json=data)

    approval = {
        "season": 2023,
        "roster_id": 1,
        "field": "points_for",
        "provider": 2040.01,
        "recomputed": 2040,
    }
    with httpx.Client(transport=httpx.MockTransport(adjusted)) as http:
        client = EvidenceClient(tmp_path / "receipts", http=http)
        if (blocked and not excluded) or blocked == "selected_record":
            with pytest.raises(
                ValueError, match="disagree|Missing postseason participants"
            ):
                collect(
                    client,
                    entry,
                    2024,
                    results_only=True,
                    approved_points_resolutions=[approval],
                    excluded_result_seasons={2023: "Unresolved results"}
                    if excluded
                    else None,
                )
        else:
            _, _, support = collect(
                client,
                entry,
                2024,
                results_only=True,
                approved_points_resolutions=[approval],
                excluded_result_seasons={2023: "Unresolved results"}
                if excluded
                else None,
            )
            assert support["roster_records_by_league"]["prior"][1]["points_for"] == (
                2040.01 if excluded else 2040
            )
            assert (
                support["source_roster_records_by_league"]["prior"][1]["points_for"]
                == 2040.01
            )
            assert ("prior", 18, 1) in support["matchups"]
            if excluded:
                assert support["excluded_result_seasons"] == {
                    2023: "Unresolved results"
                }
                assert support["excluded_points_resolutions"] == [approval]
                assert support["approved_points_resolutions"] == []
                return
            audit = support["evidence_discrepancies"][0]
            assert audit["season"] == 2023
            assert audit["differences"]["points_for"] == {
                "provider": 2040.01,
                "recomputed": 2040,
            }
            assert audit["resolution"] == "approved_weekly_scores"


@pytest.mark.parametrize(
    "exclusions", [{2024: "selected"}, {2022: "unknown"}, {2023: " "}]
)
def test_result_exclusions_require_known_prior_year_and_reason(
    tmp_path, season_source, exclusions
):
    from app.services.historical_backfill_run import collect

    entry, handler, _ = season_source
    entry.league_season_by_id["prior"] = 2023
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(ValueError, match="exclusion"),
    ):
        collect(
            EvidenceClient(tmp_path / "receipts", http=http),
            entry,
            2024,
            results_only=True,
            excluded_result_seasons=exclusions,
        )


@pytest.mark.parametrize("missing_transaction", [False, True])
def test_excluded_results_keep_prior_pick_transfers(
    tmp_path, season_source, missing_transaction
):
    # Mutation: omit excluded-year transactions, losing inherited ownership.
    from app.services.historical_backfill_run import collect

    entry, handler, _ = season_source
    entry.league_season_by_id["prior"] = 2023
    entry.roster_to_user_by_league["prior"] = {1: "a", 2: "b"}
    pick = {
        "season": "2025",
        "round": 1,
        "roster_id": 1,
        "previous_owner_id": 1,
        "owner_id": 2,
    }

    def adjusted(request):
        path = request.url.path
        prior = "/prior" in path
        data = handler(
            httpx.Request(
                request.method,
                str(request.url).replace("/prior", "/league"),
                content=request.content,
            )
        ).json()
        if path.endswith("/prior"):
            data["season"] = "2023"
        elif prior and path.endswith("/winners_bracket"):
            data = []
        elif prior and path.endswith("/transactions/0"):
            if missing_transaction:
                return httpx.Response(404)
            data = [
                {
                    "transaction_id": "synthetic-transfer",
                    "status": "complete",
                    "status_updated": 1700000000000,
                    "draft_picks": [pick],
                }
            ]
        elif path.endswith("/traded_picks"):
            data = [pick]
        return httpx.Response(200, json=data)

    with httpx.Client(transport=httpx.MockTransport(adjusted)) as http:
        client = EvidenceClient(tmp_path / "receipts", http=http)
        if missing_transaction:
            with pytest.raises(ValueError, match="Evidence request failed HTTP 404"):
                collect(
                    client,
                    entry,
                    2024,
                    excluded_result_seasons={2023: "Unverified bracket"},
                )
        else:
            raw, _, support = collect(
                client,
                entry,
                2024,
                excluded_result_seasons={2023: "Unverified bracket"},
            )
            transferred = [
                p
                for p in raw["picks"]
                if p["season"] == 2025 and p["original_owner_id"] == "a"
            ]
            assert len(transferred) == 1
            assert transferred[0]["owner_id"] == "b"
            assert support["verified_result_seasons"] == [2024]
            report = prepare(
                entry,
                client,
                2024,
                tmp_path / "preview",
                excluded_result_seasons={2023: "Unverified bracket"},
            )
            coverage = json.loads((tmp_path / "preview/results-coverage.json").read_text())
            assert coverage["included_seasons"] == [2024]
            assert coverage["excluded_seasons"] == [{"season": 2023, "reason": "Unverified bracket"}]
            assert report["excluded_result_seasons"] == {2023: "Unverified bracket"}
            assert set(report["rankings"]) == {"a", "b"}
            replay = prepare(
                entry,
                EvidenceClient(tmp_path / "receipts", offline=True),
                2024,
                tmp_path / "replay",
                excluded_result_seasons={2023: "Unverified bracket"},
            )
            assert replay == report


def test_captured_median_season_reconciles_all_provider_records():
    # Mutation: count only H2H or add median totals to points against.
    # Sanitized full 2025 Sleeper archive: ten teams, thirteen regular-season weeks.
    from app.services.grader_io import _assemble_played_matchups
    from app.services.historical_backfill_run import historical_standings

    data = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/historical_median_season.json"
        ).read_text()
    )
    matchups = _assemble_played_matchups(
        {int(w): rows for w, rows in data["weekly"].items()}, "fixture"
    )
    mapping = {int(r): str(r) for r in data["records"]}
    rows = historical_standings(
        matchups,
        league_id="fixture",
        playoff_start=data["playoff_start"],
        roster_to_user=mapping,
        median_game=True,
    )
    for row in rows:
        expected = data["records"][str(row.roster_id)]
        assert (row.wins, row.losses, row.ties) == tuple(
            expected[k] for k in ("wins", "losses", "ties")
        )
        assert row.points_for == pytest.approx(
            expected["fpts"] + expected["fpts_decimal"] / 100
        )
        assert row.points_against == pytest.approx(
            expected["fpts_against"] + expected["fpts_against_decimal"] / 100
        )


def test_short_toilet_bracket_requires_proven_idle_middle_seeds():
    # Mutation: accept any missing participants, or require every non-playoff team to play.
    from app.services.historical_backfill_run import verified_idle_rosters

    from sleeper_dynasty.engine.standings import StandingRow

    rows = [StandingRow(str(i), i, 11 - i, i, 0, 1000 - i, 1000) for i in range(1, 11)]
    winners = [{"w": 1, "l": 2}, {"w": 3, "l": 4}]
    losers = [{"w": 7, "l": 8}, {"w": 9, "l": 10}]
    weekly = {
        w: [
            {"roster_id": i, "matchup_id": None if i in (5, 6) else i // 2}
            for i in range(1, 11)
        ]
        for w in range(14, 18)
    }
    settings = {"playoff_teams": 4, "playoff_type": 0, "playoff_round_type": 2}
    assert verified_idle_rosters(weekly, rows, winners, losers, settings, 14, 17) == {
        5,
        6,
    }
    weekly[15][4]["matchup_id"] = 99
    with pytest.raises(ValueError, match="inactive"):
        verified_idle_rosters(weekly, rows, winners, losers, settings, 14, 17)
    weekly[15][4]["matchup_id"] = None
    losers[0]["w"] = 5
    with pytest.raises(ValueError, match="inactive"):
        verified_idle_rosters(weekly, rows, winners, losers, settings, 14, 17)


@pytest.mark.parametrize("index", range(4))
def test_captured_multiweek_brackets_and_idle_teams(index):
    # Mutation: validate weekly winners rather than aggregate rounds, or infer missing participants.
    from app.services.grader_io import _assemble_played_matchups
    from app.services.historical_backfill_run import (
        validate_brackets,
        verified_idle_rosters,
    )

    from sleeper_dynasty.engine.standings import StandingRow

    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/historical_multiweek_brackets.json"
        ).read_text()
    )[index]
    settings = fixture["settings"]
    weekly = {int(w): rows for w, rows in fixture["weekly"].items()}
    rows = [
        StandingRow(
            str(r["roster_id"]),
            r["roster_id"],
            r["settings"]["wins"],
            r["settings"]["losses"],
            r["settings"]["ties"],
            r["settings"]["fpts"] + r["settings"].get("fpts_decimal", 0) / 100,
            0,
        )
        for r in fixture["rosters"]
    ]
    start, end = settings["playoff_week_start"], settings["last_scored_leg"]
    inactive = verified_idle_rosters(
        weekly, rows, fixture["winners"], fixture["losers"], settings, start, end
    )
    assert len(inactive) == (2 if index >= 2 else 0)
    matchups = _assemble_played_matchups(weekly, "fixture")
    kwargs = {
        "matchups": matchups,
        "league_id": "fixture",
        "playoff_start": start,
        "final_week": end,
        "playoff_round_type": settings["playoff_round_type"],
        "toilet_bowl": settings["playoff_type"] == 0,
        "inactive_rosters": inactive,
    }
    validate_brackets(
        fixture["winners"],
        fixture["losers"],
        [r.roster_id for r in rows],
        settings["playoff_teams"],
        **kwargs,
    )
    title = next(g for g in fixture["winners"] if g.get("p") == 1)
    matchups.pop(("fixture", end, title["w"]))
    with pytest.raises(ValueError, match="disagrees"):
        validate_brackets(
            fixture["winners"],
            fixture["losers"],
            [r.roster_id for r in rows],
            settings["playoff_teams"],
            **kwargs,
        )
