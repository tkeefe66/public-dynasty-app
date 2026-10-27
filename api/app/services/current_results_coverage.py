"""Source-bound partial-history Results, with separately verified current assets."""
from copy import deepcopy
from dataclasses import replace

from app.services.historical_backfill import digest
from app.services.historical_results_coverage import ResultsCoverage, apply_coverage


def binding(entry, snapshot):
    return digest({
        'identity': entry.owner_identity_version,
        'league_id': entry.league_id, 'seasons': entry.league_season_by_id,
        'membership': entry.roster_to_user_by_league,
        'format': entry.capabilities.get('format'),
        'raw_results': entry.outcome_signals, 'raw_records': entry.season_records,
        'assets': entry.outlook_signals, 'snapshot': snapshot,
    })


def apply_current_results(entry, supporting, raw):
    """Recompute from verified raw seasons. Never mutate the full history."""
    from app.services.rating_signals import compute_rating_signals

    year = max(entry.league_season_by_id.values())
    effective, coverage = apply_coverage(entry, supporting, year, raw)
    if coverage.season_league_id != entry.league_id:
        raise ValueError('Current Results coverage belongs to another league.')
    outcomes, _, _, records = compute_rating_signals(
        {**effective, 'owners': entry.owners,
         'roster_to_user_by_league': entry.roster_to_user_by_league}, {})
    snapshot = {'coverage': coverage.model_dump(mode='json'),
                'outcome_signals': outcomes, 'season_records': records}
    entry.current_rating_verification.update(
        requires_results_coverage=True,
        results_snapshot={**snapshot, 'binding_sha256': binding(entry, snapshot)})


def current_results(entry):
    """Reject stale or incomplete receipts even on direct cache reads."""
    raw = entry.current_rating_verification.get('results_snapshot')
    if not raw:
        return None
    try:
        snapshot = {k: v for k, v in raw.items() if k != 'binding_sha256'}
        coverage = ResultsCoverage.model_validate(snapshot['coverage'])
        if (coverage.league_seasons != entry.league_season_by_id
                or coverage.season_league_id != entry.league_id
                or coverage.identity_version != entry.owner_identity_version
                or set(snapshot['season_records']) != {str(y) for y in coverage.included_seasons}
                or raw.get('binding_sha256') != binding(entry, snapshot)):
            return None
        return snapshot
    except (KeyError, TypeError, ValueError):
        return None


def current_scoped_entry(entry):
    snapshot = current_results(entry)
    if snapshot is None:
        return entry
    owners = entry.owners
    if entry.capabilities.get('format') != 'redraft':
        # A departed owner has no verified current holdings. The signal builder
        # may have emitted numeric zero defaults for them; those are not assets.
        active = set(entry.roster_to_user_by_league.get(entry.league_id, {}).values())
        owners = {uid: owner for uid, owner in owners.items() if uid in active}
    return replace(entry, owners=owners, outcome_signals=deepcopy(snapshot['outcome_signals']),
                   season_records=deepcopy(snapshot['season_records']))
