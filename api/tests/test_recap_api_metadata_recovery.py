import hashlib
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.services.generation.models import GenerationAudit, stamp
from app.services.generation.recap_models import RecapAsset, RecapProviderAttempt
from app.services.generation.store import Conflict, Held, dump
from app.services.recap_video import workflow as work
from app.services.recap_video.storage import LocalPrivateMediaStore
from tests.test_recap_workflow import seed_media, fence
from tests.test_recap_elevenlabs import tagged_audio


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['valid','payload','foreign','generation','request','bytes'])
async def test_api_metadata_recovery_preserves_original_and_replays_without_new_asset(maker,tmp_path,monkeypatch,change):
    # Mutation: API trusts worker metadata, changes original evidence, or creates duplicate assets on replay.
    await seed_media(maker,tmp_path,monkeypatch,'narrate')
    store=LocalPrivateMediaStore(tmp_path/'objects')
    monkeypatch.setattr('app.services.recap_video.storage.configured_store',lambda:store)
    original=tagged_audio('Lavf63.1.102')
    downloaded=tagged_audio('Lavf63.1.102',terminated=False,geob=True,padding=0,
        payload=b'\xff\xfbchanged' if change=='payload' else b'\xff\xfbsynthetic-mpeg')
    async with maker.begin() as db:
        lease=await work.claim_stage(db,'narrator',{'narrate'},stamp())
        authority=await work.authorize_dispatch(db,**fence(lease),worker_id='narrator')
        attempt=await db.get(RecapProviderAttempt,authority['attempt_id'])
        identity={'request_id':'synthetic-request','history_item_id':'synthetic-history'}
        attempt.identity_json=dump([identity]);attempt.cost_microusd=17;attempt.state='received'
        original_receipt=dump(dict(identity=identity,request_digest=attempt.request_digest,audio_sha256=hashlib.sha256(original).hexdigest(),audio_size=len(original)))
        attempt.receipt_json=original_receipt
        key=str(uuid.uuid4());sha=hashlib.sha256(downloaded).hexdigest()
        store.put_verified(key,downloaded,sha)
        asset=RecapAsset(stage_id='foreign' if change=='foreign' else attempt.stage_id,
            generation=attempt.generation+1 if change=='generation' else attempt.generation,
            digest='b'*64 if change=='bytes' else sha,size=len(downloaded),media_type='audio/mpeg',storage_key=key)
        db.add(asset);await db.flush()
        receipt=dict(outcome='recovered',identity=identity,request_digest='wrong' if change=='request' else attempt.request_digest,
            audio_sha256=asset.digest,audio_size=asset.size,asset=dict(asset_id=asset.id,digest=asset.digest,size=asset.size))
        if change!='valid':
            with pytest.raises((Held,Conflict,ValueError)): await work.persist_recovery_receipt(db,attempt.id,receipt,worker_id='narrator')
            assert attempt.recovery_receipt_json is None
            return
        await work.persist_recovery_receipt(db,attempt.id,receipt,worker_id='narrator')
        normalized=json.loads(attempt.recovery_receipt_json)
        assert normalized['audio_sha256']==hashlib.sha256(original).hexdigest()
        restored=await db.get(RecapAsset,normalized['asset']['asset_id'])
        assert restored.id!=asset.id and store.read_range(restored.storage_key,0,restored.size-1)==original
        assert attempt.receipt_json==original_receipt and attempt.cost_microusd==17
        count=await db.scalar(select(func.count()).select_from(RecapAsset))
        await work.persist_recovery_receipt(db,attempt.id,receipt,worker_id='narrator')
        assert await db.scalar(select(func.count()).select_from(RecapAsset))==count
        audit=await db.scalar(select(GenerationAudit).where(GenerationAudit.action=='recap_recovery_metadata_normalized'))
        assert json.loads(audit.before_json)==receipt
