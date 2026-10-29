import copy

import pytest

from app.services.recap_video.periods import build_participants, scoring_period


def source():
    pair = {'rosters': [1, 2], 'winner': 2, 'loser': 1, 'status': 'title', 'source_id': 'yahoo:16:1:2'}
    rows = [{'roster_id': r, 'matchup_id': 1, 'points': '99.99', 'players': ['p'],
             'starters': ['p'], 'players_points': {'p': '99.99'}, 'recap_matchup': copy.deepcopy(pair)} for r in (1, 2)]
    rows.append({'roster_id': 3, 'matchup_id': None, 'points': None, 'players': [],
                 'starters': [], 'players_points': {}, 'recap_status': 'not_scheduled'})
    return rows


def test_yahoo_period_uses_provider_winner_and_preserves_unscheduled_owner():
    # Mutation: require invented bracket edges, drop idle owners, or derive tied winner.
    settings = {'recap_provider': 'yahoo', 'end_week': 17, 'playoff_week_start': 15, 'playoff_teams': 6}
    period = scoring_period(16, settings, {'ok': True, 'winners': [], 'losers': []})
    assert period['nfl_weeks'] == [16] and period['period_id'] == 'playoff:2'
    period['roster_positions'] = ['QB']
    result = build_participants([{'roster_id': r, 'owner_id': str(r)} for r in (1, 2, 3)],
                                {'16': source()}, {'ok': True}, period)
    assert not result['participant_error']
    assert result['pairings'][0]['winner'] == 2
    assert result['pairings'][0]['result'] == 'tiebreak_win'
    assert result['participants'][2]['status'] == 'not_scheduled'
    with pytest.raises(ValueError, match='season_finished'):
        scoring_period(18, settings, {'ok': True})


@pytest.mark.parametrize('change', ['winner', 'mismatched_pair', 'unknown_idle', 'extra_pair', 'missing_row'])
def test_yahoo_postseason_rejects_conflicting_participant_evidence(change):
    rows = source()
    if change == 'winner':
        for row in rows[:2]: row['recap_matchup']['winner'] = 3
    if change == 'mismatched_pair': rows[0]['recap_matchup']['status'] = 'consolation'
    if change == 'unknown_idle': rows[2].pop('recap_status')
    if change == 'extra_pair': rows[2]['matchup_id'] = 1
    if change == 'missing_row': rows.pop()
    result = build_participants([{'roster_id': r, 'owner_id': str(r)} for r in (1, 2, 3)],
        {'16': rows}, {'ok': True}, {'provider': 'yahoo', 'phase': 'post', 'round': 2,
        'round_type': 0, 'nfl_weeks': [16], 'roster_positions': ['QB']})
    assert result['participant_error']
