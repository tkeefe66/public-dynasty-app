"""Owner format evidence supplements missing Yahoo flags without replacing identity."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from app.auth.deps import get_current_user, require_admin
from app.db.models import LeagueMembership, User, YahooConnection, YahooLeagueGrant
from app.db.session import get_db
from app.services.generation.models import (
    GenerationAudit,
    LeagueSeason,
    LeagueSeries,
    stamp,
)
from app.services.generation.registry import register_entry, set_series
from app.services.generation.store import dump
from sqlalchemy import delete, select

from sleeper_dynasty.api.yahoo import YahooAdapter
from sleeper_dynasty.engine.capabilities import (
    capabilities_to_dict,
    derive_capabilities,
)

LEAGUE = "470.l.100000001"


async def provider_entry(*, format=None, league_id=LEAGUE, season=2026):
    # Captured anonymized Yahoo settings envelope, with just the absent format
    # flags removed to reproduce the production omission. All parsing stays real.
    path = Path(__file__).parents[2] / "tests/fixtures/yahoo/league_settings.json"
    payload = json.loads(path.read_text())
    meta, settings_node = payload["fantasy_content"]["league"]
    meta.update(league_key=league_id, season=str(season))
    settings = settings_node["settings"][0]
    settings.pop("is_keeper_league", None)
    settings.pop("uses_roster_import", None)
    if format:
        settings["is_keeper_league"] = "1" if format == "keeper" else "0"
        settings["uses_roster_import"] = "0"
    adapter = YahooAdapter("synthetic-token", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    try:
        league, _ = await adapter.get_league(league_id)
    finally:
        await adapter.close()
    return SimpleNamespace(league_id=league_id,
        chain=[{"league_id": league_id, "season": season, "format_verified": league.format_verified}],
        capabilities=capabilities_to_dict(derive_capabilities(league,
            chain_length=2, observed_pick_assets=False)),
        league_name_by_id={league_id: league.name}, league_season_by_id={league_id: season},
        generation_period={"season": season, "week": 6})


@pytest.fixture
def format_db(app, maker):
    async def seed():
        async with maker.begin() as db:
            row = await register_entry(db, await provider_entry(), verified=True)
            sid = row.series_id
            db.add(User(id="owner", google_sub="owner", email="owner@test.local", is_admin=True))
            db.add(LeagueMembership(user_id="owner", league_id=LEAGUE))
            db.add(YahooConnection(user_id="owner", generation="connection", status="connected",
                sealed_tokens="unused", expires_at=stamp() + 3600))
            db.add(YahooLeagueGrant(user_id="owner", league_id=LEAGUE, generation="connection",
                expires_at=stamp() + 300))
        return sid
    sid = asyncio.run(seed())

    async def isolated():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = isolated
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="owner", is_admin=True)
    yield maker, sid
    app.dependency_overrides.pop(get_db, None)


def confirm(client, sid, **changes):
    return client.post(f"/api/admin/generation/leagues/{sid}/format-confirmation", json={
        "expected_revision": 1, "league_id": LEAGUE, "format": "keeper",
        "reason": "Owner confirms this season uses keepers", **changes})


@pytest.mark.parametrize("format", ["redraft", "keeper"])
def test_current_yahoo_format_confirmation_is_audited_without_activation(client, format_db, format):
    # Mutation: treat owner evidence as provider verified or activate automatic generation as a side effect.
    maker, sid = format_db
    response = confirm(client, sid, format=format)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2
    async def check():
        async with maker() as db:
            row = await db.get(LeagueSeason, LEAGUE)
            evidence, caps = json.loads(row.evidence_json), json.loads(row.capabilities_json)
            assert evidence["source"] == "provider_history"
            assert evidence["chain"] == [LEAGUE]
            assert evidence["format_verified"] is False
            confirmation = evidence["owner_format_confirmation"]
            assert confirmation["format"] == format and confirmation["actor_id"] == "owner"
            assert confirmation["league_id"] == LEAGUE and confirmation["season"] == 2026
            assert confirmation["status"] == "confirmed" and confirmation["confirmed_at"] > 0
            assert caps == {"format": format, "future_picks": False,
                "roster_continuity": format == "keeper", "multiyear_history": True}
            assert row.verified_at > 0
            series = await db.get(LeagueSeries, sid)
            assert (series.lifecycle, series.hold, series.activated_at) == (
                "pending_verification", "activation_required", 0)
            record = await db.scalar(select(GenerationAudit))
            assert record.action == "season_format_confirmed" and record.actor_id == "owner"
            assert json.loads(record.after_json)["owner_format_confirmation"] == confirmation
    asyncio.run(check())
    listed = client.get("/api/admin/generation/leagues").json()["records"][0]["seasons"][0]
    assert listed["format_verification_source"] == "owner"
    assert listed["format_confirmation_available"] is False
    assert confirm(client, sid).status_code == 409
    assert confirm(client, sid, expected_revision=2, format="redraft").status_code == 422


def test_confirmation_survives_same_season_provider_refresh_and_allows_separate_activation(client, format_db):
    # Mutation: discard explicit owner evidence whenever Yahoo again omits its format flags.
    maker, sid = format_db
    assert confirm(client, sid).status_code == 200
    async def refresh():
        async with maker.begin() as db:
            before = json.loads((await db.get(LeagueSeason, LEAGUE)).evidence_json)
            row = await register_entry(db, await provider_entry(), verified=True)
            after = json.loads(row.evidence_json)
            assert after["owner_format_confirmation"] == before["owner_format_confirmation"]
            assert row.verified_at > 0 and after["format_verified"] is False
            assert json.loads(row.capabilities_json)["format"] == "keeper"
            await set_series(db, sid, expected_revision=2, lifecycle="active", profile="keeper",
                actor="owner", reason="Separate activation", activate=True)
    asyncio.run(refresh())


def test_confirmation_does_not_inherit_into_next_season(client, format_db):
    # Mutation: reuse a series-wide format override as evidence for every renewal season.
    maker, sid = format_db
    assert confirm(client, sid).status_code == 200
    async def renew():
        entry = await provider_entry(league_id="480.l.100000003", season=2027)
        entry.chain.append({"league_id": LEAGUE, "season": 2026, "format_verified": False})
        async with maker.begin() as db:
            row = await register_entry(db, entry, verified=True)
            assert row.series_id == sid and row.verified_at == 0
            assert "owner_format_confirmation" not in json.loads(row.evidence_json)
    asyncio.run(renew())
    assert confirm(client, sid, expected_revision=2).status_code == 409


@pytest.mark.parametrize("existing_hold", ["", "owner_paused", "identity_conflict"])
def test_conflicting_provider_format_invalidates_confirmation_and_preserves_stronger_holds(
        client, format_db, existing_hold):
    # Mutation: silently prefer owner format over contradictory explicit provider evidence.
    maker, sid = format_db
    assert confirm(client, sid).status_code == 200
    async def conflict():
        async with maker.begin() as db:
            series = await db.get(LeagueSeries, sid)
            series.hold = existing_hold
            row = await register_entry(db, await provider_entry(format="redraft"), verified=True)
            evidence = json.loads(row.evidence_json)
            assert row.verified_at == 0
            assert evidence["owner_format_confirmation"]["status"] == "conflict"
            assert evidence["owner_format_confirmation"]["provider_format"] == "redraft"
            assert series.hold == (existing_hold or "format_conflict")
    asyncio.run(conflict())
    listed = client.get("/api/admin/generation/leagues").json()["records"][0]["seasons"][0]
    assert listed["format_confirmation_available"] is False
    assert listed["format_verification_source"] is None


@pytest.mark.parametrize("invalid", ["legacy", "unknown_caps", "missing_identity", "identity_conflict",
    "provider_format", "not_member", "not_admin", "missing_actor", "expired_grant", "changed_grant"])
def test_confirmation_cannot_bypass_identity_capability_or_actor_gates(client, format_db, invalid):
    # Mutation: use owner input to bless unverifiable data or bypass current private-league authorization.
    maker, sid = format_db
    async def invalidate():
        async with maker.begin() as db:
            row = await db.get(LeagueSeason, LEAGUE)
            evidence = json.loads(row.evidence_json)
            if invalid == "legacy":
                evidence["source"] = "legacy_cache"
            elif invalid == "missing_identity":
                evidence["chain"] = []
            elif invalid == "provider_format":
                evidence["format_verified"] = True
            elif invalid == "unknown_caps":
                row.capabilities_json = dump({"format": "redraft"})
            elif invalid == "identity_conflict":
                (await db.get(LeagueSeries, sid)).hold = "identity_conflict"
            elif invalid == "not_member":
                await db.execute(delete(LeagueMembership))
            elif invalid == "not_admin":
                (await db.get(User, "owner")).is_admin = False
            elif invalid == "missing_actor":
                await db.execute(delete(User))
            else:
                grant = await db.get(YahooLeagueGrant, ("owner", LEAGUE))
                if invalid == "expired_grant":
                    grant.expires_at = stamp() - 1
                else:
                    grant.generation = "replaced"
            row.evidence_json = dump(evidence)
    asyncio.run(invalidate())
    response = confirm(client, sid)
    assert response.status_code in (409, 422), response.text
    async def unchanged():
        async with maker() as db:
            assert not (await db.scalars(select(GenerationAudit))).all()
            assert (await db.get(LeagueSeries, sid)).revision == 1
    asyncio.run(unchanged())


def test_format_confirmation_route_requires_admin_and_rejects_unsupported_format(client, app, format_db):
    # Mutation: expose format mutation outside the owner-only route or accept arbitrary formats.
    _, sid = format_db
    assert confirm(client, sid, format="dynasty").status_code == 422
    assert confirm(client, sid, reason=" ").status_code == 422
    app.dependency_overrides.pop(require_admin)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="member", is_admin=False)
    assert confirm(client, sid).status_code == 403


@pytest.mark.parametrize("invalid", ["legacy", "unknown_caps"])
def test_owner_confirmation_never_rescues_unverified_refresh(client, format_db, invalid):
    # Mutation: keep permission from owner evidence after provider identity or capability evidence is lost.
    maker, sid = format_db
    assert confirm(client, sid).status_code == 200
    async def refresh():
        entry = await provider_entry()
        if invalid == "unknown_caps":
            entry.capabilities = {}
        async with maker.begin() as db:
            row = await register_entry(db, entry, verified=invalid != "legacy")
            assert row.verified_at == 0
            assert json.loads(row.evidence_json)["owner_format_confirmation"]["status"] == "confirmed"
    asyncio.run(refresh())
    listed = client.get("/api/admin/generation/leagues").json()["records"][0]["seasons"][0]
    assert listed["format_confirmation_available"] is False
    assert listed["format_verification_source"] is None


def test_matching_provider_evidence_retains_owner_history_and_uses_provider_label(client, format_db):
    # Mutation: label all future format evidence owner-confirmed even when Yahoo explicitly verifies it.
    maker, sid = format_db
    assert confirm(client, sid).status_code == 200
    async def refresh():
        async with maker.begin() as db:
            row = await register_entry(db, await provider_entry(format="keeper"), verified=True)
            assert row.verified_at > 0
            evidence = json.loads(row.evidence_json)
            assert evidence["format_verified"] is True
            assert evidence["owner_format_confirmation"]["status"] == "confirmed"
    asyncio.run(refresh())
    listed = client.get("/api/admin/generation/leagues").json()["records"][0]["seasons"][0]
    assert listed["format_verification_source"] == "provider"
    assert listed["format_confirmation_available"] is False


def test_provider_conflict_cannot_clear_on_next_missing_format_refresh(client, format_db):
    # Mutation: revive owner authorization after conflicting provider evidence disappears on a later read.
    maker, sid = format_db
    assert confirm(client, sid).status_code == 200
    async def refresh():
        async with maker.begin() as db:
            await register_entry(db, await provider_entry(format="redraft"), verified=True)
        async with maker.begin() as db:
            row = await register_entry(db, await provider_entry(), verified=True)
            assert row.verified_at == 0
            assert json.loads(row.evidence_json)["owner_format_confirmation"]["status"] == "conflict"
    asyncio.run(refresh())
    assert confirm(client, sid, expected_revision=3).status_code == 422


@pytest.mark.parametrize("existing_hold", ["", "owner_paused", "format_conflict"])
def test_same_provider_key_with_different_season_cannot_reuse_confirmation(client, format_db, existing_hold):
    # Mutation: compare confirmation only with the stored year and ignore a changed incoming provider season.
    maker, sid = format_db
    assert confirm(client, sid).status_code == 200
    async def refresh():
        async with maker.begin() as db:
            (await db.get(LeagueSeries, sid)).hold = existing_hold
            row = await register_entry(db, await provider_entry(season=2027), verified=True)
            assert row.verified_at == 0
            evidence = json.loads(row.evidence_json)
            assert evidence["identity_conflict"] == "provider_season_changed"
            assert (await db.get(LeagueSeries, sid)).hold == (existing_hold or "identity_conflict")
        # Another provider refresh cannot silently erase the recorded identity conflict.
        async with maker.begin() as db:
            row = await register_entry(db, await provider_entry(format="keeper"), verified=True)
            assert row.verified_at == 0
    asyncio.run(refresh())
    listed = client.get("/api/admin/generation/leagues").json()["records"][0]["seasons"][0]
    assert listed["format_verification_source"] is None
    assert listed["format_confirmation_available"] is False
