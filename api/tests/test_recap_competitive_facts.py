"""Period evidence must not drift when next week's live roster changes."""
import copy
import json

import pytest

from app.services.generation.recap_models import RecapEpisode, RecapObservation, RecapPublication
from app.services.generation.store import dump
from app.services.recap_video.readiness import competitive_digest
from tests.test_recap_readiness import snapshot
from tests.test_recap_publication import ready_article, legacy_for_canonical


def live_change(source):
    changed = copy.deepcopy(source)
    changed['participants'][0].update(starters=['next-week'], players=['new-player'],
        settings={'wins': 5, 'fpts': 979}, metadata={'record': 'WLWWWW'}, reserve=['injured'])
    changed['rules'] = {**changed.get('rules', {}), 'leg': 7, 'last_report': 6, 'last_scored_leg': 6}
    changed['bracket']['winners'] = [{'r': 1, 'm': 1, 't1': 2, 't2': 1}]
    return changed


def test_live_roster_and_projected_bracket_do_not_change_historical_facts():
    # Mutation: hash complete live roster/settings/bracket instead of period evidence.
    source = snapshot()
    assert competitive_digest(source) == competitive_digest(live_change(source))


def test_inventory_revision_alone_does_not_reset_completed_period_stability():
    from app.services.recap_video.readiness import evaluate_readiness
    old = snapshot()
    changed = {**old, 'schedule_revision': 'next-week-schedule-refresh'}
    assert competitive_digest(old) == competitive_digest(changed)
    assert evaluate_readiness(changed, old, 4600).ready


@pytest.mark.asyncio
async def test_schedule_metadata_rollout_preserves_existing_authority(maker, tmp_path, monkeypatch):
    from app.services.generation.store import digest
    from app.services.recap_video.readiness import competitive_facts
    from app.services.recap_video.corrections import observe_correction
    ident = await ready_article(maker, tmp_path, monkeypatch)
    legacy, _ = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        old = await db.get(RecapObservation, episode.latest_observation_id)
        source = json.loads(old.snapshot_json)
        old_hash = digest({**competitive_facts(source), 'schedule_revision': source['schedule_revision']})
        old.facts_digest = episode.facts_digest = old_hash
        result = await observe_correction(db, ident, {**source, 'schedule_revision': 'updated-inventory'}, 6400)
        assert result['withdrawn'] == []
        assert episode.facts_digest == old_hash
        assert not (await db.get(RecapPublication, legacy)).withdrawn


@pytest.mark.parametrize('field', ['score', 'starter', 'owner', 'scoring', 'postseason'])
def test_competitive_changes_remain_detectable(field):
    # Mutation: drop actual period scores, lineup, ownership, scoring or playoff evidence.
    source = snapshot()
    changed = copy.deepcopy(source)
    if field == 'score':
        changed['scores']['4'][0]['points'] = '101.01'
    elif field == 'starter':
        changed['scores']['4'][0]['starters'][0] = 'replacement'
    elif field == 'owner':
        changed['participants'][0]['owner_id'] = 'replacement-owner'
    elif field == 'scoring':
        changed['scoring_settings'] = {'rec': 2}
    else:
        source['phase'] = changed['phase'] = 'post'
        changed['bracket']['winners'] = [{'r': 1, 'm': 1, 't1': 2, 't2': 1}]
    assert competitive_digest(source) != competitive_digest(changed)


@pytest.mark.asyncio
async def test_live_change_does_not_withdraw_existing_legacy_digest(maker, tmp_path, monkeypatch):
    # Mutation: compare old raw stored hash to new semantic hash and withdraw on rollout.
    from app.services.generation.store import digest
    from app.services.recap_video.readiness import FACT_FIELDS
    from app.services.recap_video.corrections import observe_correction
    ident = await ready_article(maker, tmp_path, monkeypatch)
    legacy, _ = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        old = await db.get(RecapObservation, episode.latest_observation_id)
        source = json.loads(old.snapshot_json)
        source['participants'][0]['starters'] = ['previous-live-player']
        old.snapshot_json = dump(source)
        old.snapshot_digest = digest(source)
        episode.facts_digest = digest({k: source.get(k) for k in FACT_FIELDS})
        old.facts_digest = episode.facts_digest
        authority_digest = episode.facts_digest
        result = await observe_correction(db, ident, live_change(source), 6400)
        assert result['withdrawn'] == []
        assert not (await db.get(RecapPublication, legacy)).withdrawn
        assert episode.hold != 'recap_facts_changed'
        assert episode.facts_digest == authority_digest
        again = live_change(source)
        again['participants'][0]['players'] = ['another-live-change']
        await observe_correction(db, ident, again, 10400)
        assert episode.facts_digest == authority_digest
        assert not (await db.get(RecapPublication, legacy)).withdrawn
        from app.services.recap_video.readiness import require_readiness
        assert await require_readiness(db, episode.series_id, {
            'season': episode.season, 'week': episode.week,
            'period_id': episode.period_id, 'recap_facts_digest': authority_digest}) is episode


def test_generation_source_omits_live_stats_but_retains_period_lineups():
    # Mutation: fix hash but still feed future cumulative stats/lineups to the writer.
    from app.services.recap_video.collector import source_facts
    source = live_change(snapshot())
    facts = source_facts(source)
    assert 'settings' not in facts['participants'][0]
    assert 'starters' not in facts['participants'][0]
    assert facts['scores'] == source['scores']


@pytest.mark.asyncio
async def test_corrected_historical_starter_still_withdraws(maker, tmp_path, monkeypatch):
    # Mutation: exclude historical matchup starters together with the live lineup.
    from app.services.recap_video.corrections import observe_correction
    from app.services.recap_video.periods import build_participants
    ident = await ready_article(maker, tmp_path, monkeypatch)
    legacy, _ = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        source = json.loads((await db.get(RecapObservation, episode.latest_observation_id)).snapshot_json)
        starters = source['scores']['4'][0]['starters']
        starters[0], starters[1] = starters[1], starters[0]
        source.update(build_participants(source['participants'], source['scores'], source['bracket'], source))
        result = await observe_correction(db, ident, source, 6400)
        assert result['withdrawn'] == [legacy]
        assert (await db.get(RecapPublication, legacy)).withdrawn


@pytest.mark.asyncio
async def test_source_outage_then_identical_facts_does_not_withdraw(maker, tmp_path, monkeypatch):
    # Mutation: replace known facts with incomplete fetch hash, then call recovery a correction.
    from app.services.recap_video.corrections import observe_correction
    ident = await ready_article(maker, tmp_path, monkeypatch)
    legacy, _ = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        source = json.loads((await db.get(RecapObservation, episode.latest_observation_id)).snapshot_json)
        original = episode.facts_digest
        await observe_correction(db, ident, {**source, 'observed_games': []}, 6400)
        assert episode.facts_digest == original
        await observe_correction(db, ident, source, 10400)
        assert not (await db.get(RecapPublication, legacy)).withdrawn
        assert episode.hold != 'recap_facts_changed'
