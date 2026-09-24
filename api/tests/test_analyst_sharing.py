import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.deps import get_cache_dir
from app.services.analyst_store import AnalystStore


def seed():
    data = dict(season=2026, week=1, league_name="Test League", generated_at="2026-09-17T12:00:00Z",
                model="test", markdown="Public recap with a $25 bet.", facts={"private": "hidden"}, lore="Private lore",
                sources=[{"publisher": "RotoBaller", "title": "Injury report", "published_at": "2026-09-16T12:00:00Z",
                          "url": "https://www.rotoballer.com/player-news/example/1", "text": "Private source body"},
                         {"publisher": "Example", "title": "Unsafe URL", "url": "javascript:alert(1)"}],
                context_note="Partial news coverage.")
    AnalystStore(get_cache_dir()).save("test", data)
    return data


def test_public_link_is_limited_revocable_and_tracks_corrections(client):
    # Mutation: leak the full archive, keep revoked links alive, or pin stale prose.
    data = seed()
    url = "/api/league/test/analyst/2026/1/share"
    created = client.post(url)
    assert created.status_code == 200
    token = created.json()["token"]
    assert len(token) >= 43
    assert client.post(url).json()["token"] == token
    # Remove the test auth bypass: the actual public route must work anonymously.
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    try:
        with TestClient(app) as anonymous:
            response = anonymous.get(f"/api/public/analyst/{token}")
            assert response.status_code == 200
            assert "no-store" in response.headers["cache-control"]
            assert set(response.json()) == {"season", "week", "league_name", "generated_at", "markdown", "revision", "correction_note", "sources", "context_note"}
            assert response.json()["sources"][0]["url"].startswith("https://www.rotoballer.com/")
            assert response.json()["sources"][1]["url"] is None
            assert "Private source body" not in response.text
            assert response.json()["context_note"] == "Partial news coverage."
            assert anonymous.get("/api/league/test/analyst").status_code == 401
            assert anonymous.post(url).status_code == 401
            assert anonymous.delete(url).status_code == 401
            AnalystStore(get_cache_dir()).save_correction("test", {**data, "markdown": "Corrected recap"}, "Fixed score")
            assert anonymous.get(f"/api/public/analyst/{token}").json()["markdown"] == "Corrected recap"
    finally:
        app.dependency_overrides.update(overrides)
    assert client.delete(url).status_code == 200
    assert client.get(f"/api/public/analyst/{token}").status_code == 404
    assert client.post(url).json()["token"] != token


def test_cannot_share_unpublished_edition_or_guess_token(client):
    # Mutation: create a public capability for an absent edition or accept guessed IDs.
    assert client.post("/api/league/test/analyst/2026/1/share").status_code == 404
    assert client.get("/api/public/analyst/guess").status_code == 404
