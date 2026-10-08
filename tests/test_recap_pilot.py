"""Behavioral checks for the manual, single-league media pilot."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "recap_pilot.py"


def module():
    assert SCRIPT.exists(), "The pilot package builder has not been implemented"
    spec = importlib.util.spec_from_file_location("recap_pilot", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def create(tmp_path):
    mod = module()
    cache = tmp_path / "chain.json"
    cache.write_text(
        json.dumps(
            {
                "league_id": "test-league",
                "league_name_by_id": {
                    "test-league": mod.read(mod.ASSETS / "episode.template.json")[
                        "league_name"
                    ]
                },
                "league_season_by_id": {"test-league": 2026},
            }
        )
    )
    mod.initialize(cache, tmp_path / "pilot")
    return mod, tmp_path / "pilot"


def test_only_requested_league_can_initialize(tmp_path):
    # Mutation: removing the Dynasty Bitch identity check permits other leagues.
    mod = module()
    path = tmp_path / "chain.json"
    path.write_text(
        json.dumps(
            {
                "league_id": "other",
                "league_name_by_id": {"other": "Other league"},
                "league_season_by_id": {"other": 2026},
            }
        )
    )
    with pytest.raises(ValueError, match="Dynasty Bitch"):
        mod.initialize(path, tmp_path / "pilot")
    assert not (tmp_path / "pilot").exists()


def test_timeline_is_full_ninety_seconds_and_keeps_approved_line(tmp_path):
    # Mutation: dropping a scene or altering the approved character reference.
    mod, root = create(tmp_path)
    episode = mod.load_episode(root)
    assert episode["duration"] == 90
    assert episode["scenes"][0]["start"] == 0
    assert episode["scenes"][-1]["end"] == 90
    assert all(
        a["end"] == b["start"] for a, b in zip(episode["scenes"], episode["scenes"][1:])
    )
    assert "coach’s fucking fault" in mod.spoken_text(episode)
    assert 180 <= len(mod.spoken_text(episode).split()) <= 215


def test_quote_does_not_count_as_spend_and_unknown_is_not_zero(tmp_path):
    # Mutation: summing quotations as charges or replacing unknown charges with zero.
    mod, root = create(tmp_path)
    mod.quote(root, 4.5, "text2speech_v2", "test-voice", "preset")
    assert mod.cost_summary(root) == {
        "quoted_credits": 4.5,
        "known_charged_credits": 0,
        "unsettled_attempts": 0,
        "attempts": 0,
    }
    mod.reserve(root, "first", 5)
    summary = mod.cost_summary(root)
    assert summary["known_charged_credits"] == 0
    assert summary["unsettled_attempts"] == 1
    mod.settle(root, "first", "failed", None)
    assert mod.cost_summary(root)["unsettled_attempts"] == 1


def test_budget_and_unresolved_or_duplicate_attempt_block_retry(tmp_path):
    # Mutation: deleting any spend guard admits another manual paid request.
    mod, root = create(tmp_path)
    mod.quote(root, 4.5, "text2speech_v2", "test-voice", "preset")
    for cap in (0, 4, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            mod.reserve(root, "first", cap)
    mod.reserve(root, "first", 5)
    with pytest.raises(ValueError):
        mod.reserve(root, "second", 10)
    mod.settle(root, "first", "completed", 4.5)
    with pytest.raises(ValueError):
        mod.reserve(root, "first", 10)
    with pytest.raises(ValueError):
        mod.reserve(root, "second", 5)
    assert mod.cost_summary(root)["attempts"] == 1


def test_script_edit_invalidates_quote(tmp_path):
    # Mutation: not checking the script hash reuses a quote for different audio.
    mod, root = create(tmp_path)
    mod.quote(root, 2, "text2speech_v2", "test-voice", "preset")
    data = mod.load_episode(root)
    data["scenes"][0]["narration"] += " A revision."
    (root / "episode.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="script"):
        mod.reserve(root, "first", 5)


def test_changed_scope_cannot_build(tmp_path):
    # Mutation: trusting the manifest's scope bypasses the fixed local configuration.
    mod, root = create(tmp_path)
    data = mod.load_episode(root)
    data["league_id"] = "other"
    (root / "episode.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="league"):
        mod.build(root)


def test_init_never_overwrites_and_build_has_no_external_provider(tmp_path):
    # Mutation: allowing reinitialization erases the receipt ledger.
    mod, root = create(tmp_path)
    with pytest.raises(FileExistsError):
        mod.initialize(tmp_path / "chain.json", root)
    mod.build(root)
    text = (root / "preview" / "episode.js").read_text()
    assert "script_hash" in text
    assert "audio" in text
    assert "test-league" not in text  # no external identity needed by the static player
    assert (root / "preview" / "index.html").is_file()


def test_audio_requires_completed_current_script_and_cannot_silently_drift(tmp_path):
    # Mutation: importing an unresolved take or keeping it after script edits.
    mod, root = create(tmp_path)
    audio = tmp_path / "take.mp3"
    audio.write_bytes(b"synthetic-media-for-file-binding-test")
    mod.quote(root, 2, "text2speech_v2", "test-voice", "preset")
    mod.reserve(root, "first", 5)
    with pytest.raises(ValueError, match="completed"):
        mod.attach_audio(root, audio, "first")
    mod.settle(root, "first", "completed", 2, "test-job")
    mod.attach_audio(root, audio, "first")
    mod.build(root)
    assert (root / "preview" / "narration.mp3").read_bytes() == audio.read_bytes()
    episode = mod.load_episode(root)
    episode["scenes"][0]["narration"] += " Revised."
    (root / "episode.json").write_text(json.dumps(episode))
    with pytest.raises(ValueError, match="Narration"):
        mod.build(root)


def test_audio_bytes_and_timeline_are_validated(tmp_path):
    # Mutation: bypassing file digest or contiguous-timeline checks.
    mod, root = create(tmp_path)
    audio = tmp_path / "take.mp3"
    audio.write_bytes(b"original")
    mod.quote(root, 2, "text2speech_v2", "test-voice", "preset")
    mod.reserve(root, "first", 5)
    mod.settle(root, "first", "completed", 2)
    mod.attach_audio(root, audio, "first")
    (root / "narration.mp3").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Narration"):
        mod.build(root)
    episode = mod.load_episode(root)
    episode["scenes"][1]["start"] = 11
    (root / "episode.json").write_text(json.dumps(episode))
    with pytest.raises(ValueError, match="timeline"):
        mod.load_episode(root)


def test_media_ranges_support_seeking_and_suffix_requests():
    # Mutation: ignoring ranges makes the browser restart audio instead of seeking.
    mod = module()
    assert hasattr(mod, "range_bounds"), "Preview server must support media byte ranges"
    assert mod.range_bounds("bytes=20-39", 100) == (20, 39)
    assert mod.range_bounds("bytes=20-", 100) == (20, 99)
    assert mod.range_bounds("bytes=-10", 100) == (90, 99)
    assert mod.range_bounds("bytes=20-999", 100) == (20, 99)


def test_invalid_media_ranges_are_rejected():
    # Mutation: accepting an out-of-file range reports nonexistent audio bytes.
    mod = module()
    assert hasattr(mod, "range_bounds"), (
        "Preview server must validate media byte ranges"
    )
    for value in ("bytes=100-", "bytes=40-20", "bytes=-0", "bytes=", "items=0-1"):
        with pytest.raises(ValueError):
            mod.range_bounds(value, 100)
