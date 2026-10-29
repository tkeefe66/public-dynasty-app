"""Yahoo source normalization for weekly recap observations; no scoring estimates."""
import json
import re
from dataclasses import asdict

from sleeper_dynasty.api.yahoo import YahooDataError, _require_week, _truth, child, roster_id_for
from sleeper_dynasty.api.yahoo_json import collection, merge_fragments


def postseason_inventory(matchups, week, team_keys):
    """Validate complete current or prior playoff evidence before interpreting it."""
    seen = set()
    results = []
    for matchup in matchups:
        _require_week(matchup, week)
        if any(matchup.get(flag) not in (0, 1, '0', '1')
               for flag in ('is_playoffs', 'is_consolation')):
            raise YahooDataError('Yahoo playoff classification is missing or invalid; retry collection.')
        if matchup.get('status') != 'postevent' or not _truth(matchup['is_playoffs']):
            raise YahooDataError('Yahoo postseason matchup is not final; retry after results settle.')
        raw = child(matchup, 'teams')
        sides = collection(raw)
        if isinstance(raw, dict) and str(raw.get('count')) != str(len(sides)):
            raise YahooDataError('Yahoo postseason team count is incomplete; retry collection.')
        if any(not isinstance(t, dict) or 'team' not in t for t in sides):
            raise YahooDataError('Yahoo postseason team shape is invalid; retry collection.')
        keys = [merge_fragments(t['team']).get('team_key') for t in sides]
        if len(keys) not in (1, 2) or len(set(keys)) != len(keys) or set(keys) - set(team_keys) or seen.intersection(keys):
            raise YahooDataError('Yahoo postseason participant coverage conflicts; retry collection.')
        if len(keys) == 2 and matchup.get('winner_team_key') not in keys:
            raise YahooDataError('Yahoo postseason winner is unresolved; retry after results settle.')
        seen.update(keys)
        results.append((matchup, keys))
    return results


def postseason_rows(league_id, week, rows, matchups, team_keys, eliminated):
    """Bind exact completed Yahoo outcomes; absence never implies elimination."""
    inventory = {roster_id_for(k): k for k in team_keys}
    indexed = {r['roster_id']: r for r in rows}
    if len(inventory) != len(team_keys) or len(indexed) != len(rows) or set(indexed) - inventory.keys():
        raise YahooDataError('Yahoo postseason team inventory conflicts; retry collection.')
    playing = set()
    for matchup, keys in postseason_inventory(matchups, week, team_keys):
        if len(keys) == 1:
            continue  # A one-team scoreboard entry has no opponent/result.
        winner_key = matchup.get('winner_team_key')
        if winner_key not in keys:
            raise YahooDataError('Yahoo postseason winner is unresolved; retry after results settle.')
        ids = [roster_id_for(k) for k in keys]
        if any(r not in indexed for r in ids):
            raise YahooDataError('Yahoo postseason scoring rows are incomplete; retry collection.')
        state = ('consolation' if _truth(matchup.get('is_consolation')) else
                 'placement' if set(ids) & eliminated else 'title')
        evidence = {'rosters': ids, 'winner': roster_id_for(winner_key),
                    'loser': next(r for r in ids if r != roster_id_for(winner_key)),
                    'status': state, 'source_id': f'yahoo:{week}:' + ':'.join(str(r) for r in sorted(ids))}
        for rid in ids:
            indexed[rid]['recap_matchup'] = evidence
            playing.add(rid)
    if set(indexed) != playing or not playing:
        raise YahooDataError('Yahoo postseason result inventory is incomplete; retry collection.')
    for rid in inventory.keys() - playing:
        rows.append({'roster_id': rid, 'matchup_id': None, 'points': None,
                     'players': [], 'starters': [], 'players_points': {}, 'recap_status': 'not_scheduled'})
    return rows


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
                    'settings': {'recap_provider': 'yahoo', 'end_week': int(client._metadata[league_id]['end_week']),
                                 'playoff_week_start': league.playoff_week_start,
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
            # Yahoo supplies period-local result authority on the scoring rows.
            # Never invent Sleeper future bracket edges from Yahoo standings.
            data = []
        else:
            data = await client.get_raw_matchups(league_id, int(resource.split('/')[1]), exact=True)
    return {'ok': True, 'source': source, 'data': data,
            'normalized': True, 'raw': json.dumps(data, sort_keys=True), 'provider_timestamp': ''}
