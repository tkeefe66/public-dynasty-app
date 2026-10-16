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


@pytest.mark.parametrize("boundary", [". ", "! ", "? ", "; ", ": "])
def test_spoken_decimal_stops_at_sentence_boundary(boundary):
    # Mutation: strip punctuation before number parsing, merging 1.4 and four into 1.44.
    script = {"segments": [{"id": "s", "text": "One point four" + boundary + "Four stars."}]}
    assert verify_speech(script, transcript("1.4. Four stars."))["passed"]
    assert not verify_speech(script, transcript("1.44 stars."))["passed"]


@pytest.mark.parametrize('fragments,consistent', [
    ([' Score', ' 123', '.4', ' points.'], True),
    ([' Score', ' 123', '.5', ' points.'], False),
    ([' Score', ' 123', ' 4', ' points.'], False),
])
def test_recognizer_word_fragments_preserve_decimal_boundaries(fragments, consistent):
    # Mutation: joining raw recognizer fragments with extra spaces corrupts decimals;
    # removing every space instead would incorrectly merge independent numbers.
    # Shape captured from pinned faster-whisper; names/content are synthetic.
    text = 'Score 123.4 points.'
    raw = {'text': text, 'words': [dict(word=w, start=i, end=i+.5, probability=.99)
                                  for i, w in enumerate(fragments)]}
    result = verify_speech({'segments': [dict(id='s', text=text)]}, raw)
    assert ('speech_evidence_inconsistent' not in result['issues']) is consistent
    assert result['passed'] is consistent
    assert result['raw_transcript'] == raw


@pytest.mark.parametrize("written,spoken", [("Minus fourteen points.", "14 points."), ("-14 points.", "14 points."), ("14%.", "14.")])
def test_number_sign_and_unit_cannot_disappear(written, spoken):
    assert not verify_speech({"segments": [{"id": "s", "text": written}]}, transcript(spoken))["passed"]


def segmented_transcript(text):
    raw = transcript(text)
    raw['segments'] = [dict(text=text, start=0, end=raw['words'][-1]['end'],
                            avg_logprob=-.1, no_speech_prob=.1)]
    return raw


def test_exact_audible_homophones_use_approved_position_only():
    # Mutation: remove narrow homophones, or apply fuzzy/content-insensitive matching.
    script = {'segments': [dict(id='s', text='Avery won. Blake has a bye.')]}
    assert verify_speech(script, transcript('Avery one. Blake has a buy.'))['passed']
    for wrong in ['Blake one. Avery has a buy.', 'Avery lost. Blake has a buy.',
                  'Avery one. Blake has no buy.', 'Avery one. Blake had a buy.']:
        assert not verify_speech(script, transcript(wrong))['passed']
    assert not verify_speech({'segments': [dict(id='s', text='Score one.')]}, transcript('Score won.'))['passed']


def test_segment_evidence_can_support_isolated_low_word_confidence():
    # Mutation: retain every-word .75 rule despite exact text and strong segment evidence.
    raw = segmented_transcript('Avery won the game by fourteen points today.')
    raw['words'][2]['probability'] = .2
    original = __import__('copy').deepcopy(raw)
    result = verify_speech({'segments': [dict(id='s', text=raw['text'])]}, raw)
    assert result['passed']
    assert result['raw_transcript'] == original


def test_captured_calibration_segment_preserves_raw_homophone_evidence():
    # Mutation: every-word confidence floor or removal of won/one equivalence.
    # Captured pinned faster-whisper evidence from the fictional-team calibration.
    raw = {'text': 'Alpha one, Bravo lost.', 'words': [
        {'word': ' Alpha', 'start': 20.48, 'end': 20.88, 'probability': 0.9953901767730713},
        {'word': ' one,', 'start': 20.88, 'end': 21.28, 'probability': 0.38946112990379333},
        {'word': ' Bravo', 'start': 21.86, 'end': 22.0, 'probability': 0.9010677337646484},
        {'word': ' lost.', 'start': 22.0, 'end': 22.44, 'probability': 0.9640864729881287}],
        'segments': [{'text': ' Alpha one, Bravo lost.', 'start': 20.48, 'end': 22.44,
                      'avg_logprob': -0.15105017354187456, 'no_speech_prob': 0.005004620645195246}]}
    assert verify_speech({'segments': [dict(id='s', text='Alpha won, Bravo lost.')]}, raw)['passed']


@pytest.mark.parametrize('mutation', ['missing', 'nan', 'text', 'coverage', 'weak', 'silence', 'all_low'])
def test_segment_confidence_requires_complete_consistent_evidence(mutation):
    # Mutation: trust high segment metadata without validating coverage/text/word confidence.
    raw = segmented_transcript('Avery won the game by fourteen points today.')
    raw['words'][2]['probability'] = .2
    segment = raw['segments'][0]
    if mutation == 'missing': del segment['avg_logprob']
    if mutation == 'nan': segment['start'] = float('nan')
    if mutation == 'text': segment['text'] = 'Different words.'
    if mutation == 'coverage': segment['end'] -= .2
    if mutation == 'weak': segment['avg_logprob'] = -2
    if mutation == 'silence': segment['no_speech_prob'] = .9
    if mutation == 'all_low':
        for word in raw['words']: word['probability'] = .2
    assert not verify_speech({'segments': [dict(id='s', text=raw['text'])]}, raw)['passed']


def test_zero_duration_word_preserved_but_zero_duration_phrase_rejected():
    # Mutation: require every word positive duration, or allow entirely zero-duration evidence.
    raw = segmented_transcript('Avery won the game today.')
    raw['words'][2]['end'] = raw['words'][2]['start']
    script = {'segments': [dict(id='s', text=raw['text'])]}
    assert verify_speech(script, raw)['passed']
    for word in raw['words']: word['start'] = word['end'] = 0
    raw['segments'][0]['end'] = 0
    assert not verify_speech(script, raw)['passed']


def test_zero_duration_word_at_segment_boundary_belongs_to_matching_text():
    # Mutation: greedily consume every word ending at the preceding segment end.
    raw = dict(text='Alpha won. Bravo lost.', words=[
        dict(word=' Alpha', start=0, end=.5, probability=.99),
        dict(word=' won.', start=.5, end=1, probability=.99),
        dict(word=' Bravo', start=1, end=1, probability=.99),
        dict(word=' lost.', start=1, end=1.5, probability=.99)], segments=[
        dict(text='Alpha won.', start=0, end=1, avg_logprob=-.1, no_speech_prob=.1),
        dict(text='Bravo lost.', start=1, end=1.5, avg_logprob=-.1, no_speech_prob=.1)])
    script = {'segments': [dict(id='s', text=raw['text'])]}
    assert verify_speech(script, raw)['passed']
    raw['segments'][1]['text'] = 'Charlie lost.'
    assert not verify_speech(script, raw)['passed']
