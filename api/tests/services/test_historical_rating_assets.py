import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


def manifest():
    return {
        "version": 1, "season": 2024, "season_league_id": "old", "format": "dynasty",
        "as_of": "2025-01-07", "through_week": 14, "prices_as_of": "2025-01-07",
        "identity_version": "", "verified_by": "test operator", "verified_at": "2026-10-23",
        "roster_source": "fixture final roster", "picks_source": "fixture complete transfers",
        "prices_source": "fixture dated price archive", "owners": ["u1", "u2"],
        "draft_rounds": 1, "pick_horizon": 3,
        "players": [
            {"player_id": "p1", "owner_id": "u1", "value": 9000, "birth_date": "2000-01-07"},
            {"player_id": "p2", "owner_id": "u2", "value": 1000, "birth_date": "1990-01-01"}],
        "picks": [{"season": year, "round": 1, "original_owner_id": owner,
                   "owner_id": "u2", "value": 1000}
                  for year in (2025, 2026, 2027) for owner in ("u1", "u2")],
    }


def test_verified_assets_use_historical_ages_holdings_and_pick_transfers():
    # Mutation: price current players or credit picks to original instead of actual owners.
    from app.services.historical_rating_assets import HistoricalRatingAssets
    assets = HistoricalRatingAssets.model_validate(manifest())
    signals, ranks = assets.signals()
    assert signals["u1"]["roster_value_share"] == 0.9
    assert signals["u1"]["young_core_share"] == 1
    assert signals["u1"]["draft_capital"] == 0
    assert signals["u2"]["draft_capital"] == 6000
    assert ranks["u1"] == {"rank": 1, "of": 2}


@pytest.mark.parametrize("policy_version", ["stats-guy-v1", "stats-guy-offense-v2", "dynasty-process-v1", "dynasty-process-offense-v2"])
def test_keeper_dated_policy_accepts_verified_rosters_without_future_assets(
    policy_version,
):
    from app.services.historical_backfill import digest
    from app.services.historical_rating_assets import HistoricalRatingAssets

    data = manifest()
    data.update(format="keeper", draft_rounds=0, picks=[], prices_as_of="2025-01-06")
    for player in data["players"]:
        player.update(position="RB", pricing="provider")
    data = HistoricalRatingAssets.model_validate(data).model_dump(
        mode="json", exclude={"validation"}
    )
    data["valuation_policy"] = {
        "version": policy_version,
        "source_url": "https://dynastyprocess.com" if policy_version.startswith("dynasty-process") else "https://statsguyfantasy.com",
        "excluded": (
            [{"player_id": "defender", "owner_id": "u1", "position": "LB"}]
            if policy_version.endswith("offense-v2")
            else []
        ),
        "unranked_upper_bounds": {},
        "priced": 2,
        "eligible": 2,
        "evidence_sha256": "a" * 64,
    }
    data["validation"] = {
        "manifest_sha256": digest(data),
        "result_inputs_sha256": "b" * 64,
        "stable": True,
        "scenarios": 1,
    }
    assets = HistoricalRatingAssets.model_validate(data)
    signals, _ = assets.signals()
    assert signals["u1"]["roster_value_share"] == 0.9
    assert signals["u1"]["draft_capital"] == signals["u2"]["draft_capital"] == 0
    if policy_version == "dynasty-process-v1":
        invalid = deepcopy(data)
        invalid['valuation_policy']['source_url'] = 'https://statsguyfantasy.com'
        with pytest.raises(ValueError, match='source'):
            HistoricalRatingAssets.model_validate(invalid)
    if policy_version == "stats-guy-offense-v2":
        invalid = deepcopy(data)
        invalid["valuation_policy"]["version"] = "stats-guy-v1"
        with pytest.raises(ValueError, match="Invalid excluded assets"):
            HistoricalRatingAssets.model_validate(invalid)
    data["players"][0]["value"] = 1
    with pytest.raises(ValueError, match="differs from validated preview"):
        HistoricalRatingAssets.model_validate(data)


@pytest.mark.parametrize("change", ["future_price", "missing_pick", "duplicate_player", "missing_age", "unknown_owner"])
def test_incomplete_or_future_assets_are_rejected(change):
    # Mutation: accept future prices, missing inventory, or incomplete player evidence.
    from app.services.historical_rating_assets import HistoricalRatingAssets
    data = manifest()
    if change == "future_price":
        data["prices_as_of"] = "2025-01-08"
    elif change == "missing_pick":
        data["picks"].pop()
    elif change == "duplicate_player":
        data["players"].append(deepcopy(data["players"][0]))
    elif change == "missing_age":
        del data["players"][0]["birth_date"]
    else:
        data["players"][0]["owner_id"] = "future_owner"
    with pytest.raises(ValueError):
        HistoricalRatingAssets.model_validate(data)


