from copy import deepcopy

import pytest

from .test_full_player_pick_values import inputs


def evidence():
    _, draft, picks, support = inputs()
    draft["season"] = "2025"
    return {
        "season": 2025,
        "league_id": "L",
        "cutoff": "2025-12-31",
        "source": "stats_guy",
        "format": "sf_dynasty",
        "draft": draft,
        "picks": picks,
        "positions": support["positions"],
        "board": {
            "asOf": "2025-12-30",
            "format": "sf_dynasty",
            "tep": "std",
            "total": 6,
            "rankings": [
                {"id": pid, "position": "WR", "value": v.superflex_value}
                for pid, v in support["ktc_by_player_id"].items()
            ],
        },
    }


def test_dated_model_uses_dated_prices_and_replays_evidence():
    # Mutation: use current or rookie prices instead of the dated player board.
    from app.services.historical_full_player_picks import estimate, validate

    args = evidence()
    receipt = estimate(**args)
    assert receipt["estimate"]["rounds"][0]["value"] == 6000
    assert receipt["estimate"]["prices_as_of"] == "2025-12-30"
    validate(receipt)
    damaged = deepcopy(receipt)
    damaged["estimate"]["rounds"][0]["value"] += 1
    with pytest.raises(ValueError, match="replay"):
        validate(damaged)


@pytest.mark.parametrize(
    "damage", ["future", "stale", "missing", "wrong_format", "truncated"]
)
def test_dated_model_rejects_unverified_prices(damage):
    # Mutation: omit date/coverage checks and silently accept unverified input.
    from app.services.historical_full_player_picks import estimate

    args = evidence()
    if damage == "future":
        args["board"]["asOf"] = "2026-01-01"
    if damage == "stale":
        args["board"]["asOf"] = "2025-12-01"
    if damage == "missing":
        args["board"]["rankings"].pop()
        args["board"]["total"] -= 1
    if damage == "wrong_format":
        args["board"]["format"] = "non_sf_dynasty"
    if damage == "truncated":
        args["board"]["total"] += 1
    with pytest.raises(ValueError):
        estimate(**args)


def dated_manifest():
    from app.services.historical_backfill import digest
    from app.services.historical_full_player_picks import estimate
    from app.services.historical_rating_assets import HistoricalRatingAssets

    from .test_historical_rating_assets import manifest

    raw = manifest()
    raw.update(
        season=2025,
        season_league_id="L",
        format="keeper",
        as_of="2025-12-31",
        prices_as_of="2025-12-30",
        draft_rounds=3,
    )
    raw["players"] = [
        {
            "player_id": pid,
            "owner_id": uid,
            "value": value,
            "birth_date": "2000-01-01",
            "position": "WR",
            "pricing": "provider",
        }
        for pid, uid, value in [("1", "u1", 9999), ("2", "u2", 6000)]
    ]
    receipt = estimate(**evidence())
    raw["picks"] = [
        {
            "season": y,
            "round": r["round"],
            "original_owner_id": uid,
            "owner_id": uid,
            "value": r["value"],
        }
        for y in (2026, 2027, 2028)
        for r in receipt["estimate"]["rounds"]
        for uid in ("u1", "u2")
    ]
    raw = HistoricalRatingAssets.model_validate(raw).model_dump(
        mode="json", exclude={"validation"}
    )
    raw["pick_valuation"] = receipt
    raw["valuation_policy"] = {
        "version": "stats-guy-v1",
        "source_url": "https://statsguyfantasy.com",
        "excluded": [],
        "unranked_upper_bounds": {},
        "priced": 2,
        "eligible": 2,
        "evidence_sha256": "a" * 64,
    }
    raw["validation"] = {
        "manifest_sha256": digest(raw),
        "result_inputs_sha256": "b" * 64,
        "stable": True,
        "scenarios": 1,
    }
    return raw


def test_manifest_binds_pick_model_to_roster_scale_and_inventory():
    # Mutation: accept modeled picks at unrelated prices, dates, or season.
    from app.services.historical_rating_assets import HistoricalRatingAssets

    raw = dated_manifest()
    assert HistoricalRatingAssets.model_validate(raw).pick_valuation
    for field, value in [("value", 123), ("round", 4)]:
        damaged = deepcopy(raw)
        damaged["picks"][0][field] = value
        with pytest.raises(ValueError):
            HistoricalRatingAssets.model_validate(damaged)


def test_model_only_historical_scope_is_provisional_and_tampering_unavailable():
    # Mutation: require excluded Results for model-only history or trust altered assets.
    from app.services.historical_backfill import digest
    from app.services.historical_rating_assets import HistoricalRatingAssets
    from app.services.season_ratings import historical_results_digest, rating_scope

    from ._grader_fixtures import _v2_entry

    e = _v2_entry(capabilities={"format": "keeper"})
    e.league_season_by_id = {"L": 2025}
    e.roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    raw = dated_manifest()
    snapshot = {
        "version": 1,
        "status": "provisional",
        "basis": "season_end",
        "format": "keeper",
        "as_of": raw["as_of"],
        "owners": raw["owners"],
        "season_records": {},
        "outcome_signals": e.outcome_signals,
    }
    raw["validation"]["result_inputs_sha256"] = historical_results_digest(snapshot)
    raw["validation"]["manifest_sha256"] = digest(
        {k: v for k, v in raw.items() if k != "validation"}
    )
    assets = HistoricalRatingAssets.model_validate(raw)
    signals, ranks = assets.signals()
    snapshot.update(asset_source=raw, outlook_signals=signals, roster_ranks=ranks)
    e.season_rating_inputs = {"2025": snapshot}
    assert rating_scope(e, 2025)["status"] == "provisional"
    assert "full-player" in rating_scope(e, 2025)["valuation_note"]
    snapshot["outlook_signals"]["u1"]["draft_capital"] += 1
    assert rating_scope(e, 2025)["status"] == "unavailable"


def test_historical_idp_exclusion_is_explicit_and_preserves_offensive_round_sample():
    # Mutation: include IDP prices in an offensive-asset model or silently exclude them.
    from app.services.historical_full_player_picks import estimate

    args = evidence()
    args["positions"]["6"] = "LB"
    args["board"]["rankings"][-1].update(position="LB", value=99999)
    with pytest.raises(ValueError):
        estimate(**args)
    receipt = estimate(**args, exclude_idp=True)
    assert receipt["estimate"]["rounds"][-1]["value"] == 2000
    assert receipt["estimate"]["selections"][-1]["source"] == "excluded-position"
    assert receipt["exclude_idp"] is True
