import asyncio
import pytest
from sqlalchemy import func, select
from tests.test_generation_postgres import pgmaker  # noqa: F401
from tests.test_recap_workflow import seed_media, fence
from app.services.generation.store import Conflict,Held
from app.services.generation.models import stamp
from app.services.generation.recap_models import RecapStage,RecapProviderAttempt,RecapBudgetAllocation,RecapRecovery
from app.services.recap_video import workflow
from app.services.recap_video.admin_actions import replacement_preview,approve_replacement


@pytest.mark.asyncio
async def test_replacement_concurrency_has_one_execution_and_one_send_authority(pgmaker,tmp_path,monkeypatch):
    # Mutation: remove global CAS/unique execution identity or permit repeated dispatch authority.
    ident,_=await seed_media(pgmaker,tmp_path,monkeypatch,'narrate')
    async with pgmaker.begin() as db:
        preview=await replacement_preview(db,ident)
    async def replace():
        try:
            async with pgmaker.begin() as db:
                return await approve_replacement(db,ident,preview_digest=preview['digest'],maximum_microusd=100,
                    actor_id='owner',reason='Synthetic replacement',disposition_evidence='Original take cannot be recovered after explicit review')
        except (Conflict,Held):
            return None
    outcomes=await asyncio.gather(*(replace() for _ in range(8)))
    assert sum(value is not None for value in outcomes)==1
    async with pgmaker.begin() as db:
        lease=await workflow.claim_stage(db,'worker',{'narrate'},stamp())
    async def send():
        try:
            async with pgmaker.begin() as db:
                return await workflow.authorize_dispatch(db,**fence(lease),worker_id='worker')
        except (Held,Conflict):
            return None
    sent=await asyncio.gather(*(send() for _ in range(8)))
    assert sum(value is not None for value in sent)==1
    async with pgmaker() as db:
        assert await db.scalar(select(func.count()).select_from(RecapStage).where(RecapStage.execution_revision==2))==4
        assert await db.scalar(select(func.count()).select_from(RecapProviderAttempt))==1


@pytest.mark.asyncio
async def test_original_unknown_and_late_receipt_remain_financial_only(pgmaker,tmp_path,monkeypatch):
    # Mutation: late original receipt reinstalls old content or clears its cost reservation without settlement.
    from tests.test_recap_corrections import test_bounded_replacement_retains_unknown_obligation_and_original_script
    await test_bounded_replacement_retains_unknown_obligation_and_original_script(pgmaker,tmp_path,monkeypatch)
    async with pgmaker.begin() as db:
        old=await db.scalar(select(RecapProviderAttempt).where(RecapProviderAttempt.state=='abandoned'))
        stage=await db.get(RecapStage,old.stage_id)
        assert stage.state=='cancelled'
        from app.services.generation.store import digest
        import json
        await workflow.record_receipt(db,old.id,{'status':200,'request':digest(json.loads(old.request_json))},worker_id=old.worker_id)
        assert old.cost_microusd==17 and stage.state=='cancelled'
        allocation=await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id==old.id))
        assert allocation.actual_microusd==17 and allocation.outstanding_microusd==0


@pytest.mark.asyncio
async def test_replacement_requires_exact_durable_authorization(pgmaker,tmp_path,monkeypatch):
    # Mutation: execution revision alone bypasses replacement authority or unrelated provider uncertainty.
    ident,_=await seed_media(pgmaker,tmp_path,monkeypatch,'narrate')
    async with pgmaker.begin() as db:
        preview=await replacement_preview(db,ident)
        await approve_replacement(db,ident,preview_digest=preview['digest'],maximum_microusd=100,
            actor_id='owner',reason='Synthetic replacement',disposition_evidence='Original take cannot be recovered after explicit review')
        lease=await workflow.claim_stage(db,'worker',{'narrate'},stamp())
        proof=await db.scalar(select(RecapRecovery).where(RecapRecovery.stage_id==lease['stage_id'],RecapRecovery.action=='bounded_replacement_authority'))
        proof.before_json='{"input_digest":"changed","script_id":"script","execution_revision":2}'
    async with pgmaker.begin() as db:
        with pytest.raises(Held,match='replacement_authorization_changed'):
            await workflow.authorize_dispatch(db,**fence(lease),worker_id='worker')
        assert await db.scalar(select(func.count()).select_from(RecapProviderAttempt))==0


