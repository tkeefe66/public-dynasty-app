"""Disposable Postgres: real contention against committed current authority."""
import asyncio
import pytest
from tests.test_recap_publication import approve_current
from types import SimpleNamespace
from sqlalchemy import select, func

from tests.test_generation_postgres import pgmaker  # noqa: F401
from tests.test_recap_publication import ready_article
from app.services.generation.models import GenerationOutbox
from app.services.generation.recap_models import RecapPublication, RecapShareDecision
from app.services.generation.store import Held, Conflict, lock_control
from app.services.recap_video import publication as p


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['source_hold','script_head'])
async def test_projection_authority_changed_after_selection_on_postgres(pgmaker,tmp_path,monkeypatch,change):
    from tests.test_recap_publication import test_projector_rechecks_current_media_authority_without_storage_io
    await test_projector_rechecks_current_media_authority_without_storage_io(pgmaker,tmp_path,monkeypatch,change)


@pytest.mark.asyncio
async def test_member_article_bootstrap_has_one_token_under_contention(pgmaker,tmp_path,monkeypatch):
    ident = await ready_article(pgmaker,tmp_path,monkeypatch)
    async with pgmaker.begin() as db:
        (await db.get(RecapShareDecision,'series:series')).allowed = False
    async def enable():
        async with pgmaker.begin() as db:
            return await p.change_share(db,league_id='synthetic',season=2026,week=4,enabled=True,actor_id='member')
    values = await asyncio.gather(*(enable() for _ in range(8)))
    assert len({value['token'] for value in values}) == 1
    async with pgmaker() as db:
        assert await db.scalar(select(func.count()).select_from(RecapPublication)) == 1
        assert (await db.get(RecapPublication,ident)).authority_revision == 1
        assert (await db.get(RecapShareDecision,'edition:'+ident)).revision == 1


@pytest.mark.asyncio
async def test_legacy_identity_adoption_is_atomic_on_postgres(pgmaker, tmp_path, monkeypatch):
    # Exercise real primary-key migration and preserved history under the control CAS.
    from tests.test_recap_publication import test_legacy_adoption_preserves_token_permissions_history_and_episode
    await test_legacy_adoption_preserves_token_permissions_history_and_episode(pgmaker,tmp_path,monkeypatch)


@pytest.mark.asyncio
async def test_one_selection_wins_approval_race(pgmaker, tmp_path, monkeypatch):
    # Mutation: reusing stale identity-map proof after waiting on control lock.
    ident = await ready_article(pgmaker, tmp_path, monkeypatch)
    async with pgmaker.begin() as db:
        proof = await approve_current(db, ident, 0, None, reviewer=SimpleNamespace(id='admin', is_admin=True), reason='Synthetic preview')
    async def attempt():
        try:
            async with pgmaker.begin() as db:
                return await p.select_publication(db, ident, 0, None, proof)
        except (Held, Conflict):
            return None
    assert len([r for r in await asyncio.gather(*(attempt() for _ in range(8))) if r]) == 1
    async with pgmaker() as db:
        assert await db.scalar(select(func.count()).select_from(RecapPublication)) == 1
        assert await db.scalar(select(func.count()).select_from(GenerationOutbox).where(GenerationOutbox.kind=='recap_publication')) == 1


@pytest.mark.asyncio
async def test_revoke_committed_during_verification_wins(pgmaker, tmp_path, monkeypatch):
    # Mutation: object verification locks control or stale approval bypasses opt-out.
    ident = await ready_article(pgmaker, tmp_path, monkeypatch)
    async with pgmaker.begin() as db:
        proof = await approve_current(db, ident, 0, None, reviewer=SimpleNamespace(id='admin', is_admin=True), reason='Synthetic preview')
    entered, release = asyncio.Event(), asyncio.Event()
    original = p.verified_media
    async def delayed(*args):
        entered.set()
        await release.wait()
        return await original(*args)
    monkeypatch.setattr(p, 'verified_media', delayed)
    async def selection():
        async with pgmaker.begin() as db:
            await p.select_publication(db, ident, 0, None, proof)
    task = asyncio.create_task(selection())
    await entered.wait()
    async with pgmaker.begin() as db:
        await asyncio.wait_for(lock_control(db), 2)
        db.add(RecapShareDecision(scope='edition:'+ident, allowed=False, opted_out=True))
    release.set()
    with pytest.raises(Held, match='edition_sharing_opted_out'):
        await task
    async with pgmaker() as db:
        assert await db.get(RecapPublication, ident) is None


@pytest.mark.asyncio
async def test_stale_outbox_never_installs_superseded_pointer(pgmaker, tmp_path, monkeypatch):
    # Mutation: outbox payload overrides later withdrawal/authority revision.
    from app.services.generation.publication import drain
    ident = await ready_article(pgmaker, tmp_path, monkeypatch)
    async with pgmaker.begin() as db:
        proof = await approve_current(db, ident, 0, None, reviewer=SimpleNamespace(id='admin', is_admin=True), reason='Synthetic preview')
    async with pgmaker.begin() as db:
        await p.select_publication(db, ident, 0, None, proof)
    async with pgmaker.begin() as db:
        await lock_control(db)
        row = await db.get(RecapPublication, ident)
        row.authority_revision += 1
        row.withdrawn = True
    await drain(pgmaker, tmp_path)
    async with pgmaker() as db:
        row = await db.get(RecapPublication, ident)
        assert row.withdrawn and row.projected_revision == 0
        assert not (tmp_path/'recap_publications').exists()
        item = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.kind=='recap_publication'))
        assert item.delivered


@pytest.mark.asyncio
async def test_additive_migration_preserves_existing_episode(pgmaker, tmp_path, monkeypatch):
    # Mutation: migration rewrites or drops existing episode/budget history.
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.services.generation.recap_models import RecapEpisode, RecapPublicationApproval, RecapPublicationControl, RecapPublicationSelection
    from app.services.generation.store import data
    from tests.test_recap_video_script import seed
    ident, _ = await seed(pgmaker,tmp_path,monkeypatch)
    async with pgmaker() as db:
        before = data(await db.get(RecapEpisode,ident))
    module_path = Path(__file__).parents[1]/'migrations/versions/0017_recap_publication.py'
    spec = importlib.util.spec_from_file_location('publication_migration',module_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = pgmaker.kw['bind']
    async with engine.begin() as connection:
        def upgrade(conn):
            for model in (RecapPublicationSelection,RecapPublicationApproval,RecapPublication,RecapShareDecision,RecapPublicationControl):
                model.__table__.drop(conn)
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        await connection.run_sync(upgrade)
    async with pgmaker() as db:
        assert data(await db.get(RecapEpisode,ident)) == before
        assert await db.scalar(select(func.count()).select_from(RecapPublication)) == 0
        assert await db.get(RecapPublicationControl,'global') is None
