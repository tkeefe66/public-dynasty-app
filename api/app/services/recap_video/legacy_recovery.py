"""Explicit, receipt-only recovery of false live-roster withdrawals.

This incident recovery does not adopt legacy media into the generation pipeline,
change sharing consent, or authorize any provider request. The caller owns the
transaction. File/media verification remains enforced by the normal read path.
"""
import json
import hashlib
import re
from pathlib import Path
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.services.generation.models import (ArtifactHead, ContentArtifact, GenerationAudit,
    GenerationOperation, GenerationOutbox, ProviderAttempt, stamp)
from app.services.generation.recap_models import (RecapAttention, RecapEpisode,
    RecapObservation, RecapPublication, RecapShareDecision, RecapStage)
from app.services.generation.store import Held, audit, digest, dump, lock_control
from app.services.recap_video.publication import legacy_episode_id, public_article, serving_gate
from app.services.recap_video.qualification import require_admin_actor
from app.services.recap_video.readiness import competitive_digest, evaluate_readiness


def legacy_claim_evidence(facts, source):
    """Verify frozen named lineup facts against immutable period observations.

    This proves the structured scoring claims, not arbitrary natural-language
    prose, news, or forecasts. Callers must separately bind their editorial review.
    Never manufacture a historical source_snapshot from these named facts.
    """
    def require(value):
        if not value:
            raise Held('legacy_claim_evidence_conflict')
    def equal(a, b):
        require(Decimal(str(a)).is_finite() and Decimal(str(b)).is_finite())
        require(Decimal(str(a)) == Decimal(str(b)))
    def unique(rows, key):
        result = {r[key]: r for r in rows}
        require(bool(result) and len(result) == len(rows))
        return result
    try:
        equal(facts['week'], source['week'])
        owners = unique(source['participants'], 'owner_name')
        scores = unique(source['scores'][str(source['week'])], 'roster_id')
        require(set(scores) == {p['roster_id'] for p in owners.values()})
        names = unique(facts['player_context']['players'], 'player')
        require(len({p['player_id'] for p in names.values()}) == len(names))
        def player_id(player):
            name = player['player'].rsplit(' (', 1)[0]
            if name in names:
                require(player['position'] == names[name]['position'])
                return names[name]['player_id']
            # Defense identifiers are team codes, explicitly present in the
            # frozen display label and checked against the period roster below.
            require(player['position'] == 'DEF' and ' (DEF, ' in player['player'])
            return player['player'].rsplit(', ', 1)[1].removesuffix(')')
        lineups = unique(facts['lineups'], 'owner')
        require(set(lineups) == set(owners))
        starter_count = 0
        for owner, lineup in lineups.items():
            row = scores[owners[owner]['roster_id']]
            require([player_id(p) for p in lineup['starters']] == row['starters'])
            require(len(set(row['starters'])) == len(row['starters']))
            for player in lineup['starters']:
                require(player['owner'] == owner)
                equal(player['points'], row['players_points'][player_id(player)])
                starter_count += 1
        covered = set()
        opponents = {}
        for matchup in facts['matchups']:
            a, b = matchup['winner'], matchup['loser']
            require(a != b and a not in covered and b not in covered)
            covered.update((a, b)); opponents[a], opponents[b] = b, a
            ar, br = scores[owners[a]['roster_id']], scores[owners[b]['roster_id']]
            require(ar['matchup_id'] is not None and ar['matchup_id'] == br['matchup_id'])
            equal(matchup['winner_points'], ar['points']); equal(matchup['loser_points'], br['points'])
            margin = Decimal(ar['points']) - Decimal(br['points'])
            equal(matchup['margin'], margin)
            require(margin >= 0 and matchup['tied'] == (margin == 0))
        require(covered == set(owners))
        # Awards and projections reuse named player records; verify every
        # concrete player score wherever the frozen packet repeats it.
        def check_player_records(value):
            if isinstance(value, dict):
                if {'owner', 'player', 'position', 'points'} <= set(value):
                    row = scores[owners[value['owner']]['roster_id']]
                    identity = player_id(value)
                    require(identity in row['players'])
                    equal(value['points'], row['players_points'][identity])
                for child in value.values():
                    check_player_records(child)
            elif isinstance(value, list):
                for child in value:
                    check_player_records(child)
        check_player_records(facts)
        for field, high in (('high_scorer', True), ('low_scorer', False)):
            if facts.get(field):
                value = facts[field]
                points = scores[owners[value['owner']]['roster_id']]['points']
                equal(value['points'], points)
                equal(points, (max if high else min)(Decimal(row['points']) for row in scores.values()))
        standings = unique(facts['standings'], 'owner')
        require(set(standings) == set(owners))
        for owner, standing in standings.items():
            settings = owners[owner]['settings']
            for field in ('wins', 'losses', 'ties'):
                equal(standing[field], settings[field])
            equal(standing['points_for'], round(settings['fpts'] + settings['fpts_decimal'] / 100, 1))
        swaps = 0
        for regret in facts['bench_regret']:
            owner = regret['owner']; row = scores[owners[owner]['roster_id']]
            opponent = scores[owners[opponents[owner]]['roster_id']]
            for swap in regret['legal_swaps']:
                bench, starter = swap['benched_player'], swap['started_player']
                a, b = player_id(bench), player_id(starter)
                require(bench['owner'] == starter['owner'] == owner)
                require(a in row['players'] and a not in row['starters'] and b in row['starters'])
                slot = source['roster_positions'][row['starters'].index(b)]
                require(swap['slot'] == slot)
                eligible = {'FLEX': {'RB', 'WR', 'TE'}, 'SUPER_FLEX': {'QB', 'RB', 'WR', 'TE'}}.get(slot, {slot})
                require(bench['position'] in eligible)
                equal(bench['points'], row['players_points'][a]); equal(starter['points'], row['players_points'][b])
                gain = Decimal(str(bench['points'])) - Decimal(str(starter['points']))
                equal(swap['points_gained'], gain)
                effect = swap['matchup_effect']; total = Decimal(row['points']) + gain
                equal(effect['team_points'], total); equal(effect['opponent_points'], opponent['points'])
                margin = total - Decimal(opponent['points']); equal(effect['margin'], margin)
                require(effect['result'] == ('win' if margin > 0 else 'loss' if margin < 0 else 'tie'))
                swaps += 1
        return dict(facts_digest=digest(facts), source_digest=digest(source), starters=starter_count,
                    swaps=swaps, standings=len(standings), matchups=len(facts['matchups']))
    except (KeyError, TypeError, ValueError, InvalidOperation, IndexError):
        raise Held('legacy_claim_evidence_incomplete') from None


