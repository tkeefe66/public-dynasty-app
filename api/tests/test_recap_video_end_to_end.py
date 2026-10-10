"""Opt-in disposable PostgreSQL + final Linux image + authenticated Next acceptance.

No provider network: only provider HTTP and ASR transcript are synthetic. Stage
admission, receipts, validators, renderer, publication and auth are production.
Run alone: its PostgreSQL fixture deliberately recreates the *_tests schema.
"""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

import httpx
import pytest
from sqlalchemy import select
from tests.test_generation_postgres import pgmaker  # noqa: F401
from tests.test_generation_gateway import seed_job, BODY, REQUEST
from tests.test_recap_readiness import snapshot
from tests.test_recap_video_script import approved_payload
from tests.test_recap_elevenlabs import RATE
from app.services.generation import models as g, recap_models as m
from app.services.generation.store import digest, dump, Held, OwnershipLost
from app.services.recap_video import workflow as w, qualification as q, elevenlabs as el, publication as p

pytestmark = pytest.mark.skipif(os.getenv('RECAP_ACCEPTANCE') != '1', reason='Opt-in isolated PostgreSQL/Linux/Next acceptance')
ROOT = Path(__file__).resolve().parents[2]


class CountedProse:
    """Physical provider sends; gateway retries must reuse saved unique identities."""
    def __init__(self, maker):
        self.maker = maker
        self.calls = []
        self.content = None
    async def send(self, request):
        from app.services.generation.transport import Receipt
        async with self.maker() as db:
            pending = list((await db.scalars(select(g.ProviderAttempt).where(g.ProviderAttempt.state == 'dispatching'))).all())
            assert len(pending) == 1
            assert pending[0].request_digest == digest(request)
            identity = pending[0].id
        self.calls.append(identity)
        assert self.calls.count(identity) == 1, 'Duplicate physical prose send'
        return Receipt(200, dump({**BODY, 'id':'synthetic-'+str(len(self.calls)), 'model':request['model'],
            'content':self.content or BODY['content'], 'stop_reason':'tool_use' if self.content else 'end_turn'}),
            {'request-id':'synthetic-'+str(len(self.calls))})


async def asset(maker, store, lease, data, mime, identity=None):
    identity = identity or str(uuid.uuid4())
    sha = hashlib.sha256(data).hexdigest()
    key = str(uuid.uuid4())
    store.put_verified(key, data, sha)
    async with maker.begin() as db:
        db.add(m.RecapAsset(id=identity, stage_id=lease['stage_id'], generation=lease['generation'],
            digest=sha, size=len(data), media_type=mime, storage_key=key))
    return dict(asset_id=identity, digest=sha, size=len(data))


def fence(lease):
    return {key:lease[key] for key in ('stage_id','generation','epoch','input_digest')}


async def claim(maker, kind):
    async with maker.begin() as db:
        lease = await w.claim_stage(db, 'acceptance-worker', {kind}, g.stamp())
    assert lease and lease['capability'] == kind
    return lease


async def complete(maker, lease, result):
    async with maker.begin() as db:
        value = await w.complete_stage(db, **fence(lease), worker_id='acceptance-worker', result=result)
        assert value['state'] == 'succeeded', value
    # Crash after durable checkpoint: a new process cannot complete or claim it again.
    async with maker.begin() as db:
        with pytest.raises(OwnershipLost):
            await w.complete_stage(db, **fence(lease), worker_id='acceptance-worker', result=result)
        assert await w.claim_stage(db, 'restarted-worker', {lease['capability']}, g.stamp()) is None


async def linux_stage(maker, store, lease, directory):
    directory.mkdir()
    incoming = {}
    async with maker() as db:
        for identity in lease['allowed_assets']:
            row = await db.get(m.RecapAsset, identity)
            (directory/identity).write_bytes(store.read_range(row.storage_key, 0, row.size-1))
            incoming[identity] = {'file':identity}
    (directory/'lease.json').write_text(dump(lease))
    (directory/'assets.json').write_text(dump(incoming))
    command = ['docker','run','--rm','--network','none','--memory','2g','--tmpfs','/scratch:rw,size=4g',
        '--cap-add','SYS_ADMIN','--security-opt','seccomp=unconfined','--security-opt','apparmor=unconfined',
        '--security-opt','systempaths=unconfined','-e','BOUNDARY_SECRET=recap-boundary-sentinel',
        '-e','TMPDIR=/scratch','-v',f'{directory}:/exchange',os.environ['RECAP_ACCEPTANCE_IMAGE'],
        'python','scripts/check_recap_media_runtime.py','--acceptance-dir','/exchange']
    result = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    saved = json.loads((directory/'result.json').read_text())
    assert saved['boundary']['isolated'] and saved['result']['status'] == 'ok', saved
    for identity, item in saved['assets'].items():
        await asset(maker, store, lease, (directory/item['file']).read_bytes(), item['media_type'], identity)
    await complete(maker, lease, saved['result'])
    return saved


