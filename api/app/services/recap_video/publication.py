"""API-only publication authority. No worker route can approve/select/share.

Task10 calls record_approval with its authenticated admin, then select_publication
in a NEW transaction (immutable object verification precedes the control lock).
Member share bootstrap exposes only an already-published article, never media.
Task11 rotates the external serving epoch and sets mode=quarantine before restore.
Neither database restore nor an outbox replay can set deployment configuration.
"""
import asyncio
import hashlib
import json
import re
import secrets
from pathlib import Path

from sqlalchemy import select, update

from app.config import get_settings
from app.services.analyst_media import ASSETS, AnalystMedia
from app.services.analyst_shares import AnalystShares
from app.services.generation.models import ContentArtifact, GenerationControl, GenerationOutbox, stamp
from app.services.generation.recap_models import (
    RecapAsset, RecapEpisode, RecapPublication, RecapPublicationApproval,
    RecapPublicationControl, RecapPublicationSelection, RecapShareDecision, RecapStage,
)
from app.services.generation.store import Conflict, Held, audit, digest, dump, lock_control, resolve_policy
from app.services.recap_video.storage import configured_store

PUBLIC_FIELDS = ('season', 'week', 'league_name', 'generated_at', 'markdown',
                 'edition_type', 'revision', 'correction_note', 'sources', 'context_note')


def mode():
    config = get_settings()
    value = config.recap_publication_mode
    if config.recap_restore_epoch and value == 'legacy':
        raise Held('public_serving_quarantined')
    if value not in ('legacy', 'database'):
        raise Held('public_serving_quarantined')
    return value


async def serving_gate(db):
    """External epoch must match explicit reconciliation; never auto-bootstrap."""
    config = get_settings()
    if config.recap_restore_epoch:
        from app.services.generation.recovery import require_restore_report
        await require_restore_report(db)
    row = await db.get(RecapPublicationControl, 'global', populate_existing=True)
    generation = await db.get(GenerationControl, 'global', populate_existing=True)
    if (config.recap_publication_mode != 'database' or not config.recap_serving_epoch
            or not row or row.quarantined or not row.reconciliation_digest
            or generation and generation.hold == 'restore_quarantine'
            or row.epoch != config.recap_serving_epoch):
        raise Held('public_serving_quarantined')
    return row


def legacy_episode_id(league_id, season, week):
    return 'legacy:' + digest([league_id, season, week])


def public_article(data):
    if data.get('edition_type') != 'roast' or not data.get('markdown'):
        raise Held('private_packet_not_public')
    return {'correction_note':None, 'sources':[], 'context_note':None,
            **{key: data[key] for key in PUBLIC_FIELDS if key in data}}


async def edition_row(db, league_id, season, week):
    return await db.scalar(select(RecapPublication).where(RecapPublication.league_id == league_id,
        RecapPublication.season == season, RecapPublication.week == week).execution_options(populate_existing=True))


async def authority_for_episode(db, episode):
    """Resolve a logical edition before correction; only legacy identity may migrate."""
    row = await db.get(RecapPublication, episode.episode_id, populate_existing=True)
    if row and (row.league_id, row.season, row.week) != (episode.league_id, episode.season, episode.week):
        raise Held('publication_edition_mismatch')
    if row is None:
        row = await edition_row(db, episode.league_id, episode.season, episode.week)
        if row and (row.episode_id != legacy_episode_id(episode.league_id, episode.season, episode.week) or row.article_id):
            raise Held('publication_identity_already_managed')
    return row


