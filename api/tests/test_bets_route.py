"""Side-bets route tests: CRUD happy paths, validation, PATCH state rules,
summary math. Auth deps are overridden by conftest's client fixture; a real
SQLite DB is wired in via a get_db override (same shape as test_events_route)."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import User
from app.db.session import get_db


@pytest.fixture()
def db_maker(app, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bets.db'}")

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            # conftest's FAKE_USER id — satisfies the audit FKs.
            session.add(User(id="test-user", google_sub="g-test", email="t@test.local"))
            await session.commit()

    asyncio.run(_create())
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield maker
    finally:
        asyncio.run(engine.dispose())


def _make_bet(client, **overrides):
    body = {
        "description": "Tom finishes above Mike in the regular season",
        "amount_cents": 50000,
        "season": 2026,
        "side_a_owner_id": "u_tom",
        "side_b_owner_id": "u_mike",
        "made_at": "2026-07-15",
    }
    body.update(overrides)
    return client.post("/api/league/L1/bets", json=body)


def test_create_and_list(client, db_maker):
    resp = _make_bet(client)
    assert resp.status_code == 201
    bet = resp.json()
    assert bet["status"] == "open"
    # Cold chain cache degrades to raw ids — never a 409 on bets endpoints.
    assert bet["side_a"] == {
        "user_id": "u_tom",
        "owner_name": "u_tom",
        "team_name": None,
        "franchise_name": None,
        "avatar_url": None,
        "membership_status": "unverified",
        "last_active_season": None,
    }

    listed = client.get("/api/league/L1/bets").json()
    assert [b["id"] for b in listed["bets"]] == [bet["id"]]


def test_validation_rejections(client, db_maker):
    assert _make_bet(client, side_b_owner_id="u_tom").status_code == 422
    assert _make_bet(client, amount_cents=0).status_code == 422
    assert _make_bet(client, description="   ").status_code == 422


@pytest.mark.parametrize("format", ["redraft", "keeper", "dynasty"])
def test_linked_former_owner_bets_keep_settlement_ids_and_merge_totals(client, db_maker, monkeypatch, format):
    # Mutation: canonicalize bet sides but leave the stored winner raw, or split aliased totals.
    from tests.test_owner_membership import entry_for
    from app.routes import bets
    entry = entry_for(format)
    entry.owner_aliases = {"old-former": "former"}
    monkeypatch.setattr(bets.ChainCache, "read", lambda *args, **kwargs: entry)
    for uid in ["old-former", "former"]:
        made = _make_bet(client, side_a_owner_id=uid, side_b_owner_id="returning", season=2023).json()
        # The UI settles using the side id it received. It must still match the persisted bet.
        settled = client.patch(f"/api/league/L1/bets/{made['id']}",
                               json={"status": "settled", "winner_owner_id": made["side_a"]["user_id"]})
        assert settled.status_code == 200
        view = settled.json()
        assert view["winner_owner_id"] == view["side_a"]["user_id"]
        assert view["side_a"]["membership_status"] == "former"
    summary = client.get("/api/league/L1/bets/summary").json()["owners"]
    assert len(summary) == 2
    assert summary[0]["owner"]["user_id"] == "former"
    assert summary[0]["net_cents"] == 100000
    # Profile-level bet history must include both historical and canonical IDs.
    assert len(client.get("/api/league/L1/bets?owner_id=former").json()["bets"]) == 2


@pytest.mark.parametrize("format", ["redraft", "keeper", "dynasty"])
def test_former_bet_history_and_money_survive_departure(client, db_maker, monkeypatch, format):
    # Mutation: remove departed participants from bet lists/summary, or lose their status.
    from tests.test_owner_membership import entry_for
    from app.routes import bets
    entry = entry_for(format)
    monkeypatch.setattr(bets.ChainCache, "read", lambda *args, **kwargs: entry)
    made = _make_bet(client, side_a_owner_id="former", side_b_owner_id="returning", season=2023).json()
    settled = client.patch(f"/api/league/L1/bets/{made['id']}",
                          json={"status": "settled", "winner_owner_id": "former"})
    assert settled.status_code == 200
    listed = client.get("/api/league/L1/bets?season=2023").json()["bets"]
    assert listed[0]["side_a"]["membership_status"] == "former"
    assert listed[0]["side_a"]["last_active_season"] == 2023
    summary = client.get("/api/league/L1/bets/summary?season=2023").json()["owners"]
    assert len(summary) == 2
    assert summary[0]["owner"]["membership_status"] == "former"
    assert summary[0]["net_cents"] == 50000
    assert sum(o["net_cents"] for o in summary) == 0


def test_settle_push_void_and_summary(client, db_maker):
    won = _make_bet(client).json()["id"]
    pushed = _make_bet(client, amount_cents=2000).json()["id"]
    voided = _make_bet(client, amount_cents=3000).json()["id"]
    open_id = _make_bet(client, amount_cents=1000).json()["id"]

    r = client.patch(
        f"/api/league/L1/bets/{won}",
        json={"status": "settled", "winner_owner_id": "u_tom"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "settled"
    assert r.json()["settled_at"] is not None
    assert client.patch(
        f"/api/league/L1/bets/{pushed}", json={"status": "push"}
    ).status_code == 200
    assert client.patch(
        f"/api/league/L1/bets/{voided}", json={"status": "void"}
    ).status_code == 200

    # Void keeps history: all four bets still listed.
    assert len(client.get("/api/league/L1/bets").json()["bets"]) == 4

    summary = client.get("/api/league/L1/bets/summary").json()
    by_id = {o["owner"]["user_id"]: o for o in summary["owners"]}
    assert by_id["u_tom"]["net_cents"] == 50000
    assert by_id["u_tom"]["won"] == 1
    assert by_id["u_tom"]["cents_at_stake"] == 1000
    assert by_id["u_mike"]["net_cents"] == -50000
    assert by_id["u_mike"]["pushed"] == 1
    # Sorted by net desc.
    assert summary["owners"][0]["owner"]["user_id"] == "u_tom"
    _ = open_id


def test_patch_state_rules(client, db_maker):
    bet_id = _make_bet(client).json()["id"]

    # Winner without a status change is rejected.
    assert client.patch(
        f"/api/league/L1/bets/{bet_id}", json={"winner_owner_id": "u_tom"}
    ).status_code == 422
    # Winner must be a side.
    assert client.patch(
        f"/api/league/L1/bets/{bet_id}",
        json={"status": "settled", "winner_owner_id": "u_zzz"},
    ).status_code == 422

    client.patch(
        f"/api/league/L1/bets/{bet_id}",
        json={"status": "settled", "winner_owner_id": "u_tom"},
    )
    # Settled bets can't be field-edited...
    assert client.patch(
        f"/api/league/L1/bets/{bet_id}", json={"description": "edited"}
    ).status_code == 422
    # ...but can be reverted to open (clears winner/settled), then edited.
    reverted = client.patch(f"/api/league/L1/bets/{bet_id}", json={"status": "open"})
    assert reverted.status_code == 200
    assert reverted.json()["winner_owner_id"] is None
    assert reverted.json()["settled_at"] is None
    assert client.patch(
        f"/api/league/L1/bets/{bet_id}", json={"description": "edited"}
    ).status_code == 200


def test_unknown_and_cross_league_bet_404(client, db_maker):
    bet_id = _make_bet(client).json()["id"]
    assert client.patch(
        "/api/league/L1/bets/missing", json={"status": "void"}
    ).status_code == 404
    assert client.patch(
        f"/api/league/OTHER/bets/{bet_id}", json={"status": "void"}
    ).status_code == 404