async def paid_artifact(maker, transport, job_id, payload, tool_blocks=None):
    from app.services.generation.gateway import Gateway
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.features import ValidatedOutput
    async with maker.begin() as db:
        job = await db.get(g.GenerationOperation, job_id)
        job.state, job.generation, job.lease_until = 'running', 1, g.stamp()+600
        policy = json.loads(job.policy_json)['policy']['features'][job.feature]
        request_digest = job.request_digest
    for number in (1,2):
        transport.content = tool_blocks[number-1] if tool_blocks else None
        request = {**REQUEST, 'model':policy['model' if number == 1 else 'review_model']}
        first = await Gateway(maker, transport, epoch='test-epoch').invoke(job_id, 1, number, request)
        # Restart after provider receipt, before artifact save; no physical resend.
        assert await Gateway(maker, transport, epoch='test-epoch').invoke(job_id, 1, number, request) == first
    async with maker.begin() as db:
        saved = await save_artifact(db, job_id, 1, ValidatedOutput(payload, digest(payload), request_digest, 2))
    return saved


async def automatic_job(maker, candidate):
    from app.services.generation.worker import admit_automatic
    await admit_automatic(maker)
    async with maker() as db:
        job = await db.scalar(select(g.GenerationOperation).where(g.GenerationOperation.candidate_key == candidate.key))
        assert job and job.actor_kind == 'scheduler', 'Automatic admission did not create scheduler-owned work'
        return job