async def withdraw_edition(db, league_id, season, week, *, expected_revision, actor_id, reason):
    """Task10 commits this BEFORE correction/paid repair, even without a canonical episode.

    Keep share decisions and tokens intact: correction is not consent to re-enable sharing.
    Call behind existing authenticated correction authorization, never worker routes.
    """
    if not actor_id or not reason.strip():
        raise Held('publication_correction_reason_required')
    await lock_control(db)
    await serving_gate(db)
    row = await edition_row(db, league_id, season, week)
    if not row:
        raise Held('publication_missing')
    if row.authority_revision != expected_revision:
        raise Conflict('Publication changed. Review the current correction state.')
    row.withdrawn = True
    row.authority_revision += 1
    audit(db, actor_id, 'recap_publication_withdrawn', row.episode_id, reason)
    return dict(episode_id=row.episode_id, authority_revision=row.authority_revision)


async def edition_decision(db, identity, league_id, season, week):
    """A pre-episode decision keeps its logical-edition tombstone until adoption."""
    share = await db.get(RecapShareDecision, 'edition:'+identity, populate_existing=True)
    legacy = legacy_episode_id(league_id, season, week)
    if identity != legacy:
        prior = await db.get(RecapShareDecision, 'edition:'+legacy, populate_existing=True)
        if share and prior:
            raise Held('publication_identity_share_conflict')
        share = share or prior
    return share


async def sharing_context(db, row=None, *, league_id=None, season=None, week=None):
    if row:
        league_id, season, week = row.league_id, row.season, row.week
    row = await edition_row(db, league_id, season, week)
    episode = await db.scalar(select(RecapEpisode).where(RecapEpisode.league_id == league_id,
        RecapEpisode.season == season, RecapEpisode.week == week).execution_options(populate_existing=True))
    identity = row.episode_id if row else episode.episode_id if episode else legacy_episode_id(league_id, season, week)
    share = await edition_decision(db, identity, league_id, season, week)
    return row, episode, identity, share


async def share_state(db, row=None, **target):
    await serving_gate(db)
    _, _, _, share = await sharing_context(db, row, **target)
    return {'token': share.token if share and share.allowed and not share.opted_out else None}


async def change_share(db, row=None, *, enabled, actor_id, **target):
    await lock_control(db)
    gate = await serving_gate(db)
    row, episode, identity, share = await sharing_context(db, row, **target)
    bootstrapped = enabled and not row
    if bootstrapped:
        # This is member authorization to share an ALREADY published article,
        # never an admin media approval or a future-sharing grant.
        row = await article_share_bootstrap(db, identity, episode, target, gate)
    scope = 'edition:'+identity
    if not share:
        share = RecapShareDecision(scope=scope, revision=0)
        db.add(share)
    elif share.scope != scope:
        share.scope = scope
    if enabled and share.allowed and not share.opted_out:
        if not bootstrapped:
            return {'token': share.token}
    else:
        share.revision += 1
        share.allowed, share.opted_out = enabled, not enabled
        share.token = secrets.token_urlsafe(32) if enabled else None
        share.token_digest = hashlib.sha256(share.token.encode()).hexdigest() if share.token else None
    if row:
        row.share_revision = share.revision
        # Authority fences invalidate any prepared selection/projection on revoke.
        already_projected = row.projected_revision == row.authority_revision
        row.authority_revision += 1
        if already_projected:
            row.projected_revision = row.authority_revision
    audit(db, actor_id, 'recap_share_enabled' if enabled else 'recap_share_revoked', identity,
          'Explicit member sharing decision')
    return {'token': share.token}


async def require_episode_readiness(db, episode):
    from app.services.recap_video.readiness import require_readiness
    return await require_readiness(db, episode.series_id, dict(season=episode.season,
        week=episode.week, period_id=episode.period_id, recap_facts_digest=episode.facts_digest),
        league_id=episode.league_id, media_checkpoint=True)


async def publication_policy(db, series_id, media_id=None):
    policy = await resolve_policy(db, series_id)
    config = get_settings()
    feature = policy['policy']['features']['recap_video' if media_id else 'analyst']
    if (policy['blocked_by'] or policy['policy']['paused'] or config.generation_emergency_pause
            or not policy['epoch'] or config.generation_execution_epoch != policy['epoch']
            or feature['paused'] or feature['mode'] == 'disabled'):
        raise Held('publication_paused')
    return policy


