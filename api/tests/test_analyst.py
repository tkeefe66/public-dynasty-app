from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from sleeper_dynasty.models.league import League, MatchupResult, Roster


@pytest.fixture(autouse=True)
def isolated_bet_snapshot(monkeypatch):
    monkeypatch.setattr("app.services.analyst.load_bets_snapshot", AsyncMock(return_value={
        "available": True, "as_of": "2026-09-17T12:00:00+00:00", "active": [], "resolved": [],
    }))


def setup_league():
    league = League("123", "Test League", 2026, 2, ["QB", "BN"], {}, 15, 2, "in_season")
    client = SimpleNamespace(
        get_nfl_state=AsyncMock(return_value={"season": "2026", "week": 2, "season_type": "regular"}),
        get_league=AsyncMock(return_value=(league, None)),
        get_rosters=AsyncMock(return_value=[
            Roster(1, "a", "Alice", ["p1"], 9, 0, 0, 900, 0),
            Roster(2, "b", "Bob", ["p2"], 0, 9, 0, 800, 0),
        ]),
        get_matchup_results=AsyncMock(return_value=[
            MatchupResult(1, 1, 1, 25, ["p1"], ["p1"], {"p1": 25}),
            MatchupResult(1, 1, 2, 15, ["p2"], ["p2"], {"p2": 15}),
        ]),
        get_players=AsyncMock(return_value={
            "p1": {"full_name": "Player One", "position": "QB"},
            "p2": {"full_name": "Player Two", "position": "QB"},
        }),
        get_projections=AsyncMock(return_value={}),
    )
    entry = SimpleNamespace(league_id="123")
    writer = Mock(model="test-model")
    writer.write.return_value = "## Week one\nAlice wins."
    return client, entry, writer


@pytest.mark.asyncio
async def test_bets_and_standings_reach_writer_and_saved_edition(tmp_path, monkeypatch):
    # Mutation: build context but never pass it to the writer or archive it.
    from dataclasses import replace

    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    client.get_rosters.return_value = [replace(r, wins=1 if r.roster_id == 1 else 0,
                                              losses=0 if r.roster_id == 1 else 1,
                                              points_for=25 if r.roster_id == 1 else 15)
                                        for r in client.get_rosters.return_value]
    snapshot = {"available": True, "active": [{"id": "wager", "stake": "$25.00", "terms": "Higher finish"}], "resolved": []}
    loader = AsyncMock(return_value=snapshot)
    monkeypatch.setattr("app.services.analyst.load_bets_snapshot", loader)
    await generate_analyst(client, entry, tmp_path, writer=writer)
    packet = writer.write.call_args.args[0]
    assert packet.bets == snapshot
    assert packet.standings_race["emphasis"] == "early_trends"
    stored = AnalystStore(tmp_path).editions("123")[0]
    snapshot["active"][0]["stake"] = "$50.00"
    assert stored["facts"]["bets"]["active"][0]["stake"] == "$25.00"
    assert stored["facts"]["standings_race"]["teams"][0]["record_after"] == [1, 0, 0]


@pytest.mark.asyncio
async def test_catchup_does_not_backdate_current_bets(tmp_path, monkeypatch):
    # Mutation: attach today's active bets to every missing historical week.
    from dataclasses import replace

    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    client.get_nfl_state.return_value["week"] = 3
    results = client.get_matchup_results.return_value
    client.get_matchup_results.side_effect = lambda lid, week: [replace(r, week=week) for r in results]
    loader = AsyncMock(return_value={"available": True, "active": [], "resolved": []})
    monkeypatch.setattr("app.services.analyst.load_bets_snapshot", loader)
    await generate_analyst(client, entry, tmp_path, writer=writer)
    editions = AnalystStore(tmp_path).editions("123")
    assert editions[0]["facts"]["bets"]["available"] is True
    assert editions[1]["facts"]["bets"]["available"] is False
    loader.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_once_survives_refresh_and_reopen(tmp_path):
    # Mutation: always call the writer and overwrite the saved edition.
    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    await generate_analyst(client, entry, tmp_path, writer=writer)
    writer.write.return_value = "Changed text"
    await generate_analyst(client, entry, tmp_path, writer=writer)
    saved = AnalystStore(tmp_path).editions("123")
    assert len(saved) == 1
    assert saved[0]["markdown"] == "## Week one\nAlice wins."
    assert saved[0]["facts"]["standings"][0]["wins"] == 1
    assert writer.write.call_count == 1