async def episode(maker, tmp_path, store, prose, narration_calls, week, metadata, *, automatic=False):
    from app.services.recap_video.readiness import observe_period
    from app.services.recap_video.contracts import EpisodeKey
    from app.services.recap_video.periods import build_participants, eligible_release
    from app.services.recap_video.collector import edition_from_snapshot
    from app.services.generation.planner import observe
    from app.services.generation.commands import authorize_candidate
    from app.services.generation.publication import drain
    from app.services.recap_video.audio import MODEL_REVISION, MODEL_SHA256
    source = snapshot()
    source.update(week=week, period_id=str(week), nfl_weeks=[week], scores={str(week):source['scores']['4']},
        starters={str(week):source['starters']['4']}, current_period_id=str(week))
    source['participants'][0]['owner_name']='Avery'
    source['participants'][1]['owner_name']='Blake'
    source.update(build_participants(source['participants'], source['scores'], source['bracket'], source))
    start = eligible_release('2026-10-11') + (week-4)*604800
    source['eligible_at'] = start
    async with maker.begin() as db:
        (await db.get(g.LeagueSeason,'synthetic')).latest_week = week
        ident = await observe_period(db, EpisodeKey('series',2026,str(week)), source, start-3600)
        assert (await db.get(m.RecapEpisode,ident)).admitted_at == 0
        await observe_period(db, EpisodeKey('series',2026,str(week)), source, start)
        current = await db.get(m.RecapEpisode,ident)
        assert current.lifecycle == 'ready'
        article = {**edition_from_snapshot(source,generated_at=start), 'edition_type':'roast',
            'markdown':f'# Week {week}\n\nAvery and Blake tied. Synthetic reviewed recap.'}
        candidate = await observe(db, series_id='series',league_id='synthetic',feature='analyst',
            subject=f'article-{week}',event=str(week),payload={'edition':article,'season':2026,'week':week,
                'period_id':str(week),'recap_facts_digest':current.facts_digest,'event_at':start})
        if not automatic:
            job = await authorize_candidate(db,candidate.key,actor_id='owner',actor_kind='admin',reason='Synthetic article review',authorization_key=f'article-{week}')
    if automatic:
        job = await automatic_job(maker,candidate)
    written = await paid_artifact(maker,prose,job.id,article)
    await drain(maker,tmp_path)
    await drain(maker,tmp_path)  # projection crash/restart is idempotent
    async with maker.begin() as db:
        assert (await db.get(m.RecapEpisode,ident)).article_digest == written.digest
        if not automatic:
            await w.prepare_preflight(db,ident,actor_id='owner',reason='Synthetic account metadata fixture')
    if automatic:
        await w.advance_media(maker)
        await w.advance_media(maker)  # Repeated ticks retain one claimable free challenge.
        async with maker() as db:
            pending = list((await db.scalars(select(m.RecapStage).where(m.RecapStage.episode_id == ident))).all())
            assert len(pending) == 1 and pending[0].kind == 'preflight' and pending[0].state == 'queued'
            assert not await db.scalar(select(m.RecapProviderAttempt.id).where(m.RecapProviderAttempt.stage_id == pending[0].id))
    lease = await claim(maker,'preflight')
    await complete(maker,lease,{'status':'ok','asset_ids':[],'report':metadata})
    if automatic:
        await w.advance_media(maker)
    async with maker.begin() as db:
        if automatic:
            candidates = (await db.scalars(select(g.GenerationCandidate).where(g.GenerationCandidate.feature == 'recap_video'))).all()
            candidate = next(c for c in candidates if json.loads(c.payload_json).get('episode_id') == ident)
        else:
            candidate = await w.prepare_episode_script(db,ident,cache_dir=tmp_path)
        saved = json.loads(candidate.payload_json)
        payload = approved_payload(saved)
        payload['script']['opening']='Welcome.'
        payload['script']['closing']='That is all.'
        payload['script']['segments'][0]['text']='Avery and Blake tied.'
        if not automatic:
            job = await authorize_candidate(db,candidate.key,actor_id='owner',actor_kind='admin',reason='Synthetic script review',authorization_key=f'script-{week}')
    if automatic:
        job = await automatic_job(maker,candidate)
    script = payload['script']
    blocks = [[{'type':'tool_use','id':'synthetic-tool','name':name,'input':value}] for name,value in (
        ('submit_script',{k:v for k,v in script.items() if k != 'reviews'}),('review_script',script['reviews'][-1]))]
    artifact_row = await paid_artifact(maker,prose,job.id,payload,blocks)
    if automatic:
        await w.advance_media(maker)
    async with maker.begin() as db:
        stages = await w.start_media(db,artifact_row.id)
        ids = [row.id for row in stages]
    async with maker.begin() as db:
        assert [row.id for row in await w.start_media(db,artifact_row.id)] == ids
    lease = await claim(maker,'narrate')
    async with maker.begin() as db:
        authority = await w.authorize_dispatch(db,**fence(lease),worker_id='acceptance-worker')
    text = authority['request']['inputs'][0]['text']
    audio = (Path(__file__).parent/'fixtures/recap_media/audio.mp3').read_bytes()
    async def identity(value):
        async with maker.begin() as db:
            await w.persist_identity(db,authority['attempt_id'],value,worker_id='acceptance-worker')
    async def save(data,sha):
        return await asset(maker,store,lease,data,'audio/mpeg')
    def provider(request):
        narration_calls.append(authority['attempt_id'])
        assert narration_calls.count(authority['attempt_id']) == 1
        return httpx.Response(200,json={'audio_base64':base64.b64encode(audio).decode(),
            'alignment':{'characters':list(text),'character_start_times_seconds':[i*2/len(text) for i in range(len(text))],
                'character_end_times_seconds':[(i+1)*2/len(text) for i in range(len(text))]},
            'voice_segments':[{'voice_id':'synthetic-voice','start_time_seconds':0,'end_time_seconds':2,
                'character_start_index':0,'character_end_index':len(text),'dialogue_input_index':0}]},
            headers={'request-id':authority['attempt_id'],'history-item-id':'synthetic-history-'+str(week),'character-cost':str(len(text))})
    receipt = await el.ElevenLabsTransport('throwaway-synthetic-secret',identity,save,transport=httpx.MockTransport(provider)).send({**lease['input']['paid'], **authority})
    assert receipt.get('outcome') == 'received', receipt
    async with maker.begin() as db:
        await w.persist_receipt(db,authority['attempt_id'],receipt,worker_id='acceptance-worker')
    await w.reconcile_media_receipts(maker)  # crash after raw receipt before settlement
    async with maker.begin() as db:
        with pytest.raises(Held,match='already_issued'):
            await w.authorize_dispatch(db,**fence(lease),worker_id='acceptance-worker')
    await complete(maker,lease,{'status':'ok','asset_ids':[receipt['asset']['asset_id']], 'report':{'receipt_digest':el.canonical(receipt)}})
    speech = await claim(maker,'speech_check')
    words = text.split()
    raw = {'text':text,'words':[{'word':word,'start':i*2/len(words),'end':(i+1)*2/len(words),'probability':.99} for i,word in enumerate(words)],
        'model_revision':MODEL_REVISION,'model_sha256':MODEL_SHA256['model.bin']}
    transcript = await asset(maker,store,speech,dump(raw).encode(),'application/json')
    await complete(maker,speech,{'status':'ok','asset_ids':[transcript['asset_id']],
        'report':{'transcript_asset_id':transcript['asset_id'],'audio_asset_ids':[receipt['asset']['asset_id']]}})
    await linux_stage(maker,store,await claim(maker,'render'),tmp_path/f'render-{week}')
    checked = await claim(maker,'media_check')
    await linux_stage(maker,store,checked,tmp_path/f'check-{week}')
    return ident,checked['stage_id'],source