@pytest.mark.asyncio
async def test_exact_recovery_request_has_one_original_worker_claim(pgmaker,tmp_path,monkeypatch):
    # Mutation: wrong worker can recover arbitrary attempts, or duplicate polling starts competing recovery work.
    from app.services.recap_video.recovery import enqueue_recovery,claim_recovery
    ident,_=await seed_media(pgmaker,tmp_path,monkeypatch,'narrate')
    async with pgmaker.begin() as db:
        lease=await workflow.claim_stage(db,'original-worker',{'narrate'},stamp())
        sent=await workflow.authorize_dispatch(db,**fence(lease),worker_id='original-worker')
        await workflow.persist_identity(db,sent['attempt_id'],{'history_item_id':'synthetic-history','request_id':'synthetic-request'},worker_id='original-worker')
        (await db.get(RecapProviderAttempt,sent['attempt_id'])).state='unknown'
        row=await enqueue_recovery(db,sent['attempt_id'],actor_id='owner',reason='Retrieve exact saved result')
        recovery_id=row.id
    async def claim(worker):
        async with pgmaker.begin() as db:return await claim_recovery(db,worker,stamp())
    assert await claim('another-worker') is None
    values=await asyncio.gather(*(claim('original-worker') for _ in range(8)))
    selected=[value for value in values if value]
    assert len(selected)==1 and selected[0]['recovery_id']==recovery_id and selected[0]['attempt_id']==sent['attempt_id']