async def article_share_bootstrap(db, identity, episode, target, gate):
    if episode:
        await require_episode_readiness(db, episode)
        from app.services.recap_video.contracts import _published_article
        article = await _published_article(db, episode)
        artifact = await db.get(ContentArtifact, article['artifact_id'])
        public = public_article(json.loads(artifact.payload_json))
        series_id, facts = episode.series_id, episode.facts_digest
        league_id, season, week = episode.league_id, episode.season, episode.week
    else:
        league_id, season, week = target['league_id'], target['season'], target['week']
        edition = AnalystShares(get_settings().cache_dir).edition(league_id, season, week)
        if not edition:
            raise Held('publication_missing')
        public, artifact, facts = public_article(edition), None, ''
        from app.services.generation.models import LeagueSeason
        league = await db.get(LeagueSeason, league_id)
        series_id = league.series_id if league else 'legacy:'+league_id
    policy = await publication_policy(db, series_id)
    row = RecapPublication(episode_id=identity, series_id=series_id, league_id=league_id, season=season, week=week,
        article_id=artifact.id if artifact else '', article_revision=public['revision'],
        article_digest=artifact.digest if artifact else digest(public), article_json=dump(public), facts_digest=facts,
        media_json='{}', share_revision=0, authority_revision=0, projected_revision=0,
        epoch=gate.epoch, policy_digest=digest(policy), published_at=stamp())
    db.add(row)
    return row


async def set_future_sharing(db, series_id, *, allowed, actor_id):
    await serving_gate(db)
    await lock_control(db)
    row = await db.get(RecapShareDecision, 'series:'+series_id, populate_existing=True)
    if not row:
        row = RecapShareDecision(scope='series:'+series_id, revision=0)
        db.add(row)
    row.revision += 1
    row.allowed, row.opted_out = allowed, not allowed
    audit(db, actor_id, 'recap_future_sharing', series_id, 'Explicit future sharing permission', after={'allowed':allowed})


async def current_scope(db, episode_id, expected_revision, media_id):
    gate = await serving_gate(db)
    episode = await db.get(RecapEpisode, episode_id, populate_existing=True)
    if not episode:
        raise Held('recap_episode_missing')
    policy = await publication_policy(db, episode.series_id, media_id)
    await require_episode_readiness(db, episode)
    from app.services.recap_video.contracts import _published_article
    article = await _published_article(db, episode)
    row = await authority_for_episode(db, episode)
    if (row.authority_revision if row else 0) != expected_revision:
        raise Conflict('Publication changed. Review the current article and media.')
    media_fence = None
    if media_id:
        stage = await db.get(RecapStage, media_id, populate_existing=True)
        if not stage or stage.state != 'succeeded' or stage.episode_id != episode_id or stage.kind != 'media_check':
            raise Held('media_checkpoint_unready')
        from app.services.recap_video.workflow import _current
        await _current(db, stage, now=stamp())
        media_fence = [stage.generation, stage.epoch, stage.input_digest, stage.result_json]
    publication_episode_id = row.episode_id if row else episode_id
    share = await edition_decision(db, publication_episode_id, episode.league_id, episode.season, episode.week)
    future = await db.get(RecapShareDecision, 'series:'+episode.series_id, populate_existing=True)
    if share and share.opted_out:
        raise Held('edition_sharing_opted_out')
    if not share or not share.allowed:
        if not future or not future.allowed or future.opted_out:
            raise Held('future_sharing_disabled')
    return dict(episode_id=episode_id, publication_episode_id=publication_episode_id,
        share_scope=share.scope if share else 'edition:'+episode_id,
        expected_revision=expected_revision, media_id=media_id,
        article=article, facts_digest=episode.facts_digest, source_digest=episode.source_digest,
        policy_digest=digest(policy), generation_epoch=policy['epoch'], serving_epoch=gate.epoch,
        share_revision=share.revision if share else 0, future_revision=future.revision if future else 0,
        media_fence=media_fence)


