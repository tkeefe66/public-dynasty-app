from __future__ import annotations

import pytest

from app.services.profile_store import ProfileStore


@pytest.fixture
def store(tmp_path):
    return ProfileStore(cache_dir=tmp_path)


def test_read_missing_returns_empty(store):
    assert store.read("L1") == {}


def test_upsert_then_read_roundtrip(store):
    profile = {
        "win_name": "Morgan",
        "loss_name": "Finley",
        "archetype": "The Planner",
        "rivals": ["u_joey", "u_amir"],
        "roast": "always checking the waiver wire",
    }
    store.upsert("L1", "u_mike", profile)
    got = store.read("L1")
    assert got == {"u_mike": profile}


def test_upsert_returns_all_profiles(store):
    store.upsert("L1", "u_mike", {"win_name": "Morgan"})
    all_profiles = store.upsert("L1", "u_joey", {"win_name": "Drew"})
    assert set(all_profiles) == {"u_mike", "u_joey"}


def test_upsert_overwrites_same_owner(store):
    store.upsert("L1", "u_mike", {"win_name": "Morgan", "roast": "old"})
    store.upsert("L1", "u_mike", {"win_name": "Morgan", "roast": "new"})
    got = store.read("L1")
    assert got["u_mike"]["roast"] == "new"


def test_profiles_are_per_league(store):
    store.upsert("L1", "u_mike", {"win_name": "Morgan"})
    store.upsert("L2", "u_joey", {"win_name": "Drew"})
    assert set(store.read("L1")) == {"u_mike"}
    assert set(store.read("L2")) == {"u_joey"}


def test_no_ttl_old_file_still_read(store, tmp_path):
    import json
    import os
    import time

    store.upsert("L1", "u_mike", {"win_name": "Morgan"})
    path = tmp_path / "profiles_L1.json"
    old = time.time() - 365 * 24 * 3600
    os.utime(path, (old, old))
    # Unlike ChainCache, profiles never expire — this is user data.
    assert store.read("L1") == {"u_mike": {"win_name": "Morgan"}}
    # sanity: file is what we expect
    assert json.loads(path.read_text()) == {"u_mike": {"win_name": "Morgan"}}
