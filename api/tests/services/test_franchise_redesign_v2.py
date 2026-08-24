"""Task 6: live_ratings scores the v2 tree (Results / Assets, no Skill)."""

from app.services.franchise_redesign import build_v2_pillars, live_ratings, model_for

from ._grader_fixtures import dynasty_entry, redraft_entry  # noqa: F401 (fixtures)


def test_dynasty_selects_the_v2_dynasty_tree(dynasty_entry):
    assert model_for(dynasty_entry) == "v2_dynasty"
    rows = live_ratings(dynasty_entry)
    row = next(iter(rows.values()))
    assert row["model"] == "v2_dynasty"
    assert set(row["pillars"]) == {"results", "assets"}


def test_redraft_gets_results_only(redraft_entry):
    rows = live_ratings(redraft_entry)
    row = next(iter(rows.values()))
    assert set(row["pillars"]) == {"results"}


def test_pillars_read_the_persisted_signal_dicts(dynasty_entry):
    pillars = build_v2_pillars(dynasty_entry)
    uid = next(iter(dynasty_entry.owners))
    assert "expected_wins" in pillars[uid]["results"]
    assert "young_core_share" in pillars[uid]["assets"]


def test_no_skill_pillar_survives(dynasty_entry):
    rows = live_ratings(dynasty_entry)
    for row in rows.values():
        assert "skill" not in row["pillars"]