async def verified_media(db, episode_id, media_id):
    """Read/verify all private bytes BEFORE selection acquires control lock."""
    if media_id is None:
        return {}, ''
    from app.services.recap_video.rendering import bundle, validate_check
    stage = await db.get(RecapStage, media_id, populate_existing=True)
    if not stage or stage.episode_id != episode_id or stage.kind != 'media_check' or stage.state != 'succeeded':
        raise Held('media_checkpoint_unready')
    await validate_check(db, stage, json.loads(stage.result_json))
    render = await db.get(RecapStage, stage.predecessor_id)
    episode, files = await bundle(db, render, json.loads(render.result_json))
    if not all(name in files for name in ASSETS):
        raise Held('public_derivatives_missing')
    script = await db.get(ContentArtifact, stage.script_id)
    source = json.loads(script.payload_json) if script else {}
    authority = await db.get(RecapEpisode, episode_id)
    # Source article binding comes from the API-created script input, never worker JSON.
    if (not script or script.feature != 'recap_video' or source.get('episode_id') != episode_id
            or source.get('article_digest') != authority.article_digest
            or source.get('recap_facts_digest') != authority.facts_digest):
        raise Held('media_article_changed')
    store = configured_store()
    public = {}
    for name in ASSETS:
        asset = files[name]
        if asset.media_type != ASSETS[name]:
            raise Held('public_format_invalid')
        data = await asyncio.to_thread(store.read_range, asset.storage_key, 0, asset.size-1)
        if len(data) != asset.size or hashlib.sha256(data).hexdigest() != asset.digest:
            raise Held('public_asset_corrupt')
        public[name] = dict(asset_id=asset.id, key=asset.storage_key, sha256=asset.digest, bytes=asset.size)
    return dict(id=hashlib.sha256(media_id.encode()).hexdigest()[:32], duration_seconds=episode['duration'],
                files=public, storage='private', stage_generation=stage.generation, stage_epoch=stage.epoch), stage.script_id


async def preview_publication(db, episode_id, expected_revision, media_id):
    """Task10 displays this exact preview and submits its digest with the review."""
    media, script_id = await verified_media(db, episode_id, media_id)
    scope = await current_scope(db, episode_id, expected_revision, media_id)
    scope.update(media_digest=digest(media), script_id=script_id)
    return dict(digest=digest(scope), article=scope['article'], media=AnalystMedia.public_metadata(media or None))


async def record_approval(db, episode_id, expected_revision, media_id, *, reviewer, reason, preview_digest):
    """Called ONLY behind Task10's require_admin dependency; no worker capability."""
    if not getattr(reviewer, 'is_admin', False) or not getattr(reviewer, 'id', '') or not reason.strip():
        raise Held('publication_admin_review_required')
    media, script_id = await verified_media(db, episode_id, media_id)
    await lock_control(db)
    scope = await current_scope(db, episode_id, expected_revision, media_id)
    scope.update(media_digest=digest(media), script_id=script_id)
    if digest(scope) != preview_digest:
        raise Held('publication_preview_changed')
    row = RecapPublicationApproval(episode_id=episode_id, scope_json=dump(scope), reviewer_id=reviewer.id, reason=reason)
    db.add(row)
    await db.flush()
    audit(db, reviewer.id, 'recap_publication_reviewed', episode_id, reason)
    return {'approval_id':row.id}


