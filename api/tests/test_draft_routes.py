"""Route-level tests for the draft board endpoints.

Follows the pattern in test_leaderboard.py: seed a ``ChainCacheEntry`` into a
tmp cache dir, patch the route module's ``_cache_dir`` indirection point to
point at it, and hit the route through the authenticated `client` fixture.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.chain_cache import ChainCache
from tests.helpers import minimal_chain_cache_entry


def _pick(season: int, drafter: str = "u1") -> dict:
    return {
        "player_id": f"p{season}", "full_name": f"Player {season}",
        "position": "RB", "drafter_id": drafter, "round": 1, "slot": 1,
        "picks_in_round": 12, "pick_no": 1, "draft_season": season,
        "production_total": 0.0,
    }


def _seed(cache_dir: Path, league_id: str = "L1") -> None:
    entry = minimal_chain_cache_entry(
        league_id=league_id,
        drafted_picks=[_pick(2024), _pick(2025), _pick(2023)],
        owners={"u1": {"owner_name": "Alice"}},
    )
    ChainCache(cache_dir=cache_dir).write(league_id, entry)


def test_draft_seasons_lists_newest_first(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.draft._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L1/draft/seasons")
    assert resp.status_code == 200
    seasons = resp.json()["seasons"]
    assert seasons == sorted(seasons, reverse=True)
    assert seasons == [2025, 2024, 2023]


def test_draft_seasons_409s_on_a_cold_cache(client, tmp_path):
    # Same cold-start contract as every other dashboard endpoint.
    with patch("app.routes.draft._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_unseen/draft/seasons")
    assert resp.status_code == 409
    assert "cold" in resp.json()["detail"].lower()
