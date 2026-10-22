import pytest
from sqlalchemy import select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation
from app.services.generation.recap_models import RecapBudgetAllocation, RecapStage
from app.services.generation.store import Held
from app.services.recap_video import editorial as e
from app.services.recap_video.editorial_amendment import retract_unused_editorial
from tests.test_recap_editorial import setup, preview


@pytest.mark.asyncio
async def test_unused_retirement_preserves_artifact_releases_envelope_and_allows_new_preview(maker,tmp_path,monkeypatch):
    # Mutation: cancellation deletes paid evidence or permits old approval proof to resume.
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        result=await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        artifact=await db.get(ContentArtifact,result['artifact_id']); original=artifact.payload_json
        await retract_unused_editorial(db,artifact_id=artifact.id,actor_id='owner',reason='Correct scene plan before any media starts')
        assert artifact.payload_json==original
        assert await db.get(ArtifactHead,artifact.subject) is None
        assert (await db.get(GenerationOperation,result['operation_id'])).state=='cancelled'
        allocation=await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.operation_id==result['operation_id']))
        assert allocation.actual_microusd==0
        with pytest.raises(Held): await e.require_editorial_artifact(db,artifact)
        next_preview=await preview(db,script,review)
        assert next_preview['new_writer_calls']==0
        corrected=await e.apply_editorial(db,preview_id=next_preview['preview_id'],preview_digest=next_preview['digest'],actor_id='owner',reason='Approve corrected scene plan')
        replacement=await db.get(ContentArtifact,corrected['artifact_id'])
        assert replacement.revision==artifact.revision+1
        assert (await db.get(ArtifactHead,artifact.subject)).artifact_id==replacement.id
        await e.require_editorial_artifact(db,replacement)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['stage','managed','unaudited'])
async def test_retirement_rejects_used_or_non_editorial_and_unaudited_history(maker,tmp_path,monkeypatch,change):
    # Mutation: cancelled artifacts are generically exempted or media work can be retired.
    ident,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        result=await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        artifact=await db.get(ContentArtifact,result['artifact_id'])
        if change=='stage': db.add(RecapStage(episode_id=ident,kind='narrate',operation_id=result['operation_id'],script_id=artifact.id,revision=1,input_json='{}',input_digest='x',policy_digest='x'))
        elif change=='managed': artifact.provenance='managed'
        else:
            (await db.get(GenerationOperation,result['operation_id'])).state='cancelled'
            await db.delete(await db.get(ArtifactHead,artifact.subject))
            await db.flush()
            with pytest.raises(Held): await preview(db,script,review)
            return
        with pytest.raises(Held): await retract_unused_editorial(db,artifact_id=artifact.id,actor_id='owner',reason='Retire')


@pytest.mark.asyncio
async def test_retirement_skips_only_new_renderability_gate(maker,tmp_path,monkeypatch):
    # Mutation: rendering failure blocks safe retirement, or runtime bypasses that gate too.
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        result=await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        artifact=await db.get(ContentArtifact,result['artifact_id'])
        def unsupported(*args): raise ValueError('Scene plan no longer accepts this coverage')
        monkeypatch.setattr('media.timeline.scene_plan',unsupported)
        with pytest.raises(Held): await e.require_editorial_artifact(db,artifact)
        assert (await retract_unused_editorial(db,artifact_id=artifact.id,actor_id='owner',reason='Correct unused scene coverage'))['retired']
