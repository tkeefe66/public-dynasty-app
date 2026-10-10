"""Synthetic independent speech evidence; mutations must change spoken content."""
import pytest

from app.services.recap_video.audio import split_narration, verify_speech


def transcript(text):
    return {"text": text, "words": [{"word": w, "start": i * .2, "end": (i + 1) * .2,
        "probability": .99} for i, w in enumerate(text.split())]}


@pytest.mark.parametrize("wrong,issue", [
    ("Avery won by forty points. That is all.", "spoken_number_mismatch"),
    ("Avery did not win by fourteen points. That is all.", "negation_mismatch"),
    ("Avery lost by fourteen points. That is all.", "result_verb_mismatch"),
    ("Avery won by fourteen points.", "content_mismatch"),
    ("Avery won by fourteen points. Avery won by fourteen points. That is all.", "content_mismatch"),
])
def test_semantic_corruption_holds(wrong, issue):
    # Mutations: number replacement, negation/winner inversion, ending drop, chunk replay.
    script = {"segments": [{"id": "s1", "text": "Avery won by fourteen points. That is all.",
        "spoken_numbers": [{"value": "14", "spoken": "fourteen"}]}]}
    report = verify_speech(script, transcript(wrong))
    assert report["passed"] is False
    assert issue in report["issues"]
    assert report["raw_transcript"] == transcript(wrong)


def test_caption_text_cannot_hide_wrong_spoken_score():
    report = verify_speech({"segments": [{"id": "s1", "text": "Won by fourteen points.",
        "spoken_numbers": [{"value": "14", "spoken": "fourteen"}]}]},
        {"text": "Won by forty points.", "words": []})
    assert not report["passed"] and "spoken_number_mismatch" in report["issues"]


def test_documented_orthographic_alias_and_complete_evidence():
    script = {"segments": [{"id": "s1", "text": "Avery won.", "spoken_numbers": []}]}
    assert verify_speech(script, transcript("Averie won."), reviewed_aliases={"Avery": ["Averie"]})["passed"]
    assert not verify_speech({**script, "name_aliases": {"Avery": ["Averie"]}}, transcript("Averie won."))["passed"]
    assert not verify_speech(script, {"text": "Avery won.", "words": []})["passed"]
    evidence = transcript("Avery won.")
    evidence["words"][0]["probability"] = .2
    assert "speech_confidence_low" in verify_speech(script, evidence)["issues"]


def test_chunking_counts_tags_and_keeps_whole_narrative_segments():
    # Whole segments protect number/unit and setup/punchline spans by construction.
    segments = [{"id": "a", "text": "[dry] " + "a" * 990}, {"id": "b", "text": "b" * 1004}]
    chunks = split_narration(segments)
    assert [c["segment_ids"] for c in chunks] == [["a"], ["b"]]
    assert all(len(c["text"]) <= 2000 for c in chunks)
    with pytest.raises(ValueError, match="segment"):
        split_narration([{"id": "protected", "text": "x" * 2001}])
    with pytest.raises(ValueError):
        split_narration(segments, 2001)


def test_pinned_model_rejects_missing_and_changed_artifacts(tmp_path):
    from app.services.recap_video.audio import verify_model_artifacts
    with pytest.raises(ValueError, match="model"):
        verify_model_artifacts(tmp_path)
    (tmp_path / "model.bin").write_bytes(b"untrusted model")
    with pytest.raises(ValueError, match="model"):
        verify_model_artifacts(tmp_path)


@pytest.mark.parametrize("written,spoken", [
    ("Avery won by fourteen points.", "Avery won by 14 points!"),
    ("A hundred sixty one points. Forty four more.", "161 points, 44 more."),
    ("One hundred and six point two four.", "106.24."),
    ("Avery should've won but didn't.", "Avery should have won but did not."),
])
def test_formatting_and_supported_contractions_preserve_semantics(written, spoken):
    script = {"segments": [{"id": "s", "text": written, "spoken_numbers": []}]}
    assert verify_speech(script, transcript(spoken))["passed"]


def test_numeric_format_normalization_cannot_merge_two_numbers():
    script = {"segments": [{"id": "s", "text": "One two points.", "spoken_numbers": []}]}
    assert not verify_speech(script, transcript("Three points."))["passed"]


@pytest.mark.parametrize("written,spoken", [("Minus fourteen points.", "14 points."), ("-14 points.", "14 points."), ("14%.", "14.")])
def test_number_sign_and_unit_cannot_disappear(written, spoken):
    assert not verify_speech({"segments": [{"id": "s", "text": written}]}, transcript(spoken))["passed"]
