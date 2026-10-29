import pytest

from sleeper_dynasty.llm.recap_packet import ArchivedPacket


def packet():
    return ArchivedPacket({'source_snapshot': {'week': 7,
        'participants': [{'roster_id': 1, 'owner_name': 'Alpha'}],
        'scores': {'7': [{'roster_id': 1, 'starters': ['a', 'b', 'c'],
            'players_points': {'a': '36.5', 'b': '24.5', 'c': '23.4', 'bench': '26.12'}}]}}})


@pytest.mark.parametrize('text', [
    "**Alpha's** lineup: a **36.5-point** starter and a **26.12-point** contribution.",
    "**Alpha's** lineup had four starters above 23 points.",
    "**Alpha's** lineup had a **26.12-point** starter.",
])
def test_rejects_bench_score_and_wrong_starter_count(text):
    from sleeper_dynasty.llm.recap_starter_claims import require_starter_claims
    with pytest.raises(ValueError, match='starter'):
        require_starter_claims(text, packet())


def test_accepts_verified_starters_and_explicit_bench_role():
    from sleeper_dynasty.llm.recap_starter_claims import require_starter_claims
    require_starter_claims("**Alpha's** lineup had three starters above 23 points. A **36.5-point** starter.", packet())
    require_starter_claims("**Alpha's** bench scored 26.12 points.", packet())
    require_starter_claims("Alpha's starter scored 36.5. His bench contributed 26.12 points.", packet())


def test_new_brief_excludes_unlabelled_bench_but_retains_legacy_replay():
    from sleeper_dynasty.llm.recap_packet import editorial_facts
    data = packet().to_dict()
    data.update(heroes=[], goats=[], busts=[], bench_regret=[], lineups=[], player_context={})
    data['source_snapshot']['scores']['7'][0]['players'] = ['a', 'b', 'c', 'bench']
    original = ArchivedPacket(data)
    new = editorial_facts(original, starter_safe=True)
    old = editorial_facts(original)
    assert 'bench' not in new['source_snapshot']['scores']['7'][0]['players_points']
    assert old['source_snapshot']['scores']['7'][0]['players_points']['bench'] == '26.12'
    assert original.to_dict() == data