@pytest.mark.asyncio
async def test_0018_migration_preserves_stage_receipt_and_publication_defaults(pgmaker,tmp_path,monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from app.services.generation import recap_models as models
    from app.services.generation.store import data
    ident,stage_id=await seed_media(pgmaker,tmp_path,monkeypatch,'narrate')
    async with pgmaker() as db:
        before=data(await db.get(RecapStage,stage_id))
    path=Path(__file__).parents[1]/'migrations/versions/0018_recap_qualification.py'
    spec=importlib.util.spec_from_file_location('qualification_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    async with pgmaker.kw['bind'].begin() as connection:
        def upgrade(conn):
            for model in (models.RecapRecoveryRequest,models.RecapAttention,models.RecapRecovery,models.RecapDependency,
                    models.RecapStandingAuthorization,models.RecapQualificationReview,models.RecapCalibration):
                model.__table__.drop(conn)
            conn.execute(text('ALTER TABLE recap_stages DROP CONSTRAINT uq_recap_stage'))
            conn.execute(text('ALTER TABLE recap_stages DROP COLUMN execution_revision'))
            conn.execute(text('ALTER TABLE recap_stages ADD CONSTRAINT uq_recap_stage UNIQUE (episode_id,revision,kind,chunk)'))
            conn.execute(text('ALTER TABLE recap_publication_approvals DROP COLUMN authorization_kind'))
            conn.execute(text('ALTER TABLE recap_publication_approvals DROP COLUMN authorization_id'))
            with Operations.context(MigrationContext.configure(conn)):migration.upgrade()
        await connection.run_sync(upgrade)
    async with pgmaker() as db:
        assert data(await db.get(RecapStage,stage_id))==before
        assert await db.scalar(select(func.count()).select_from(models.RecapCalibration))==0
        assert await db.scalar(select(func.count()).select_from(models.RecapRecoveryRequest))==0


@pytest.mark.asyncio
async def test_replacement_keeps_existing_public_take_readable(pgmaker,tmp_path,monkeypatch):
    # Mutation: selecting current execution for public reads hides a valid reviewed older take.
    import hashlib,json
    from app.services.generation.recap_models import RecapPublication,RecapShareDecision,RecapPublicationControl,RecapEpisode
    from app.services.generation.models import ContentArtifact
    from app.services.generation.store import dump,data
    from app.services.recap_video.publication import authorize_public_read
    ident,media_id=await seed_media(pgmaker,tmp_path,monkeypatch,'media_check')
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH','test-serving')
    token='s'*43
    async with pgmaker.begin() as db:
        (await db.get(RecapStage,media_id)).state='succeeded'
        article=await db.get(ContentArtifact,'article');episode=await db.get(RecapEpisode,ident)
        db.add(RecapPublicationControl(id='global',epoch='test-serving',reconciliation_digest='synthetic',quarantined=False))
        db.add(RecapShareDecision(scope='edition:'+ident,revision=1,allowed=True,token=token,token_digest=hashlib.sha256(token.encode()).hexdigest()))
        db.add(RecapPublication(episode_id=ident,series_id='series',league_id='synthetic',season=2026,week=4,
            article_id=article.id,article_revision=1,article_digest=episode.article_digest,article_json=article.payload_json,facts_digest=episode.facts_digest,
            media_id=media_id,media_json=dump({'id':'old-take','duration_seconds':90,'files':{'video.mp4':{'bytes':12},'audio.mp3':{'bytes':6}}}),
            share_revision=1,authority_revision=1,projected_revision=1,epoch='test-serving'))
    async with pgmaker.begin() as db:
        before=await authorize_public_read(db,token,'old-take',stamp())
        preview=await replacement_preview(db,ident)
        await approve_replacement(db,ident,preview_digest=preview['digest'],maximum_microusd=100,actor_id='owner',
            reason='Explicit new performance',disposition_evidence='Reviewed original take needs a different performance')
    async with pgmaker() as db:
        assert await authorize_public_read(db,token,'old-take',stamp())==before
        assert (await db.get(RecapStage,media_id)).state=='succeeded'


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary',['approval','selection'])
@pytest.mark.parametrize('change',['recovery','policy'])
async def test_recovered_publication_reloads_after_storage_before_lock(pgmaker,tmp_path,monkeypatch,boundary,change):
    # Mutation: let pre-storage identity-map evidence survive a concurrent committed change.
    import json
    from tests.test_recap_qualification import reviewed_recovered_fourth
    from app.services.recap_video import qualification as q,publication as p
    from app.services.generation.models import GenerationPolicy
    from app.services.generation.store import lock_control,dump
    ident,mid,_=await reviewed_recovered_fourth(pgmaker,tmp_path,monkeypatch)
    async with pgmaker.begin() as db:proof=await q.record_standing_approval(db,ident,0,mid)
    started,release=asyncio.Event(),asyncio.Event()
    async def storage(db,*args):
        # Real verifier loads these before potentially slow object-store I/O.
        attempt=await db.get(RecapProviderAttempt,'narration-0')
        policy=await db.get(GenerationPolicy,'app')
        started.set();await release.wait()
        assert attempt is not None and policy is not None
        return {},'script'
    monkeypatch.setattr(p,'verified_media',storage)
    async def publish():
        async with pgmaker.begin() as db:
            if boundary=='approval':return await q.record_standing_approval(db,ident,0,mid)
            return await p.select_publication(db,ident,0,mid,proof)
    pending=asyncio.create_task(publish())
    await asyncio.wait_for(started.wait(),5)
    try:
        async with pgmaker.begin() as db:
            await asyncio.wait_for(lock_control(db),5)  # No storage work under the global lock.
            if change=='recovery':
                attempt=await db.get(RecapProviderAttempt,'narration-0')
                value=json.loads(attempt.recovery_receipt_json);value['audio_sha256']='changed'
                attempt.recovery_receipt_json=dump(value)
            else:
                row=await db.get(GenerationPolicy,'app')
                value=json.loads(row.value_json);value['features']['recap_video']['paused']=True;row.value_json=dump(value)
    finally:release.set()
    with pytest.raises(Held):await pending
    from app.services.generation.recap_models import RecapEpisode
    async with pgmaker() as db:assert await p.authority_for_episode(db,await db.get(RecapEpisode,ident)) is None
