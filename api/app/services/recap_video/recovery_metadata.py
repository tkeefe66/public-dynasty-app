"""Exact original-byte reconstruction for older history-recovery workers."""
import asyncio
import hashlib
import json
import uuid

from sqlalchemy import select

from app.services.generation.models import GenerationAudit
from app.services.generation.recap_models import RecapAsset
from app.services.generation.store import Conflict, dump


async def normalize_recovery_metadata(db, attempt, receipt, original):
    from app.services.recap_video.elevenlabs import restore_exact_mp3_metadata
    from app.services.recap_video.storage import configured_store
    asset_ref=receipt.get('asset',{})
    asset=await db.get(RecapAsset,asset_ref.get('asset_id',''))
    if (receipt.get('outcome')!='recovered' or receipt.get('request_digest')!=attempt.request_digest
            or original.get('request_digest')!=attempt.request_digest or original.get('identity')!=receipt.get('identity')
            or not asset or asset.stage_id!=attempt.stage_id or asset.generation!=attempt.generation
            or asset.media_type!='audio/mpeg' or not 0<asset.size<=64*1024*1024
            or asset_ref!=dict(asset_id=asset.id,digest=asset.digest,size=asset.size)
            or receipt.get('audio_sha256')!=asset.digest or receipt.get('audio_size')!=asset.size):
        raise Conflict('Recovered metadata source does not match owned request and asset')
    audits=(await db.scalars(select(GenerationAudit).where(GenerationAudit.target==attempt.id,
        GenerationAudit.action=='recap_recovery_metadata_normalized'))).all()
    if audits:
        if len(audits)!=1 or audits[0].before_json!=dump(receipt):
            raise Conflict('Recovery normalization conflicts with retained evidence')
        normalized=json.loads(audits[0].after_json)
        if attempt.recovery_receipt_json!=dump(normalized):
            raise Conflict('Recovery normalization no longer matches saved receipt')
        return normalized
    if attempt.recovery_receipt_json:
        raise Conflict('Recovery receipt conflicts with retained evidence')
    store=configured_store()
    try:
        downloaded=await asyncio.to_thread(store.read_range,asset.storage_key,0,asset.size-1)
        if len(downloaded)!=asset.size or hashlib.sha256(downloaded).hexdigest()!=asset.digest:
            raise ValueError('Stored history audio hash differs from upload')
        restored=restore_exact_mp3_metadata(downloaded,original)
    except (ValueError,OSError) as exc:
        raise Conflict('Recovered audio cannot reproduce the original response exactly') from exc
    sha=hashlib.sha256(restored).hexdigest()
    key=str(uuid.uuid4())
    # Immutable write precedes DB reference. Rollback leaves only a grace-period
    # orphan, never an accepted receipt pointing at absent bytes.
    await asyncio.to_thread(store.put_verified,key,restored,sha)
    normalized_asset=RecapAsset(stage_id=attempt.stage_id,generation=attempt.generation,
        storage_key=key,digest=sha,size=len(restored),media_type='audio/mpeg')
    db.add(normalized_asset)
    await db.flush()
    normalized={**receipt,'audio_sha256':sha,'audio_size':len(restored),
        'asset':dict(asset_id=normalized_asset.id,digest=sha,size=len(restored))}
    db.add(GenerationAudit(actor_id=attempt.worker_id,action='recap_recovery_metadata_normalized',target=attempt.id,
        reason='Exact original SHA restored by ID3 metadata normalization; MPEG payload unchanged',
        before_json=dump(receipt),after_json=dump(normalized)))
    return normalized
