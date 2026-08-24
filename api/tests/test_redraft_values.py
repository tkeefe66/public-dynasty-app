from types import SimpleNamespace

import pytest

from app.services.grader_io import is_redraft_chain, pull_supporting_data
from app.services.league_raw_cache import LeagueRawCache
from sleeper_dynasty.models.league import League


def _league(fmt, season=2025):
    return League(
        league_id=f"L{season}", name="T", season=season, total_rosters=12,
        roster_positions=["QB"], scoring_settings={}, playoff_week_start=15,
        num_playoff_teams=6, status="in_season", format=fmt,
    )


def test_redraft_chain_detected():
    assert is_redraft_chain([_league("redraft")]) is True


def test_dynasty_chain_not_redraft():
    assert is_redraft_chain([_league("dynasty")]) is False


def test_keeper_chain_not_redraft():
    assert is_redraft_chain([_league("keeper")]) is False


def test_empty_chain_defaults_to_not_redraft():
    """Never demote to redraft pricing without positive evidence."""
    assert is_redraft_chain([]) is False


def test_uses_the_latest_season_in_the_chain():
    """A league that converted formats is judged by where it is now."""
    chain = [_league("dynasty", 2023), _league("redraft", 2025)]
    assert is_redraft_chain(chain) is True


# ---------------------------------------------------------------------------
# End-to-end precedence inversion: pull_supporting_data must actually route
# a redraft chain to FantasyCalc-only pricing, not just report True/False
# from the pure helper. A refactor that reintroduced the KTC fetch, or
# dropped the `continue`-skip in the fill loop, would pass every other test
# in this suite but silently reprice redraft trades with dynasty numbers.
# ---------------------------------------------------------------------------

class _FakeHTTPResp:
    def raise_for_status(self):
        pass

    def json(self):
        return []


class _FakeHTTPClient:
    async def get(self, url):
        return _FakeHTTPResp()


class _MinimalClient:
    """Enough surface for pull_supporting_data's matchup-bundle walk. No
    matchup data is ever returned, so grading/production logic never runs —
    only the value-sourcing precedence under test."""

    async def get_raw_matchups(self, lid, week):
        return []

    async def get_rosters(self, lid):
        return [SimpleNamespace(roster_id=1, owner_id="u1")]

    async def get_users(self, lid):
        return {"u1": {"display_name": "Owner1", "team_name": None, "avatar_url": None}}

    async def get_winners_bracket(self, lid):
        return []

    async def get_losers_bracket(self, lid):
        return []

    async def get_players(self):
        return {"p1": {"full_name": "Player One", "position": "RB"}}


class _FakeSnapshotStore:
    def __init__(self):
        self.captures = []

    def capture(self, values, d):
        self.captures.append((values, d))


@pytest.mark.asyncio
async def test_redraft_chain_sources_fantasycalc_only(monkeypatch, tmp_path):
    import app.services.grader_io as mod
    from sleeper_dynasty.models.player import KTCValue

    ktc_calls: list = []

    async def _ktc():
        ktc_calls.append(True)
        return {
            "someone else": KTCValue(
                name="Someone Else", normalized_name="someone else",
                position="RB", superflex_value=9000, one_qb_value=9000,
            )
        }

    fc_calls: list = []

    async def _fc(*, dynasty=True):
        fc_calls.append(dynasty)
        return {"p1": {"superflex": 4000, "one_qb": 3500}}

    monkeypatch.setattr(mod, "fetch_ktc_values", _ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _fc)

    store = _FakeSnapshotStore()
    chain = [_league("redraft")]
    out = await pull_supporting_data(
        _MinimalClient(), chain,
        players={"p1": {"full_name": "Player One", "position": "RB"}},
        league_cache=LeagueRawCache(cache_dir=tmp_path),
        snapshot_store=store,
    )

    assert ktc_calls == [], "KTC must never be called for a redraft chain"
    assert fc_calls == [False], "FantasyCalc must be fetched with dynasty=False"
    assert "p1" in out["ktc_by_player_id"], (
        "FantasyCalc values must land in the value map, not be skipped")
    assert out["ktc_by_player_id"]["p1"].superflex_value == 4000
    assert any("unvalued" in w for w in out["warnings"]), (
        "the thin-coverage warning must be surfaced")
    # Superseded contract. This used to assert `store.captures == []`, because
    # a redraft chain was handed no store at all. It now gets a *redraft-
    # namespaced* store and captures into it, so redraft price history accrues
    # forward. The safety property that assertion was really protecting — that
    # dynasty and redraft prices never mix — is now held by the namespace and
    # asserted directly in test_snapshot_namespacing.py.
    assert len(store.captures) == 1, "a redraft chain must accrue its own price history"
    captured, _when = store.captures[0]
    assert captured["p1"].superflex_value == 4000, (
        "the captured table must be the redraft values, never dynasty's")
    assert "someone else" not in captured, "no KTC row may reach a redraft snapshot"


@pytest.mark.asyncio
async def test_dynasty_chain_keeps_ktc_precedence(monkeypatch, tmp_path):
    """Mirror of the redraft test: confirms the old behavior is untouched."""
    import app.services.grader_io as mod
    from sleeper_dynasty.models.player import KTCValue

    ktc_calls: list = []

    async def _ktc():
        ktc_calls.append(True)
        return {
            "player one": KTCValue(
                name="Player One", normalized_name="player one",
                position="RB", superflex_value=9000, one_qb_value=8800,
            )
        }

    fc_calls: list = []

    async def _fc(*, dynasty=True):
        fc_calls.append(dynasty)
        return {"p1": {"superflex": 4000, "one_qb": 3500}}

    monkeypatch.setattr(mod, "fetch_ktc_values", _ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _fc)

    store = _FakeSnapshotStore()
    chain = [_league("dynasty")]
    out = await pull_supporting_data(
        _MinimalClient(), chain,
        players={"p1": {"full_name": "Player One", "position": "RB"}},
        league_cache=LeagueRawCache(cache_dir=tmp_path),
        snapshot_store=store,
    )

    assert ktc_calls == [True], "KTC must still be called for a dynasty chain"
    assert fc_calls == [True], "FantasyCalc must still be fetched with dynasty=True"
    # KTC wins for p1 (both sources rank it); FC value (4000) must NOT overwrite it.
    assert out["ktc_by_player_id"]["p1"].superflex_value == 9000
    assert not any("unvalued" in w for w in out["warnings"]), (
        "the redraft coverage warning must not appear for a dynasty chain")
    assert len(store.captures) == 1, "a dynasty chain must still write to the KTC snapshot store"
