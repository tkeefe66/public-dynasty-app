from types import SimpleNamespace

import pytest
from app.services.analyst_store import AnalystEdition, AnalystStore
from app.services.generation.publication import project_analyst
from app.services.generation.store import Held, digest, dump


def row(payload, revision):
    data = AnalystEdition.model_validate({**payload, "revision": revision}).model_dump()
    return SimpleNamespace(league_id="123", revision=revision, payload_json=dump(data), digest=digest(data))


def edition():
    return {"season": 2026, "week": 1, "league_name": "Synthetic", "generated_at": "2026-09-10T00:00:00Z",
            "model": "verified-results-v1", "edition_type": "results", "markdown": "Original.", "facts": {}}


def test_archive_projection_replays_same_revision_without_overwriting_original(tmp_path):
    store = AnalystStore(tmp_path)
    original = row(edition(), 1)
    store.save("123", edition())
    original_path = store.edition_path("123", 2026, 1)
    before = original_path.read_bytes()
    revision = row({**edition(), "edition_type": "roast", "markdown": "Reviewed.",
                    "correction_note": "Approved correction"}, 2)
    project_analyst(tmp_path, revision, original)
    project_analyst(tmp_path, revision, original)
    assert original_path.read_bytes() == before
    assert len(list((original_path.parent / "revisions" / original_path.stem).glob("*.json"))) == 1
    assert store.editions("123")[0]["markdown"] == "Reviewed."


def test_old_generation_cannot_overwrite_newer_owner_correction(tmp_path):
    store = AnalystStore(tmp_path)
    store.save("123", edition())
    original = row(edition(), 1)
    store.save_correction("123", {**edition(), "markdown": "Owner's correction."}, "New evidence")
    stale = row({**edition(), "markdown": "Stale generated copy.", "correction_note": "Old evidence"}, 2)
    with pytest.raises(Held, match="archive_revision_conflict"):
        project_analyst(tmp_path, stale, original)
    assert store.editions("123")[0]["markdown"] == "Owner's correction."
