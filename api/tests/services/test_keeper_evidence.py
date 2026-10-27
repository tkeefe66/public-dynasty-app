# ruff: noqa: F811 -- pytest fixture injection

import pytest
from app.services.keeper_evidence import SeasonFormatStore, detect_keepers

from ._grader_fixtures import redraft_entry  # noqa: F401


def test_overlap_is_candidate_not_proof():
    # Mutation: classify any returning player as a confirmed keeper.
    report = detect_keepers(
        previous={"u": ["p"]},
        opening={"u": ["p"]},
        draft=[{"owner": "u", "player": "p"}],
    )
    assert report["format"] is None
    assert report["candidates"] == [
        {"owner": "u", "player": "p", "drafted_again": True}
    ]
    assert report["confirmed"] == []


def test_marker_proves_keeper_not_maximum_allowance():
    # Mutation: use observed keeper count as the league's maximum allowance.
    report = detect_keepers(
        previous={},
        opening={"u": ["p"]},
        draft=[{"owner": "u", "player": "p", "keeper": True}],
    )
    assert report["format"] == "keeper"
    assert report["observed_max"] == 1
    assert report["keeper_limit"] is None


def test_false_markers_do_not_prove_redraft_and_attestation_wins():
    # Mutation: false keeper markers override a member's verified format evidence.
    assert (
        detect_keepers(
            previous={},
            opening={},
            draft=[{"owner": "u", "player": "p", "keeper": False}],
        )["format"]
        is None
    )
    assert (
        detect_keepers(previous={}, opening={}, draft=[], attested_format="keeper")[
            "format"
        ]
        == "keeper"
    )


def test_format_evidence_survives_roundtrip_and_is_season_bound(tmp_path):
    # Mutation: apply a format record to another year or accept tampered contents.
    store = SeasonFormatStore(tmp_path)
    store.save(
        "league",
        2024,
        {
            "format": "keeper",
            "basis": "member confirmation",
            "evidence_sha256": "a" * 64,
        },
    )
    assert store.load("league", 2024)["format"] == "keeper"
    assert store.load("league", 2023) is None
    path = store.path("league", 2024)
    path.write_text(path.read_text().replace("keeper", "redraft"))
    with pytest.raises(ValueError, match="hash"):
        store.load("league", 2024)


def test_verified_keeper_format_prevents_results_only_redraft_rating(
    tmp_path, redraft_entry
):
    # Mutation: ignore persisted format evidence and retain the provider's redraft fallback.
    from app.services.season_ratings import build_season_rating_inputs

    from .test_season_rating_scope import _historical_support

    support = _historical_support(redraft_entry)
    store = SeasonFormatStore(tmp_path)
    old_id = next(
        lid for lid, year in redraft_entry.league_season_by_id.items() if year == 2024
    )
    store.save(
        old_id,
        2024,
        {
            "format": "keeper",
            "basis": "member confirmation",
            "evidence_sha256": "b" * 64,
        },
    )
    snapshot = build_season_rating_inputs(redraft_entry, support, format_store=store)[
        "2024"
    ]
    assert snapshot["format"] == "keeper"
    assert snapshot["status"] == "unavailable"
    assert "asset" in snapshot["reason"]

    # Losing the reviewed record must not re-enable the provider's redraft fallback.
    recovered = build_season_rating_inputs(
        redraft_entry, support, prior_snapshots={"2024": snapshot}
    )["2024"]
    assert recovered["status"] == "unavailable"
    assert recovered["requires_format_evidence"]
    assert "format evidence is missing" in recovered["reason"]


def test_format_corruption_preserves_results_requirement(tmp_path, redraft_entry):
    from app.services.season_ratings import build_season_rating_inputs

    from .test_season_rating_scope import _historical_support

    support = _historical_support(redraft_entry)
    store = SeasonFormatStore(tmp_path)
    old_id = next(
        lid for lid, year in redraft_entry.league_season_by_id.items() if year == 2024
    )
    store.save(
        old_id,
        2024,
        {"format": "redraft", "basis": "provider", "evidence_sha256": "c" * 64},
    )
    original = store.path(old_id, 2024).read_text()
    store.path(old_id, 2024).write_text("{}")
    failed = build_season_rating_inputs(
        redraft_entry,
        support,
        format_store=store,
        prior_snapshots={"2024": {"requires_results_coverage": True}},
    )["2024"]
    assert failed["requires_results_coverage"]
    assert failed["status"] == "unavailable"
    store.path(old_id, 2024).write_text(original)
    recovered = build_season_rating_inputs(
        redraft_entry, support, format_store=store, prior_snapshots={"2024": failed}
    )["2024"]
    assert recovered["requires_results_coverage"]
    assert recovered["status"] == "unavailable"
    assert "Results coverage" in recovered["reason"]