async def select_publication(db, episode_id: str, expected_revision: int, media_id: str | None, approval: dict) -> dict:
    proof = await db.get(RecapPublicationApproval, approval.get('approval_id', ''))
    if not proof or proof.consumed or proof.episode_id != episode_id:
        raise Held('publication_approval_required')
    # No global lock while storage, QA, or hashing may block.
    proof_id = proof.id
    media, script_id = await verified_media(db, episode_id, media_id)
    await db.flush()
    db.expire_all()
    await lock_control(db)
    proof = await db.get(RecapPublicationApproval, proof_id, populate_existing=True)
    from app.services.recap_video.qualification import require_standing_proof
    target_evidence = await require_standing_proof(db, proof)
    scope = await current_scope(db, episode_id, expected_revision, media_id)
    scope.update(media_digest=digest(media), script_id=script_id)
    scope.update(target_evidence)
    if proof.consumed or dump(scope) != proof.scope_json:
        raise Held('publication_approval_stale')
    episode = await db.get(RecapEpisode, episode_id)
    article = await db.get(ContentArtifact, scope['article']['artifact_id'])
    source_id = scope['publication_episode_id']
    share = await db.get(RecapShareDecision, scope['share_scope'])
    row = await db.get(RecapPublication, source_id)
    if row and source_id != episode_id:
        # Current scope proved this is the same logical legacy edition under CAS.
        # Preserve permission/tombstones and history; old outbox payloads become obsolete.
        if await db.get(RecapShareDecision, 'edition:'+episode_id):
            raise Held('publication_identity_share_conflict')
        row.episode_id = episode_id
        row.series_id = episode.series_id
        await db.execute(update(RecapPublicationSelection).where(
            RecapPublicationSelection.episode_id == source_id).values(episode_id=episode_id, series_id=episode.series_id))
    if share and share.scope != 'edition:'+episode_id:
        if await db.get(RecapShareDecision, 'edition:'+episode_id):
            raise Held('publication_identity_share_conflict')
        share.scope = 'edition:'+episode_id
    if not share:
        token = secrets.token_urlsafe(32)
        share = RecapShareDecision(scope='edition:'+episode_id, revision=1, allowed=True,
            opted_out=False, token=token, token_digest=hashlib.sha256(token.encode()).hexdigest())
        db.add(share)
    if not row:
        row = RecapPublication(episode_id=episode_id, series_id=episode.series_id, league_id=episode.league_id,
            season=episode.season, week=episode.week)
        db.add(row)
    row.article_id, row.article_revision, row.article_digest = article.id, article.revision, article.digest
    row.article_json, row.facts_digest = dump(public_article(json.loads(article.payload_json))), episode.facts_digest
    row.media_id, row.media_json, row.script_id = media_id, dump(media), script_id
    row.approval_id, row.policy_digest = proof.id, scope['policy_digest']
    row.share_revision, row.authority_revision = share.revision, expected_revision+1
    row.projected_revision = 0
    row.epoch = scope['serving_epoch']
    row.enabled, row.withdrawn, row.hold = True, False, ''
    proof.consumed = True
    db.add(GenerationOutbox(key=f'recap-publication:{episode_id}:{row.authority_revision}', kind='recap_publication',
        payload_json=dump(dict(episode_id=episode_id, authority_revision=row.authority_revision))))
    audit(db, proof.reviewer_id, 'recap_publication_selected', episode_id, proof.reason)
    await db.flush()
    return dict(episode_id=episode_id, authority_revision=row.authority_revision)


async def article_current(db, row):
    if not row.article_id:
        # Imported files remain immutable source evidence; DB still gates all reads.
        data = AnalystShares(get_settings().cache_dir).edition(row.league_id, row.season, row.week)
        return bool(data and digest(public_article(data)) == row.article_digest)
    episode = await db.get(RecapEpisode, row.episode_id, populate_existing=True)
    if not episode or episode.facts_digest != row.facts_digest or episode.article_digest != row.article_digest:
        return False
    from app.services.recap_video.contracts import _published_article
    try:
        current = await _published_article(db, episode)
        return current['artifact_id'] == row.article_id and current['revision'] == row.article_revision
    except Held:
        return False


