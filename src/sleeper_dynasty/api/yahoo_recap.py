"""Yahoo source normalization for weekly recap observations; no scoring estimates."""
import json
import re
from dataclasses import asdict

from sleeper_dynasty.api.yahoo import YahooDataError, roster_id_for


async def recap_source(client, path):
    if path == '/state/nfl':
        data = await client.get_nfl_state()
        source = 'sleeper:/state/nfl'
    else:
        match = re.fullmatch(r'/league/([^/]+)(?:/(users|rosters|winners_bracket|losers_bracket|matchups/\d+))?', path)
        if not match:
            raise YahooDataError('Unsupported recap source; inspect the requested resource.')
        league_id, resource = match.groups()
        league, _ = await client.get_league(league_id)
        if league.league_id != league_id:
            raise YahooDataError('Yahoo recap league identity changed; retry source collection.')
        source = 'yahoo:' + path
        if not resource:
            data = {'season': str(league.season), 'name': league.name,
                    'roster_positions': league.roster_positions,
                    'scoring_settings': {'multipliers': league.scoring_settings,
                                         'bonuses': [asdict(b) for b in league.scoring_bonuses]},
                    'settings': {'playoff_week_start': league.playoff_week_start,
                                 'playoff_round_type': 0, 'playoff_teams': league.num_playoff_teams}}
        elif resource in ('users', 'rosters'):
            teams = await client._teams(league_id)
            if len(teams) != league.total_rosters:
                raise YahooDataError('Yahoo recap team inventory is incomplete; retry collection.')
            if resource == 'rosters':
                data = [{'roster_id': roster_id_for(t['team_key']), 'owner_id': client._owner(t)[0]} for t in teams]
            else:
                data = [{'user_id': client._owner(t)[0], 'display_name': t.get('name') or client._owner(t)[1].get('nickname'),
                         'metadata': {'team_name': t.get('name')}} for t in teams]
        elif resource.endswith('_bracket'):
            # Yahoo's scoreboard cannot prove Sleeper-style future bracket edges.
            # Empty regular-season brackets are valid; postseason readiness fails
            # closed until supported Yahoo bracket evidence is available.
            data = []
        else:
            data = await client.get_raw_matchups(league_id, int(resource.split('/')[1]), exact=True)
    return {'ok': True, 'source': source, 'data': data,
            'normalized': True, 'raw': json.dumps(data, sort_keys=True), 'provider_timestamp': ''}