@pytest.mark.asyncio
async def test_explicit_correction_generation_and_failure_preserve_published_text(tmp_path):
    # Mutation: skip existing editions even on an explicit correction, or publish a failed draft.
    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    await generate_analyst(client, entry, tmp_path, writer=writer)
    writer.write.side_effect = ValueError("review rejected")
    await generate_analyst(client, entry, tmp_path, writer=writer, correction_week=1, correction_reason="Accuracy fixes")
    assert AnalystStore(tmp_path).editions("123")[0]["revision"] == 1
    writer.write.side_effect = None
    writer.write.return_value = "Reviewed correction"
    await generate_analyst(client, entry, tmp_path, writer=writer, correction_week=1, correction_reason="Accuracy fixes")
    assert AnalystStore(tmp_path).editions("123")[0]["markdown"] == "Reviewed correction"
    assert AnalystStore(tmp_path).editions("123")[0]["revision"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [
    {"season": "2026", "week": 1, "season_type": "regular"},
    {"season": "2025", "week": 2, "season_type": "regular"},
    {"season": "2026", "week": 2, "season_type": "pre"},
])
async def test_never_generates_unfinished_or_wrong_season(tmp_path, state):
    # Mutation: ignore the NFL season/week eligibility boundary.
    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    client.get_nfl_state.return_value = state
    await generate_analyst(client, entry, tmp_path, writer=writer)
    assert AnalystStore(tmp_path).editions("123") == []
    writer.write.assert_not_called()


@pytest.mark.asyncio
async def test_failed_generation_retries_and_budget_skip_does_not_write(tmp_path):
    # Mutation: mark a failed or budget-skipped edition as successfully saved.
    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    await generate_analyst(client, entry, tmp_path, writer=writer, skip_llm=True)
    writer.write.assert_not_called()
    writer.write.side_effect = RuntimeError("provider unavailable")
    await generate_analyst(client, entry, tmp_path, writer=writer)
    assert AnalystStore(tmp_path).editions("123") == []
    writer.write.side_effect = None
    await generate_analyst(client, entry, tmp_path, writer=writer)
    assert len(AnalystStore(tmp_path).editions("123")) == 1


@pytest.mark.asyncio
async def test_partial_week_is_not_published(tmp_path):
    # Mutation: accept a week with missing opponents or missing player scores.
    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    client.get_matchup_results.return_value.pop()
    await generate_analyst(client, entry, tmp_path, writer=writer)
    assert AnalystStore(tmp_path).editions("123") == []
    writer.write.assert_not_called()