async def project_publication(db, item, cache_dir):
    await serving_gate(db)
    payload = json.loads(item.payload_json)
    row = await db.get(RecapPublication, payload['episode_id'], populate_existing=True)
    if not row or row.authority_revision != payload['authority_revision']:
        # Obsolete work acknowledged without installing any stale pointer.
        return
    share = await db.get(RecapShareDecision, 'edition:'+row.episode_id, populate_existing=True)
    if row.withdrawn or not row.enabled or not share or not share.allowed or share.opted_out or share.revision != row.share_revision:
        raise Held('publication_withdrawn')
    if not await article_current(db, row):
        raise Held('publication_article_changed')
    proof = await db.get(RecapPublicationApproval, row.approval_id)
    if proof:
        from app.services.recap_video.qualification import require_standing_proof
        await require_standing_proof(db, proof)
    if not proof or not proof.consumed:
        raise Held('publication_approval_required')
    scope = json.loads(proof.scope_json)
    future = await db.get(RecapShareDecision, 'series:'+row.series_id, populate_existing=True)
    if (future.revision if future else 0) != scope['future_revision']:
        raise Held('publication_approval_stale')
    policy = await resolve_policy(db, row.series_id)
    config = get_settings()
    if (policy['blocked_by'] or policy['policy']['paused'] or config.generation_emergency_pause
            or config.generation_execution_epoch != scope['generation_epoch'] or digest(policy) != row.policy_digest):
        raise Held('publication_paused')
    episode = await db.get(RecapEpisode, row.episode_id, populate_existing=True)
    if not episode or episode.source_digest != scope['source_digest']:
        raise Held('recap_source_changed')
    await require_episode_readiness(db, episode)
    if row.media_id:
        stage = await db.get(RecapStage, row.media_id, populate_existing=True)
        if not stage or stage.state != 'succeeded' or [stage.generation,stage.epoch,stage.input_digest,stage.result_json] != scope['media_fence']:
            raise Held('media_checkpoint_unready')
        from app.services.recap_video.workflow import _current
        await _current(db, stage, now=stamp())
    # Files are projections only. Install before acknowledging outbox.
    target = Path(cache_dir)/'recap_publications'/hashlib.sha256(row.episode_id.encode()).hexdigest()
    AnalystShares._write(target, dict(authority_revision=row.authority_revision,
        article=json.loads(row.article_json), media=json.loads(row.media_json)))
    row.projected_revision = row.authority_revision
    row.published_at = stamp()
    if row.script_id and not await db.scalar(select(RecapPublicationSelection.id).where(
            RecapPublicationSelection.episode_id == row.episode_id,
            RecapPublicationSelection.authority_revision == row.authority_revision)):
        db.add(RecapPublicationSelection(episode_id=row.episode_id, series_id=row.series_id,
            script_id=row.script_id, authority_revision=row.authority_revision))


async def published_script_selections(db, series_id):
    rows = (await db.scalars(select(RecapPublicationSelection).where(RecapPublicationSelection.series_id == series_id)
        .order_by(RecapPublicationSelection.id.desc()))).all()
    result, episodes = [], set()
    for row in rows:
        if row.episode_id not in episodes:
            episodes.add(row.episode_id)
            result.append(row.script_id)
            if len(result) == 6:
                break
    return result


async def authorize_public_read(db, token: str, bundle_id: str | None, now: int) -> dict:
    await serving_gate(db)
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise Held('public_unavailable')
    share = await db.scalar(select(RecapShareDecision).where(
        RecapShareDecision.token_digest == hashlib.sha256(token.encode()).hexdigest()).execution_options(populate_existing=True))
    if not share or not share.allowed or share.opted_out or not share.scope.startswith('edition:'):
        raise Held('public_unavailable')
    row = await db.get(RecapPublication, share.scope[8:], populate_existing=True)
    if not row or not row.enabled or row.share_revision != share.revision or row.epoch != get_settings().recap_serving_epoch:
        raise Held('public_unavailable')
    article = public_article(json.loads(row.article_json))
    withdrawn = row.withdrawn or bool(row.hold) or not await article_current(db, row)
    if withdrawn:
        if bundle_id is not None:
            raise Held('public_unavailable')
        return dict(article={**article, 'markdown':'', 'sources':[], 'context_note':None,
            'correction_note':None, 'status':'withdrawn', 'media':None}, media={})
    media = json.loads(row.media_json) if row.projected_revision == row.authority_revision else {}
    if bundle_id is not None and (not media or media['id'] != bundle_id):
        raise Held('public_unavailable')
    return dict(article={**article, 'status':'published', 'media':AnalystMedia.public_metadata(media or None)}, media=media)


