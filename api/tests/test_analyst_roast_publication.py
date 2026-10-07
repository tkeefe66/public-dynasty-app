from app.services.analyst_shares import AnalystShares
from app.services.analyst_store import AnalystStore


def packet():
    return {"season": 2026, "week": 4, "league_name": "Synthetic",
            "generated_at": "2026-10-06T04:00:00Z", "model": "verified-results-v1",
            "edition_type": "results", "markdown": "Private results packet", "facts": {}}


def test_results_packet_is_private_until_roast_revision(tmp_path):
    store = AnalystStore(tmp_path)
    store.save("123", packet())
    original = store.edition_path("123", 2026, 4).read_bytes()
    assert store.published_editions("123") == []
    assert AnalystShares(tmp_path).create("123", 2026, 4) is None
    store.save_correction("123", {**packet(), "edition_type": "roast",
        "model": "test-model", "markdown": "Reviewed roast"}, "AI roast ready")
    assert store.published_editions("123")[0]["markdown"] == "Reviewed roast"
    assert store.published_editions("123")[0]["original_markdown"] is None
    assert AnalystShares(tmp_path).create("123", 2026, 4) is not None
    assert store.edition_path("123", 2026, 4).read_bytes() == original


def test_archive_route_hides_results_packets(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.routes.analyst.get_cache_dir", lambda: tmp_path)
    AnalystStore(tmp_path).save("123", packet())
    assert client.get("/api/league/123/analyst").json() == {"editions": []}


def test_existing_share_cannot_resolve_results_packet(tmp_path):
    shares = AnalystShares(tmp_path)
    shares.archive.save("123", {**packet(), "edition_type": "roast", "markdown": "Roast"})
    token = shares.create("123", 2026, 4)["token"]
    shares.archive.save_correction("123", packet(), "Legacy fallback fixture")
    assert shares.resolve(token) is None