def test_corrupt_archive_fails_closed_and_path_is_validated(tmp_path):
    # Mutation: treat corruption as an empty archive and permit replacement.
    from app.services.analyst_store import AnalystStore
    store = AnalystStore(tmp_path)
    path = store.edition_path("123", 2026, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("broken json")
    with pytest.raises(ValueError):
        store.editions("123")
    assert path.read_text() == "broken json"
    with pytest.raises(ValueError):
        store.editions("../escape")


def test_archive_endpoint_exists_and_is_league_scoped(client):
    # Mutation: omit the route or accidentally use a global archive.
    response = client.get("/api/league/123/analyst")
    assert response.status_code == 200
    assert response.json() == {"editions": []}


@pytest.mark.asyncio
async def test_correction_preserves_original_and_survives_normal_refresh(tmp_path):
    # Mutation: overwrite the original or let automatic refresh replace a correction.
    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    await generate_analyst(client, entry, tmp_path, writer=writer)
    store = AnalystStore(tmp_path)
    original_path = store.edition_path("123", 2026, 1)
    before = original_path.read_bytes()
    edition = store.editions("123")[0]
    store.save_correction("123", {**edition, "markdown": "Corrected facts."}, "Correct ownership and bye claims.")
    await generate_analyst(client, entry, tmp_path, writer=writer)
    corrected = store.editions("123")[0]
    assert corrected["revision"] == 2
    assert corrected["markdown"] == "Corrected facts."
    assert corrected["original_markdown"] == edition["markdown"]
    assert original_path.read_bytes() == before
    assert writer.write.call_count == 1


@pytest.mark.asyncio
async def test_catches_up_weeks_and_survives_cache_invalidation_and_backup(tmp_path):
    # Mutation: generate only the latest week, or erase editions during cache reset.
    import tarfile
    from dataclasses import replace

    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    from app.services.backup_service import archive_cache

    from sleeper_dynasty.cache import FileCache
    client, entry, writer = setup_league()
    results = client.get_matchup_results.return_value
    client.get_matchup_results.side_effect = lambda lid, week: [replace(r, week=week) for r in results]
    client.get_nfl_state.return_value["week"] = 3
    await generate_analyst(client, entry, tmp_path, writer=writer)
    FileCache(tmp_path).invalidate_all()
    saved = AnalystStore(tmp_path).editions("123")
    assert [e["week"] for e in saved] == [2, 1]
    assert [e["facts"]["standings"][0]["wins"] for e in saved] == [2, 1]
    backup = tmp_path.parent / f"{tmp_path.name}.tar.gz"
    archive_cache(tmp_path, backup)
    with tarfile.open(backup) as archive:
        assert "analyst/123/2026-01.json" in archive.getnames()
        assert "analyst/123/2026-02.json" in archive.getnames()


@pytest.mark.asyncio
async def test_concurrent_refresh_calls_writer_once(tmp_path):
    # Mutation: remove the cross-process generation claim.
    import asyncio
    import time

    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore
    client, entry, writer = setup_league()
    def slow_write(*args, **kwargs):
        time.sleep(0.05)
        return "Saved once"
    writer.write.side_effect = slow_write
    await asyncio.gather(
        generate_analyst(client, entry, tmp_path, writer=writer),
        generate_analyst(client, entry, tmp_path, writer=writer),
    )
    assert writer.write.call_count == 1
    edition = AnalystStore(tmp_path).editions("123")[0]
    with pytest.raises(FileExistsError):
        AnalystStore(tmp_path).save("123", {**edition, "markdown": "Overwrite"})
    assert AnalystStore(tmp_path).editions("123")[0]["markdown"] == "Saved once"


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_real_writer_publishes_only_an_approved_correction(tmp_path, approved):
    # Mutation: save the initial rejected draft or the correction without its final approval.
    from anthropic.types import Message
    from app.services.analyst import generate_analyst
    from app.services.analyst_store import AnalystStore

    from sleeper_dynasty.llm.recap_writer import RecapWriter

    def response(content, stop_reason):
        return Message.model_validate(
            {
                "id": "msg_synthetic",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            }
        )

    def verdict(ok):
        return response(
            [
                {
                    "type": "tool_use",
                    "id": "toolu_synthetic",
                    "name": "submit_recap_review",
                    "input": {
                        "approved": ok,
                        "violations": [] if ok else ["Wrong score"],
                    },
                }
            ],
            "tool_use",
        )

    client, entry, _ = setup_league()
    writer = RecapWriter(api_key="test")
    writer._request = Mock(
        side_effect=[
            response(
                [{"type": "text", "text": "Alice scored 250 points."}], "end_turn"
            ),
            verdict(False),
            response([{"type": "text", "text": "Alice scored 25 points."}], "end_turn"),
            verdict(approved),
        ]
    )
    try:
        await generate_analyst(client, entry, tmp_path, writer=writer)
        saved = AnalystStore(tmp_path).editions("123")
        assert [e["markdown"] for e in saved] == (
            ["Alice scored 25 points."] if approved else []
        )
        assert writer._request.call_count == 4
    finally:
        writer._client.close()


@pytest.mark.asyncio
async def test_shared_refresh_invokes_generation_after_writing_cache(
    tmp_path, monkeypatch
):
    # Mutation: implement the generator but never call it from scheduled/manual refresh.
    from app.services import analyst, refresh_service
    from app.services.chain_cache import ChainCache

    from tests.test_refresh_service import _entry
    entry = _entry(league_id="123")
    monkeypatch.setattr(refresh_service.GraderService, "run", AsyncMock(return_value=entry))
    monkeypatch.setattr(refresh_service, "_llm_over_budget", AsyncMock(return_value=False))
    monkeypatch.setattr(refresh_service, "_snapshot_ratings", AsyncMock())
    async def generate(client, result, cache_dir, *, skip_llm):
        assert ChainCache(cache_dir).read("123") is not None
        assert result.league_id == "123"
        assert skip_llm is False
    spy = AsyncMock(side_effect=generate)
    monkeypatch.setattr(analyst, "generate_analyst", spy)
    await refresh_service.refresh_league(object(), "123", cache_dir=tmp_path)
    spy.assert_awaited_once()
