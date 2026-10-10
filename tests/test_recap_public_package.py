"""Free derivatives retain saved approved audio and exact caption timing."""
import importlib
import pytest


def test_captions_escape_markup_and_preserve_verified_times():
    # Mutation: use equal timing bins or allow caption markup/WEBVTT injection.
    p = importlib.import_module('media.public_package')
    episode = {'captions':[{'start':1.234,'end':2.345,'text':'A < B & C'}]}
    text = p.captions_vtt(episode)
    assert '00:00:01.234 --> 00:00:02.345' in text
    assert 'A &lt; B &amp; C' in text
    with pytest.raises(ValueError):
        p.captions_vtt({'captions':[{'start':2,'end':1,'text':'bad'}]})


def test_derivative_evidence_rejects_wav_named_mp3():
    # Mutation: accept format labels without decoded codec and duration evidence.
    p = importlib.import_module('media.public_package')
    import json
    from pathlib import Path
    root = Path(__file__).parents[1]/'api/tests/fixtures/recap_media'
    report = json.loads((root/'public-qa.json').read_text())
    episode = json.loads((root/'episode.json').read_text())
    assert p.evidence_issues(report,episode,report['hashes']) == []
    report['audio_codec'] = 'pcm_s16le'
    assert p.evidence_issues(report,episode,report['hashes']) == ['public_derivatives_invalid']
