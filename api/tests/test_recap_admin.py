import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select,func
from app.services.generation.store import dump,Held
from app.services.generation.recap_models import RecapStage,RecapPublicationApproval,RecapQualificationReview


@pytest.mark.asyncio
async def test_http_preview_approval_uses_actual_digest_and_separate_selection_transaction(client,maker,tmp_path,monkeypatch):
    # Mutation: trust a client success flag, reuse the preview lock during selection I/O, or auto-grant first-episode standing policy.
    from tests.test_recap_workflow import seed_media
    from app.services.recap_video import publication as p,qualification as q,elevenlabs
    from app.services.generation import recap_models as m
    from app.services.generation.models import ProviderAttempt
    from app.auth.deps import require_admin
    from app.db.session import get_db
    from app.main import app
    ident,mid=await seed_media(maker,tmp_path,monkeypatch,'media_check')
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH','test-serving')
    monkeypatch.setattr(elevenlabs,'preflight_config',lambda:{'voice':'synthetic'})
    monkeypatch.setattr(q,'current_versions',lambda:{'renderer':'synthetic'})
    async with maker.begin() as db:
        (await db.get(RecapStage,mid)).state='succeeded'
        db.add(m.RecapPublicationControl(id='global',epoch='test-serving',reconciliation_digest='synthetic',quarantined=False))
        db.add(m.RecapShareDecision(scope='series:series',allowed=True,opted_out=False))
        db.add(m.RecapCalibration(id='calibration',series_id='series',season=2026,config_json='{"voice":"synthetic"}',
            metadata_json='{}',rate_json='{}',versions_json='{"renderer":"synthetic"}',evidence_json='{}',actor_id='owner'))
        db.add(m.RecapProviderAttempt(id='narration',stage_id='synthetic-paid',episode_id=ident,series_id='series',operation_id='job',
            provider='elevenlabs',account_key='primary',worker_id='worker',generation=1,epoch='test-epoch',request_digest='request',
            request_json='{}',pricing_json='{}',authority_digest='authority',state='received',cost_microusd=100))
        db.add(ProviderAttempt(operation_id='job',stage=0,generation=1,request_digest='synthetic',request_json='{}',model='synthetic',state='received',cost_microusd=10))
    async def dependency():
        async with maker() as db:
            yield db
            await db.commit()
    app.dependency_overrides[get_db]=dependency
    app.dependency_overrides[require_admin]=lambda:SimpleNamespace(id='owner',is_admin=True)
    original_lock=p.lock_control
    async def tracked_lock(db):
        value=await original_lock(db)
        db.info['control_transaction']=db.sync_session.get_transaction()
        return value
    monkeypatch.setattr(p,'lock_control',tracked_lock)
    original_select=p.select_publication
    async def fresh_selection(db,*args,**kwargs):
        assert not db.in_transaction()
        return await original_select(db,*args,**kwargs)
    monkeypatch.setattr(p,'select_publication',fresh_selection)
    async def storage_checked(db,*args):
        # This marker is set by the actual control-lock wrapper above.
        locked=db.info.get('control_transaction')
        assert locked is None or locked is not db.sync_session.get_transaction()
        return {},'script'
    monkeypatch.setattr(p,'verified_media',storage_checked)
    base=f'/api/admin/generation/recap-episodes/{ident}'
    preview=client.post(base+'/preview',json={'expected_revision':0,'media_id':mid})
    assert preview.status_code==200,preview.text
    body={'expected_revision':0,'media_id':mid,'preview_digest':'a'*64,'reason':'Reviewed actual finished preview',
        'checks':{key:'Synthetic test evidence only, not release qualification' for key in ('factual_coverage','performance','physical_phone','message_preview')}}
    assert client.post(base+'/approve',json=body).status_code==409
    body['preview_digest']=preview.json()['digest']
    approved=client.post(base+'/approve',json=body)
    assert approved.status_code==200,approved.text
    assert client.post(base+'/approve',json=body).status_code==409
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(RecapQualificationReview))==1
        assert await db.scalar(select(func.count()).select_from(RecapPublicationApproval))==1
        assert await db.scalar(select(func.count()).select_from(m.RecapStandingAuthorization))==0


@pytest.mark.asyncio
async def test_http_recovery_conflict_and_admin_permission_do_not_mutate(client,maker,tmp_path,monkeypatch):
    # Mutation: ignore stale episode revision or trust detached auth after admin removal.
    from tests.test_recap_workflow import seed_media
    from app.db.session import get_db
    from app.main import app
    from app.auth.deps import require_admin
    from app.db.models import User
    ident,_=await seed_media(maker,tmp_path,monkeypatch,'render')
    async def dependency():
        async with maker() as db:
            yield db
            await db.commit()
    app.dependency_overrides[get_db]=dependency
    app.dependency_overrides[require_admin]=lambda:SimpleNamespace(id='owner',is_admin=True)
    base=f'/api/admin/generation/recap-episodes/{ident}'
    before=client.get(base)
    assert before.status_code==200,before.text
    body={'action':'skip_video','expected_revision':'a'*64,'reason':'Synthetic skip'}
    assert client.post(base+'/actions',json=body).status_code==409
    async with maker.begin() as db:(await db.get(User,'owner')).is_admin=False
    body['expected_revision']=before.json()['revision']
    assert client.post(base+'/actions',json=body).status_code==409
    async with maker() as db:
        assert not (await db.scalars(select(RecapStage).where(RecapStage.state=='cancelled'))).all()