def test_asset_store_rejects_wrong_identity_format_and_season(tmp_path):
    # Mutation: reuse an otherwise valid manifest after identity/settings change.
    from app.services.historical_rating_assets import HistoricalAssetStore
    store = HistoricalAssetStore(tmp_path, "chain")
    store.import_verified(manifest())
    kwargs = {"season": 2024, "season_league_id": "old", "owners": ["u1", "u2"],
              "format": "dynasty", "identity_version": "", "through_week": 14, "cutoff_date": "2025-01-07"}
    assets, reason = store.load(**kwargs)
    assert assets is not None and reason is None
    for key, value in (("identity_version", "changed"), ("format", "keeper"), ("through_week", 15)):
        assets, reason = store.load(**{**kwargs, key: value})
        assert assets is None and "does not match" in reason


def test_historical_import_survives_chain_rollover(tmp_path):
    # Mutation: namespace evidence by the newest league ID instead of its historical season ID.
    from app.services.historical_rating_assets import HistoricalAssetStore
    HistoricalAssetStore(tmp_path, "old-chain").import_verified(manifest())
    assets, _ = HistoricalAssetStore(tmp_path, "new-chain").load(
        season=2024, season_league_id="old", owners=["u1", "u2"],
        format="dynasty", identity_version="", through_week=14, cutoff_date="2025-01-07")
    assert assets is not None


def test_offseason_date_cannot_pass_as_season_end(tmp_path):
    # Mutation: only check the broad winter interval, not the provider's final-week cutoff.
    from app.services.historical_rating_assets import HistoricalAssetStore
    data = manifest()
    data.update(as_of="2025-02-28", prices_as_of="2025-02-28")
    store = HistoricalAssetStore(tmp_path, "chain")
    store.import_verified(data)
    assets, reason = store.load(season=2024, season_league_id="old", owners=["u1", "u2"],
        format="dynasty", identity_version="", through_week=14, cutoff_date="2025-01-07")
    assert assets is None and "cutoff" in reason


@pytest.mark.asyncio
async def test_cutoff_uses_completed_provider_week_and_reuses_evidence(tmp_path, monkeypatch):
    # Mutation: accept the importer's date or refetch immutable evidence on every refresh.
    # Sanitized real ESPN response: 2024 regular-season week 18, captured 2026-10-23.
    from app.services.historical_rating_assets import HistoricalAssetStore
    raw = (Path(__file__).parents[1] / "fixtures/historical_cutoff_scoreboard.json").read_text()
    monkeypatch.setattr("sleeper_dynasty.api.nfl_schedule.fetch_week_evidence", AsyncMock(return_value={
        "raw": raw, "source": "ESPN public scoreboard", "provider_timestamp": "captured fixture"}))
    store = HistoricalAssetStore(tmp_path, "chain")
    assert await store.verified_week_cutoff(2024, 18) == "2025-01-07"
    monkeypatch.setattr("sleeper_dynasty.api.nfl_schedule.fetch_week_evidence", AsyncMock(side_effect=AssertionError("must reuse")))
    assert await store.verified_week_cutoff(2024, 18) == "2025-01-07"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["wrong_week", "not_final", "empty"])
async def test_incomplete_schedule_never_establishes_cutoff(tmp_path, monkeypatch, mutation):
    # Mutation: drop season/week or completion validation and stamp an unverified cutoff.
    from app.services.historical_rating_assets import HistoricalAssetStore
    raw = json.loads((Path(__file__).parents[1] / "fixtures/historical_cutoff_scoreboard.json").read_text())
    if mutation == "wrong_week":
        raw["week"]["number"] = 17
    elif mutation == "not_final":
        raw["events"][0]["status"]["type"]["completed"] = False
    else:
        raw["events"] = []
    monkeypatch.setattr("sleeper_dynasty.api.nfl_schedule.fetch_week_evidence", AsyncMock(return_value={"raw": json.dumps(raw)}))
    with pytest.raises(ValueError):
        await HistoricalAssetStore(tmp_path, "chain").verified_week_cutoff(2024, 18)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,state,expected", [
    ("STATUS_CANCELED", "post", "2023-01-04"),
    ("STATUS_POSTPONED", "post", None),
    ("STATUS_SUSPENDED", "in", None),
    ("STATUS_CANCELED", "pre", None),
])
async def test_terminal_cancellation_can_close_historical_week(tmp_path, monkeypatch, status, state, expected):
    from app.services.historical_rating_assets import HistoricalAssetStore
    # Mutation: reject terminal cancellations, or accept any unfinished/post-state game.
    # Captured ESPN 2022 week 17: Buffalo-Cincinnati was canceled, not awaiting completion.
    raw = json.loads((Path(__file__).parents[1] / "fixtures/historical_cutoff_canceled_scoreboard.json").read_text())
    canceled = next(e for e in raw["events"] if e["status"]["type"]["name"] == "STATUS_CANCELED")
    canceled["status"]["type"].update(name=status, state=state)
    monkeypatch.setattr("sleeper_dynasty.api.nfl_schedule.fetch_week_evidence", AsyncMock(return_value={"raw": json.dumps(raw)}))
    store = HistoricalAssetStore(tmp_path, "chain")
    if expected:
        assert await store.verified_week_cutoff(2022, 17) == expected
    else:
        with pytest.raises(ValueError, match="incomplete"):
            await store.verified_week_cutoff(2022, 17)