@pytest.mark.asyncio
async def test_tuesday_to_three_reviews_real_linux_postgres_and_authenticated_admin(pgmaker,tmp_path,monkeypatch,app):
    from app.services.recap_video.storage import LocalPrivateMediaStore
    from app.db.models import User
    from app.services.generation.policy import Policy
    from app.services.generation.publication import drain
    for name,value in {'ADMIN_EMAILS':'owner@test.local,e2e@test.local','CACHE_DIR':str(tmp_path),
        'GENERATION_EXECUTION_EPOCH':'test-epoch','RECAP_PUBLICATION_MODE':'database','RECAP_SERVING_EPOCH':'test-serving',
        'MEDIA_ASSET_ROOT':str(tmp_path/'objects'),'ELEVENLABS_VOICE_ID':'synthetic-voice',
        'ELEVENLABS_ACCOUNT_IDENTITY_DIGEST':el.canonical({'user_id':'synthetic-user','workspace_id':'synthetic-workspace'}),
        'AUTH_BACKEND_SECRET':'throwaway-recap-acceptance-backend-secret'}.items():
        monkeypatch.setenv('TRADE_GRADER_'+name,value)
    assert os.environ.get('RECAP_ACCEPTANCE_IMAGE'), 'Build and explicitly name final worker image'
    # Restore adapter registries after this isolated test.
    monkeypatch.setattr(w,'RESULT_VALIDATORS',{})
    monkeypatch.setattr(w,'RECEIPT_SETTLERS',{})
    monkeypatch.setattr(w,'PREFLIGHT_CONFIG',None)
    monkeypatch.setattr(w,'MEDIA_PLAN_BUILDER',None)
    monkeypatch.setattr(el,'QUALIFICATION_READER',q.qualification_reader)
    el.install_api()
    await seed_job(pgmaker)
    metadata = {'provenance':'elevenlabs-readonly-v1','account':{'user_id':'synthetic-user','workspace_id':'synthetic-workspace'},
        'voice':{'voice_id':'synthetic-voice'},'model':{'model_id':'eleven_v4','can_do_text_to_speech':True},'subscription':{'status':'active','tier':'synthetic'}}
    async with pgmaker.begin() as db:
        owner = await db.get(User,'owner')
        owner.google_sub,owner.email = 'e2e-test-subject','e2e@test.local'
        policy = Policy(paused=False)
        for feature in ('analyst','recap_video'):
            policy.features[feature].mode='automatic'
        (await db.get(g.GenerationPolicy,'app')).value_json=dump(policy.model_dump())
        db.add(m.RecapPublicationControl(id='global',epoch='test-serving',reconciliation_digest='synthetic',quarantined=False))
        db.add(m.RecapShareDecision(scope='series:series',allowed=True,opted_out=False))
        await q.record_calibration(db,'series',2026,actor_id='owner',config=el.preflight_config(),metadata=metadata,
            rate_snapshot=RATE,evidence={k:digest('SYNTHETIC ONLY '+k) for k in ('account_entitlement','settings_continuity','billing_terms','full_performance','linux_runtime')},
            reason='SYNTHETIC test fixture; confers no production qualification')
    store,prose,narration_calls = LocalPrivateMediaStore(tmp_path/'objects'),CountedProse(pgmaker),[]
    episodes=[]
    for week in (4,5,6):
        ident,media_id,source = await episode(pgmaker,tmp_path,store,prose,narration_calls,week,metadata)
        async with pgmaker.begin() as db:
            preview = await p.preview_publication(db,ident,0,media_id)
            proof = await q.record_preview_approval(db,ident,0,'owner',{'media_id':media_id,'preview_digest':preview['digest'],
                'reason':'Synthetic acceptance review', 'checks':{k:'SYNTHETIC fixture only; no real device or voice qualification.' for k in ('factual_coverage','performance','physical_phone','message_preview')}})
        async with pgmaker.begin() as db:
            await p.select_publication(db,ident,0,media_id,proof)
        await drain(pgmaker,tmp_path)
        async with pgmaker() as db:
            status=await q.qualification_status(db,'series',2026)
            assert status['passed']==len(episodes)+1,status
            assert status['automatic'] == (week==6),status
        episodes.append((ident,media_id,source))
    fourth = await episode(pgmaker,tmp_path,store,prose,narration_calls,7,metadata,automatic=True)
    await w.advance_media(pgmaker)
    await drain(pgmaker,tmp_path)
    async with pgmaker() as db:
        status = await q.qualification_status(db,'series',2026)
        assert status['automatic'] and status['passed'] == 3
        assert len(list((await db.scalars(select(m.RecapQualificationReview))).all())) == 3
        approved = list((await db.scalars(select(m.RecapPublicationApproval).where(m.RecapPublicationApproval.episode_id == fourth[0]))).all())
        assert len(approved) == 1 and approved[0].authorization_kind == 'standing' and not approved[0].reviewer_id
        publication = await p.authority_for_episode(db,await db.get(m.RecapEpisode,fourth[0]))
        assert publication.media_id == fourth[1] and publication.projected_revision == publication.authority_revision
    episodes.append(fourth)
    assert len(prose.calls)==16
    assert len(narration_calls)==len(set(narration_calls))==4
    async with pgmaker() as db:
        assert {a.id for a in (await db.scalars(select(g.ProviderAttempt))).all()}==set(prose.calls)
        assert {a.id for a in (await db.scalars(select(m.RecapProviderAttempt))).all()}==set(narration_calls)
    # Authenticated HTTP/Next exercise and reader revocation use these actual bytes.
    from tests.recap_acceptance_browser import exercise_browser
    await exercise_browser(app,pgmaker,tmp_path,episodes[-1],store,monkeypatch)
    image_id = subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',os.environ['RECAP_ACCEPTANCE_IMAGE']],text=True).strip()
    (tmp_path/'acceptance-evidence.json').write_text(dump({'prose_submissions':len(prose.calls),'prose_attempts':prose.calls,'image_id':image_id,
        'narration_attempts':narration_calls,'episodes':[v[0] for v in episodes],'image':os.environ['RECAP_ACCEPTANCE_IMAGE'],
        'qualification':'synthetic fixtures only','renderer':'real pinned Linux namespace and raw API validation'}))
    print('Acceptance evidence:',tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['paid_unknown', 'raw_receipt', 'free_expiry', 'checkpoint'])
