"""Yahoo postseason evidence must retain winners and every roster disposition."""
import copy

import pytest

from sleeper_dynasty.api.yahoo import YahooDataError


def matchup(a, b, winner, *, consolation=False, scores=('100.01', '100.01')):
    return {'week': '16', 'status': 'postevent', 'is_playoffs': '1',
            'is_consolation': str(int(consolation)), 'winner_team_key': f'999.l.1.t.{winner}',
            'teams': [{'team': {'team_key': f'999.l.1.t.{r}',
                       'team_points': {'week': '16', 'total': score}}}
                      for r, score in zip((a, b), scores)]}


def rows():
    return [{'roster_id': r, 'matchup_id': (r + 1) // 2, 'points': '100.01',
             'players': ['p'], 'starters': ['p'], 'players_points': {'p': '100.01'}} for r in range(1, 5)]


def test_postseason_retains_tiebreak_consolation_and_unscheduled_owners():
    # Mutation: derive tie winner from scores, or fabricate a bye for absent owners.
    from sleeper_dynasty.api.yahoo_recap import postseason_rows
    result = postseason_rows('999.l.1', 16, rows(),
        [matchup(1, 2, 2), matchup(3, 4, 3, consolation=True)],
        [f'999.l.1.t.{r}' for r in range(1, 7)], set())
    assert len(result) == 6
    assert result[0]['recap_matchup']['winner'] == 2
    assert result[0]['recap_matchup']['status'] == 'title'
    assert result[2]['recap_matchup']['status'] == 'consolation'
    assert result[4]['recap_status'] == 'not_scheduled'
    assert result[4]['points'] is None and result[4]['starters'] == []
    placement = postseason_rows('999.l.1', 16, rows(),
        [matchup(1, 2, 2), matchup(3, 4, 3, consolation=True)],
        [f'999.l.1.t.{r}' for r in range(1, 5)], {1})
    assert placement[0]['recap_matchup']['status'] == 'placement'


@pytest.mark.parametrize('change', ['winner', 'week', 'pending', 'duplicate', 'foreign', 'missing_row',
                                  'truncated', 'missing_classification', 'invalid_classification'])
def test_postseason_invalid_evidence_cannot_become_publication(change):
    from sleeper_dynasty.api.yahoo_recap import postseason_rows
    matches = [matchup(1, 2, 2), matchup(3, 4, 3, consolation=True)]
    values = rows()
    if change == 'winner': matches[0]['winner_team_key'] = '999.l.1.t.6'
    if change == 'week': matches[0]['week'] = '15'
    if change == 'pending': matches[0]['status'] = 'midevent'
    if change == 'duplicate': matches.append(copy.deepcopy(matches[0]))
    if change == 'foreign': matches[0]['teams'][0]['team']['team_key'] = 'other.l.1.t.1'
    if change == 'missing_row': values.pop()
    if change == 'truncated':
        matches[0]['teams'] = {'0': matches[0]['teams'][0], 'count': 2}
        values = values[2:]
    if change == 'missing_classification': matches[0].pop('is_consolation')
    if change == 'invalid_classification': matches[0]['is_consolation'] = 'unknown'
    with pytest.raises(YahooDataError):
        postseason_rows('999.l.1', 16, values, matches,
            [f'999.l.1.t.{r}' for r in range(1, 7)], set())
