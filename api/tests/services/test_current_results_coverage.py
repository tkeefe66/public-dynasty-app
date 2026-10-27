from copy import deepcopy

from ._grader_fixtures import _v2_entry
from .test_historical_results_coverage import covered


def prepared():
    entry = _v2_entry(capabilities={"format": "dynasty"})
    support = covered(entry)
    entry.league_id = 'old'
    entry.league_season_by_id = {'old': 2026, 'excluded': 2023}
    entry.chain[0].update(season=2026, status='in_season')
    support['league_season_by_id'] = entry.league_season_by_id
    support['verified_result_seasons'] = [2026]
    entry.current_rating_verification = {'status': 'ready', 'format': 'dynasty'}
    entry.season_rating_inputs = {'2023': {'requires_results_coverage': True}}
    return entry, support


def policy(entry, support):
    from app.services.historical_results_coverage import make_coverage
    return make_coverage(entry, support, 2026, verified_by='fixture', evidence_sha256='a' * 64)


def test_current_provisional_filters_results_preserves_assets_and_history():
    from app.services.current_results_coverage import apply_current_results
    from app.services.season_ratings import rating_scope, scoped_rating_entry

    entry, support = prepared()
    original = deepcopy(entry.season_records)
    assets = deepcopy(entry.outlook_signals)
    apply_current_results(entry, support, policy(entry, support).model_dump(mode='json'))
    scope = rating_scope(entry, 'all')
    assert scope['status'] == 'provisional'
    assert scope['included_seasons'] == [2026]
    assert scope['excluded_seasons'][0]['season'] == 2023
    scoped = scoped_rating_entry(entry, 'all')
    assert set(scoped.season_records) == {'2026'}
    assert scoped.outlook_signals == assets
    assert entry.season_records == original
    assert scoped.outcome_signals != entry.outcome_signals
    from app.services.season_ratings import build_season_rating_inputs
    entry.season_rating_inputs = build_season_rating_inputs(entry, support)
    assert rating_scope(entry, 2026)['status'] == 'provisional'
    assert rating_scope(entry, 2026)['excluded_seasons'] == scope['excluded_seasons']
    assert scoped_rating_entry(entry, 2026).outcome_signals == scoped.outcome_signals
    entry.current_rating_verification['status'] = 'unavailable'
    entry.current_rating_verification['reason'] = 'Missing current prices'
    assert rating_scope(entry, 'all')['status'] == 'unavailable'


def test_changed_or_missing_receipt_cannot_publish_current_provisional():
    from app.services.current_results_coverage import apply_current_results
    from app.services.season_ratings import rating_scope

    entry, support = prepared()
    apply_current_results(entry, support, policy(entry, support).model_dump(mode='json'))
    entry.owner_identity_version = 'changed'
    assert rating_scope(entry, 'all')['status'] == 'unavailable'
    entry.owner_identity_version = ''
    entry.current_rating_verification.pop('results_snapshot')
    assert rating_scope(entry, 'all')['status'] == 'unavailable'