async def test_disposable_postgres_crash_boundaries_never_remint_paid_authority(pgmaker,tmp_path,monkeypatch,boundary):
    from tests import test_recap_workflow as contract
    cases = {
        'paid_unknown':contract.test_one_dispatch_unknown_crash_and_late_receipt_only_settles_money,
        'raw_receipt':contract.test_crash_after_raw_receipt_reconciles_without_resending,
        'free_expiry':contract.test_free_crash_backoff_then_attention,
        'checkpoint':contract.test_duplicate_completion_and_restart_reuse_checkpoint,
    }
    await cases[boundary](pgmaker,tmp_path,monkeypatch)


@pytest.mark.asyncio
async def test_physical_prose_timeout_is_not_blindly_resent_on_postgres(pgmaker,monkeypatch):
    from app.services.generation.gateway import Gateway
    from tests.test_generation_gateway import FakeTransport
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS','owner@test.local')
    await seed_job(pgmaker)
    transport=FakeTransport(lost=True)
    for _ in range(3):
        with pytest.raises(Held,match='provider_outcome_unknown'):
            await Gateway(pgmaker,transport,epoch='test-epoch').invoke('job',1,1,REQUEST)
    assert transport.sends==1
    async with pgmaker() as db:
        attempts=list((await db.scalars(select(g.ProviderAttempt))).all())
        assert len(attempts)==1 and attempts[0].state=='unknown'
