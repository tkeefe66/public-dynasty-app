from datetime import date, datetime, timezone
from types import SimpleNamespace
from contextlib import asynccontextmanager
import pytest


def bet(id="bet-a", **changes):
    fields = dict(id=id, league_id="test", season=2026, description="Higher season finish",
                  amount_cents=12550, side_a_owner_id="a", side_b_owner_id="b", status="open",
                  winner_owner_id=None, made_at=date(2026, 9, 1), settled_at=None,
                  updated_at=datetime(2026, 9, 17, tzinfo=timezone.utc))
    return SimpleNamespace(**{**fields, **changes})


def test_snapshot_preserves_stakes_and_flags_newly_recorded_settlement():
    # Mutation: include void bets, double winner-takes stake, or infer settlement from description.
    from app.services.analyst_bets import build_bets_snapshot
    now = datetime(2026, 9, 17, tzinfo=timezone.utc)
    previous = {"as_of": "2026-09-10T12:00:00+00:00", "active": [{"id": "settled"}], "resolved": []}
    result = build_bets_snapshot([bet(), bet("settled", status="settled", winner_owner_id="b", settled_at=date(2026, 9, 16)), bet("void", status="void")],
                                 {"a": "Alice", "b": "Bob"}, now, previous)
    assert result["active"][0]["amount_cents"] == 12550
    assert result["active"][0]["stake"] == "$125.50"
    assert result["active"][0]["side_a"] == "Alice"
    assert result["active"][0]["status"] == "open"
    assert result["resolved"][0]["winner"] == "Bob"
    assert result["resolved"][0]["new_since_previous_edition"] is True
    assert len(result["active"]) == len(result["resolved"]) == 1


def test_first_snapshot_does_not_present_old_settlement_as_this_weeks_result():
    # Mutation: call every existing settled bet newly settled when no earlier snapshot exists.
    from app.services.analyst_bets import build_bets_snapshot
    result = build_bets_snapshot([bet(status="settled", winner_owner_id="a", settled_at=date(2026, 9, 2))],
                                 {"a": "Alice", "b": "Bob"}, datetime(2026, 9, 17, tzinfo=timezone.utc), None)
    assert result["resolved"][0]["new_since_previous_edition"] is False


@pytest.mark.asyncio
async def test_database_snapshot_is_scoped_and_read_only(maker, monkeypatch):
    # Mutation: query all leagues/seasons, or settle a wager during recap generation.
    from app.db.models import SideBet
    from app.services import analyst_bets
    from sqlalchemy import select
    async with maker() as db:
        for id, league_id, season in [("ours", "test", 2026), ("other", "other", 2026), ("past", "test", 2025)]:
            db.add(SideBet(id=id, league_id=league_id, season=season, description="Higher finish", amount_cents=2500,
                           side_a_owner_id="a", side_b_owner_id="b", status="open", made_at=date(2026, 9, 1)))
        await db.commit()
    @asynccontextmanager
    async def scope():
        async with maker() as db:
            yield db
    monkeypatch.setattr(analyst_bets, "session_scope", scope)
    result = await analyst_bets.load_bets_snapshot("test", 2026,
        [SimpleNamespace(owner_id="a", owner_name="Alice"), SimpleNamespace(owner_id="b", owner_name="Bob")],
        datetime(2026, 9, 17, tzinfo=timezone.utc))
    assert [b["id"] for b in result["active"]] == ["ours"]
    async with maker() as db:
        rows = list((await db.execute(select(SideBet))).scalars())
        assert len(rows) == 3 and all(b.status == "open" and b.winner_owner_id is None for b in rows)


@pytest.mark.asyncio
async def test_ledger_failure_is_not_reported_as_no_bets(monkeypatch):
    # Mutation: silently substitute an empty successful snapshot on database error.
    from app.services import analyst_bets
    @asynccontextmanager
    async def broken():
        raise RuntimeError("database unavailable")
        yield
    monkeypatch.setattr(analyst_bets, "session_scope", broken)
    result = await analyst_bets.load_bets_snapshot("test", 2026, [], datetime.now(timezone.utc))
    assert result["available"] is False
    assert "active" not in result