async def recover_false_withdrawal(db, episode_id, *, expected_revision, artifact_id,
                                   actor_id, reason, apply=False, expected_digest=None,
                                   editorial_review=None, cache_dir=None):
    """Preview/apply one exact imported edition; never perform paid work.

    Run the preview in a read-only transaction when operationally possible. Apply
    rechecks every proof under the generation control lock and requires its digest.
    The report deliberately does not claim the API filesystem has been verified.
    """
    if not reason.strip():
        raise Held('recovery_reason_required')
    if apply:
        await lock_control(db)
    await require_admin_actor(db, actor_id)
    gate = await serving_gate(db)
    episode = await db.get(RecapEpisode, episode_id, populate_existing=True)
    if (not episode or episode.admitted_at or episode.article_digest
            or episode.lifecycle != 'correction' or episode.hold != 'recap_facts_changed'):
        raise Held('legacy_false_withdrawal_episode_required')
    legacy_id = legacy_episode_id(episode.league_id, episode.season, episode.week)
    row = await db.get(RecapPublication, legacy_id, populate_existing=True)
    if (not row or row.article_id or not row.withdrawn or row.hold
            or row.authority_revision != expected_revision or row.epoch != gate.epoch):
        raise Held('legacy_withdrawal_authority_changed')
    if await db.scalar(select(RecapStage.id).where(RecapStage.episode_id == episode_id).limit(1)):
        raise Held('legacy_recovery_has_canonical_media')
    withdrawals = (await db.scalars(select(GenerationAudit).where(
        GenerationAudit.target == legacy_id, GenerationAudit.action == 'recap_publication_withdrawn')
        .order_by(GenerationAudit.created_at))).all()
    if (len(withdrawals) != 1 or withdrawals[0].reason != 'recap_facts_changed'
            or withdrawals[0].actor_id != 'api-observer'):
        raise Held('legacy_false_withdrawal_audit_required')
    withdrawal = withdrawals[0]

    artifact = await db.get(ContentArtifact, artifact_id, populate_existing=True)
    if (not artifact or artifact.feature != 'analyst' or artifact.league_id != episode.league_id
            or artifact.series_id != episode.series_id or artifact.created_at > row.published_at):
        raise Held('legacy_original_artifact_required')
    data = json.loads(artifact.payload_json)
    head = await db.get(ArtifactHead, artifact.subject, populate_existing=True)
    projection = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + artifact.id))
    if (not head or head.hold or head.artifact_id != artifact.id or head.revision != artifact.revision
            or digest(data) != artifact.digest or data.get('revision') != artifact.revision
            or data.get('season') != episode.season or data.get('week') != episode.week
            or digest(public_article(data)) != row.article_digest
            or digest(json.loads(row.article_json)) != row.article_digest
            or not projection or not projection.delivered or projection.error or projection.kind != 'artifact'
            or json.loads(projection.payload_json).get('artifact_id') != artifact.id):
        raise Held('legacy_original_article_changed')
    operation = await db.get(GenerationOperation, artifact.operation_id, populate_existing=True) if artifact.operation_id else None
    if (not operation or operation.state != 'succeeded' or operation.artifact_id != artifact.id
            or operation.league_id != episode.league_id or operation.feature != 'analyst'):
        raise Held('legacy_original_operation_required')
    receipts = (await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == operation.id))).all()
    if (not receipts or len(receipts) != operation.calls or any(
            r.state != 'received' or r.usage_state != 'known' or r.cost_microusd is None or not r.receipt_json
            for r in receipts)):
        raise Held('legacy_original_receipts_unsettled')
    if await db.scalar(select(GenerationOperation.id).where(
            GenerationOperation.subject == artifact.subject,
            GenerationOperation.id != operation.id,
            GenerationOperation.created_at >= withdrawal.created_at).limit(1)):
        raise Held('legacy_recovery_has_new_generation')

    observations = (await db.scalars(select(RecapObservation).where(
        RecapObservation.episode_id == episode_id).order_by(RecapObservation.observed_at))).all()
    baseline = None
    valid = []
    for observation in observations:
        source = json.loads(observation.snapshot_json)
        if digest(source) != observation.snapshot_digest:
            raise Held('legacy_observation_integrity_failed')
        if evaluate_readiness(source, None, stamp()).code not in ('ready', 'facts_unstable', 'release_not_due'):
            continue  # An incomplete fetch is not evidence of a changed score.
        valid.append((observation, source))
        if baseline is None and row.published_at <= observation.observed_at < withdrawal.created_at:
            baseline = (observation, source)
    if not baseline or not valid or valid[-1][0].id != episode.latest_observation_id:
        raise Held('legacy_recovery_current_evidence_required')
    canonical = competitive_digest(baseline[1])
    # Continuity since import does not prove a pre-import article was correct.
    # Prefer the complete period evidence sealed inside the approved artifact.
    # Older named facts need their original identity mapping and independent
    # structured verification, plus a separately bound editorial/media review.
    approved_source = (data.get('facts') or {}).get('source_snapshot')
    claim_proof = None
    corrected = None
    if not isinstance(approved_source, dict):
        # Older paid editions sealed named facts and source player IDs instead
        # of the newer raw snapshot. Prove those claims independently, and bind
        # a separate explicit editorial review of prose/news/forecast context.
        if not editorial_review:
            raise Held('legacy_original_source_equivalence_unproven')
        operation_data = json.loads(operation.payload_json)
        if data.get('facts') != operation_data.get('facts'):
            raise Held('legacy_original_facts_changed')
        claim_proof = legacy_claim_evidence(data['facts'], baseline[1])
        corrected = reviewed_slot_correction(data, baseline[1], row, editorial_review)
        if cache_dir is None:
            raise Held('legacy_recovery_api_cache_required')
        verify_legacy_media(row, editorial_review)
    elif competitive_digest(approved_source) != canonical:
        raise Held('legacy_original_source_equivalence_unproven')
    elif editorial_review:
        raise Held('legacy_editorial_review_only_for_named_facts')
    relevant = [(o, s) for o, s in valid if o.observed_at >= baseline[0].observed_at]
    if any(competitive_digest(source) != canonical for _, source in relevant):
        raise Held('legacy_recovery_competitive_facts_changed')
    if relevant[-1][0].observed_at - baseline[0].observed_at < 3600:
        raise Held('legacy_recovery_stable_evidence_required')
    shares = (await db.scalars(select(RecapShareDecision).where(RecapShareDecision.scope.in_(
        ['edition:' + legacy_id, 'edition:' + episode_id, 'series:' + episode.series_id]))
        .order_by(RecapShareDecision.scope))).all()
    proof = dict(episode_id=episode_id, publication_id=legacy_id, expected_revision=expected_revision,
        article_id=artifact.id, article_digest=artifact.digest, imported_article_digest=row.article_digest,
        withdrawal_id=withdrawal.id, baseline_observation_id=baseline[0].id,
        latest_observation_id=episode.latest_observation_id, competitive_digest=canonical,
        approved_source_digest=digest(approved_source),
        legacy_claim_proof=claim_proof, editorial_review=editorial_review,
        corrected_digest=digest(corrected) if corrected else None,
        observation_digests=[(o.id, o.snapshot_digest) for o in observations],
        media_digest=digest([row.media_id, row.media_json]), enabled=row.enabled,
        shares=[(s.scope, s.revision, s.allowed, s.opted_out, s.token_digest) for s in shares],
        receipt_digests=sorted((r.id, digest([r.receipt_json, r.cost_microusd])) for r in receipts),
        serving_epoch=gate.epoch)
    fingerprint = digest(proof)
    report = dict(digest=fingerprint, applied=False, episode_id=episode_id,
        publication_id=legacy_id, authority_revision=row.authority_revision,
        artifact_id=artifact.id, media_id=row.media_id, competitive_digest=canonical,
        correction_revision=corrected['revision'] if corrected else None,
        provider_requests=0, added_cost_microusd=0, filesystem_verified=False,
        media_bytes_verified=bool(corrected))
    if not apply:
        return report
    if expected_digest != fingerprint:
        raise Held('recovery_preview_changed')
    if corrected:
        # Project the immutable revision before making it readable. A crash or
        # transaction rollback leaves the publication withdrawn; a retry accepts
        # only byte-identical revision content through project_analyst's fence.
        from app.services.generation.publication import project_analyst
        replacement = ContentArtifact(series_id=artifact.series_id, league_id=artifact.league_id,
            feature=artifact.feature, subject=artifact.subject, revision=corrected['revision'],
            payload_json=dump(corrected), digest=digest(corrected),
            facts_json=dump({'original_artifact_id': artifact.id, 'recovery_proof': proof}),
            provenance='reviewed_receipt_only_correction')
        if await db.scalar(select(ContentArtifact.id).where(ContentArtifact.subject == artifact.subject,
                ContentArtifact.revision == replacement.revision)):
            raise Held('legacy_recovery_revision_already_exists')
        project_analyst(cache_dir, replacement, artifact)
        db.add(replacement)
        await db.flush()
        head.artifact_id, head.revision = replacement.id, replacement.revision
        # This dedicated recovery has already projected under the control lock;
        # do not replay normal generation readiness against a historical edition.
        db.add(GenerationOutbox(key='artifact:' + replacement.id, kind='artifact', delivered=True,
            payload_json=dump({'artifact_id': replacement.id, 'expected_artifact': artifact.id,
                              'receipt_only_recovery_proof': fingerprint})))
        row.article_json = dump(public_article(corrected))
        row.article_digest = digest(public_article(corrected))
        row.article_revision = replacement.revision
        report['corrected_artifact_id'] = replacement.id
    # Original paid content, media metadata and share tombstones remain immutable.
    # A corrected article is a separate revision with an explicit recovery proof.
    row.withdrawn = False
    row.authority_revision += 1
    row.projected_revision = row.authority_revision
    episode.lifecycle, episode.hold = 'held', 'historical_approval_required'
    for attention in (await db.scalars(select(RecapAttention).where(
            RecapAttention.episode_id == episode_id, RecapAttention.reason == 'recap_facts_changed'))).all():
        attention.state = 'resolved'
    audit(db, actor_id, 'recap_false_withdrawal_recovered', legacy_id, reason,
        before={'withdrawn': True, 'authority_revision': expected_revision},
        after={'withdrawn': False, 'authority_revision': row.authority_revision, 'proof_digest': fingerprint,
               'artifact_id': artifact.id, 'corrected_artifact_id': report.get('corrected_artifact_id'),
               'competitive_digest': canonical})
    return {**report, 'applied': True, 'authority_revision': row.authority_revision}