def scan_legacy(cache_dir):
    """Read edition state, NOT global token indexes. No bytes are modified."""
    shares, media = AnalystShares(cache_dir), AnalystMedia(cache_dir)
    rows, holds = [], []
    for path in sorted(shares.archive.root.glob('*/shares/*.json')):
        key = str(path.relative_to(cache_dir))
        try:
            league_id = path.parent.parent.name
            season, week = map(int, path.stem.split('-'))
            target = dict(league_id=league_id, season=season, week=week)
            token = shares.state(**target).get('token')
            if token and shares.resolve_target(token) != target:
                raise ValueError('active_index_mismatch')
            edition = shares.edition(**target)
            if not edition:
                raise ValueError('published_article_missing')
            article = public_article(edition)
            manifest = media.current(target, edition)
            if manifest:
                manifest = json.loads(dump(manifest))
                manifest['storage'] = 'legacy'
                for name, info in manifest['files'].items():
                    if name not in ASSETS:
                        raise ValueError('unexpected_public_asset')
                    asset = media._root(**target)/manifest['id']/name
                    data = asset.read_bytes()
                    if hashlib.sha256(data).hexdigest() != info['sha256']:
                        raise ValueError('legacy_asset_hash_mismatch')
                    info['path'] = str(asset.resolve())
            rows.append(dict(target=target, token=token, article=article, media=manifest or {}))
        except (OSError, ValueError, KeyError, TypeError, Held):
            holds.append(key)
    return rows, holds


async def reconcile_legacy(db, cache_dir, *, expected_digest=None, apply=False, epoch=''):
    rows, holds = await asyncio.to_thread(scan_legacy, cache_dir)
    fingerprint = digest(dict(rows=rows, holds=holds))
    report = dict(digest=fingerprint, editions=len(rows), holds=holds)
    if not apply:
        return report
    if get_settings().recap_publication_mode != 'quarantine':
        raise Held('legacy_reconciliation_requires_serving_quarantine')
    if not epoch or expected_digest != fingerprint:
        raise Held('legacy_reconciliation_changed')
    await lock_control(db)
    if await db.get(RecapPublicationControl, 'global'):
        raise Held('legacy_reconciliation_already_applied')
    for source in rows:
        target, article, media = source['target'], source['article'], source['media']
        episode = await db.scalar(select(RecapEpisode).where(RecapEpisode.league_id == target['league_id'],
            RecapEpisode.season == target['season'], RecapEpisode.week == target['week']))
        episode_id = episode.episode_id if episode else legacy_episode_id(**target)
        token = source['token']
        db.add(RecapShareDecision(scope='edition:'+episode_id, revision=1, allowed=bool(token), opted_out=not bool(token),
            token=token, token_digest=hashlib.sha256(token.encode()).hexdigest() if token else None))
        db.add(RecapPublication(episode_id=episode_id, series_id=episode.series_id if episode else 'legacy:'+target['league_id'], **target,
            article_revision=article['revision'], article_digest=digest(article), article_json=dump(article), facts_digest='',
            media_id=media.get('id'), media_json=dump(media), share_revision=1, authority_revision=1,
            projected_revision=1, epoch=epoch, published_at=stamp()))
    # Malformed editions are deliberately absent and fail closed, without hiding valid editions.
    db.add(RecapPublicationControl(id='global', epoch=epoch, reconciliation_digest=fingerprint, quarantined=False))
    await db.flush()
    return report
