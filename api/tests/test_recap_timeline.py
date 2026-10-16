"""Speech/timeline normalization must agree without modifying raw evidence."""
import copy

from media.timeline import build_episode, digest, validate_episode


def test_timeline_preserves_decimal_fragments_and_audible_homophones():
    # Mutation: join ASR fragments with spaces or omit position-bound homophones.
    script = dict(opening='Welcome.', closing='Good night.', segments=[dict(id='game',
        text='Avery won. Avery beat Blake 123.4 to 110.2.', claim_ids=['result:demo'],
        spoken_numbers=[dict(claim_id='result:demo', spoken='123.4'),
                        dict(claim_id='result:demo', spoken='110.2')])])
    claim = dict(id='result:demo', kind='result', owner_ids=['a', 'b'], matchup_ids=['demo'],
                 winner_id='a', result='win', values=dict(score_a='123.4', score_b='110.2', margin='13.2'))
    inputs = dict(script=script, script_digest=digest(script), claims=dict(period_id='demo',
        owners=[dict(id='a', name='Avery'), dict(id='b', name='Blake')], claims=[claim], matchup_ids=['demo']))
    fragments = [' Welcome.', ' Avery', ' one.', ' Avery', ' beat', ' Blake', ' 123', '.4', ' to',
                 ' 110', '.2.', ' Good', ' night.']
    raw = dict(text=''.join(fragments).strip(), words=[dict(word=w, start=i, end=i+.5, probability=.99)
                                                     for i, w in enumerate(fragments)])
    original = copy.deepcopy(raw)
    episode = build_episode(inputs, raw, ['audio'], '0'*64, 13)
    assert validate_episode(episode) == []
    assert episode['transcript_digest'] == digest(original)
    assert raw == original
    assert ' '.join(c['text'] for c in episode['captions']) == 'Welcome. Avery won. Avery beat Blake 123.4 to 110.2. Good night.'
    assert episode['scenes'][1]['start'] == 1
    assert episode['scenes'][1]['end'] == 11