def reviewed_slot_correction(data, source, publication, review):
    """Correct proven starter slots and source-backed opportunity terminology.

    The explicit review binds unchanged news, standings, forecasts and media;
    it never substitutes for independently checked structured period claims.
    """
    required = {'article_digest', 'media_digest', 'reviewed_sections', 'slot_corrections', 'reason'}
    if (set(review) not in (required, required | {'news_corrections'}) or review['article_digest'] != digest(data)
            or review['media_digest'] != digest([publication.media_id, publication.media_json])
            or set(review['reviewed_sections']) != {'prose', 'news', 'forecasts', 'bets', 'media'}
            or not str(review['reason']).strip() or not review['slot_corrections']):
        raise Held('legacy_editorial_review_required')
    facts = data['facts']
    names = {p['player']: p for p in facts['player_context']['players']}
    owners = {p['owner_name']: p for p in source['participants']}
    scores = {r['roster_id']: r for r in source['scores'][str(source['week'])]}
    markdown = data['markdown']
    for correction in review['slot_corrections']:
        if set(correction) != {'owner', 'player', 'points', 'old_slot', 'new_slot'}:
            raise Held('legacy_slot_correction_invalid')
        try:
            row = scores[owners[correction['owner']]['roster_id']]
            pid = names[correction['player']]['player_id']
            actual = source['roster_positions'][row['starters'].index(pid)]
            if (actual != correction['new_slot'] or actual == correction['old_slot']
                    or Decimal(str(correction['points'])) != Decimal(row['players_points'][pid])):
                raise Held('legacy_slot_correction_unproved')
        except (KeyError, ValueError, TypeError, InvalidOperation):
            raise Held('legacy_slot_correction_unproved') from None
        before = f"**{correction['player']}** dropped **{correction['points']}** from the {correction['old_slot']} slot."
        after = f"**{correction['player']}** dropped **{correction['points']}** from a {correction['new_slot']} slot."
        if markdown.count(before) != 1:
            raise Held('legacy_slot_correction_exact_match_required')
        markdown = markdown.replace(before, after, 1)
    for correction in review.get('news_corrections', []):
        if (set(correction) != {'player', 'news_id', 'count', 'before'}
                or type(correction['count']) is not int or correction['count'] < 1):
            raise Held('legacy_news_correction_invalid')
        try:
            news = [n for n in names[correction['player']]['news'] if n['id'] == correction['news_id']]
            before = correction['before']
            old = f"{correction['count']} touches"
            new = f"{correction['count']} opportunities"
            if (len(news) != 1 or not re.search(r'\b' + re.escape(new) + r'\b', news[0]['text']) or old in news[0]['text']
                    or before.count(old) != 1 or f"**{correction['player']}**" not in before
                    or len(before) > 500 or markdown.count(before) != 1):
                raise Held('legacy_news_correction_unproved')
        except (KeyError, TypeError):
            raise Held('legacy_news_correction_unproved') from None
        markdown = markdown.replace(before, before.replace(old, new, 1), 1)
    from app.services.analyst_store import AnalystEdition
    return AnalystEdition.model_validate({**data, 'markdown': markdown, 'revision': data['revision'] + 1,
        'original_markdown': None, 'correction_note': review['reason']}).model_dump()


def verify_legacy_media(publication, review):
    """Bind unchanged reviewed narration/video to every original saved byte."""
    from app.services.analyst_media import ASSETS
    media = json.loads(publication.media_json)
    if (media.get('storage') != 'legacy' or media.get('id') != publication.media_id
            or set(media.get('files', {})) != set(ASSETS)
            or review['media_digest'] != digest([publication.media_id, publication.media_json])):
        raise Held('legacy_media_review_required')
    try:
        for info in media['files'].values():
            path = Path(info['path'])
            if not path.is_absolute() or path.is_symlink() or path.stat().st_size != info['bytes']:
                raise Held('legacy_media_bytes_changed')
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != info['sha256']:
                    raise Held('legacy_media_bytes_changed')
    except (KeyError, OSError, TypeError):
        raise Held('legacy_media_bytes_unavailable') from None
