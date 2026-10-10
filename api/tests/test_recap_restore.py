import logging
import pytest


@pytest.mark.parametrize('path', [
    '/api/public/analyst/secret-token/video.mp4?token=secret-token',
    'https://app.test/share/analyst/secret-token?next=private-value',
    '/api/public/analyst%2Fsecret-token%2Fvideo.mp4%3Ftoken%3Dsecret-token',
    '%252Fshare%252Fanalyst%252Fsecret-token%253Ftoken%253Dsecret-token',
])
def test_redaction_covers_encoded_paths_queries_and_exceptions(path):
    # Mutation: sanitize only literal request URLs, leaving exception/breadcrumb paths.
    from app.services.route_normalize import redact_share_path
    from app.services.oauth_telemetry import before_send
    from app.services.recap_video.public_logging import SharePathFilter
    assert 'secret-token' not in redact_share_path(path)
    event = {'message':'Failed: '+path, 'exception':{'values':[{'value':path}]},
        'breadcrumbs':{'values':[{'message':path}]}, 'request':{'url':'https://app.test/other', 'query_string':'next='+path}}
    assert 'secret-token' not in str(before_send(event, {}))
    record = logging.LogRecord('uvicorn.access', logging.ERROR, '', 1, 'GET %s', (path,), None)
    SharePathFilter().filter(record)
    assert 'secret-token' not in record.getMessage()


@pytest.mark.asyncio
async def test_restore_reconciles_current_revocation_and_fences_recovery(maker, monkeypatch):
    # Mutation: restored share row certifies itself current or recovery lease survives.
    from app.services.generation.recap_models import RecapShareDecision, RecapRecoveryRequest, RecapPublicationControl
    from app.services.generation.recovery import quarantine, reconcile_restore, financial_digest
    from app.services.generation.store import digest
    from app.config import get_settings
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','quarantine')
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EMERGENCY_PAUSE','true')
    for key in ('RECAP_RESTORE_EPOCH','RECAP_SERVING_EPOCH','GENERATION_EXECUTION_EPOCH'):
        monkeypatch.setenv('TRADE_GRADER_'+key,'fresh-restore')
    async with maker.begin() as db:
        db.add(RecapShareDecision(scope='edition:episode',revision=1,allowed=True,token='old-token',token_digest='old'))
        db.add(RecapRecoveryRequest(id='lookup',attempt_id='attempt',worker_id='worker',actor_id='admin',
            identity_json='{}',request_digest='request',epoch='old',state='running',lease_until=999999,reason='Lookup'))
    async with maker.begin() as db:
        await quarantine(db)
        assert (await db.get(RecapRecoveryRequest,'lookup')).lease_until == 0
        current={'share_decisions':[{'scope':'edition:episode','revision':2,'allowed':False,'opted_out':True,
            'token':None,'token_digest':None}], 'financial_digest':await financial_digest(db)}
        monkeypatch.setenv('TRADE_GRADER_RECAP_RESTORE_EVIDENCE_DIGEST',digest(current))
        report=await reconcile_restore(db,{'media_objects':{},'current_authority':current}, {})
        assert report['reconciled'] is True
        assert (await db.get(RecapShareDecision,'edition:episode')).token is None
        assert (await db.get(RecapPublicationControl,'global')).quarantined is True


@pytest.mark.asyncio
async def test_missing_external_evidence_disables_old_tokens_and_future_permission(maker,monkeypatch):
    # Mutation: use backup's revocations as proof there were no newer revocations.
    from app.services.generation.recap_models import RecapShareDecision
    from app.services.generation.recovery import reconcile_restore
    from app.config import get_settings
    for key,value in {'RECAP_PUBLICATION_MODE':'quarantine','GENERATION_EMERGENCY_PAUSE':'true',
            'RECAP_RESTORE_EPOCH':'new','RECAP_SERVING_EPOCH':'new','GENERATION_EXECUTION_EPOCH':'new'}.items():
        monkeypatch.setenv('TRADE_GRADER_'+key,value)
    async with maker.begin() as db:
        db.add(RecapShareDecision(scope='edition:episode',allowed=True,token='old',token_digest='old'))
        db.add(RecapShareDecision(scope='series:series',allowed=True))
    async with maker.begin() as db:
        result=await reconcile_restore(db,{'media_objects':{},'authority':{'share_decisions':[]}}, {})
        assert not result['reconciled']
        for scope in ('edition:episode','series:series'):
            row=await db.get(RecapShareDecision,scope)
            assert not row.allowed and row.token is None


def test_backup_listing_errors_and_partial_pages_never_mean_absent():
    # Mutation: treating a denied/incomplete list as an empty recovery prefix.
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
    from recap_maintenance import absent_prefix,list_exact_prefix
    class Denied:
        def list_objects_v2(self,**kwargs):raise PermissionError('403 synthetic')
    with pytest.raises(PermissionError):absent_prefix(Denied(),'synthetic','point')
    class Partial:
        def list_objects_v2(self,**kwargs):return {'IsTruncated':True,'Contents':[]}
    with pytest.raises(ValueError,match='incomplete'):list_exact_prefix(Partial(),'synthetic','backups/point/')
    class Complete:
        def list_objects_v2(self,**kwargs):return {'IsTruncated':False,'Contents':[]}
    assert absent_prefix(Complete(),'synthetic','point')==[]


def test_restore_cli_requires_external_gate_before_any_mutation(monkeypatch,tmp_path):
    # Mutation: begin migrations/restore before checking external quarantine.
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
    import restore
    monkeypatch.setattr(sys,'argv',['restore','--database-url','sqlite+aiosqlite:///'+str(tmp_path/'db'),
        '--cache-dir',str(tmp_path/'cache'),'--quarantine-api-url','https://synthetic.invalid',
        '--expected-restore-epoch','fresh'])
    monkeypatch.setattr(restore,'_client',lambda:pytest.fail('Storage touched before quarantine'))
    assert restore.main()==2
    assert not (tmp_path/'db').exists() and not (tmp_path/'cache').exists()


@pytest.mark.asyncio
async def test_mismatched_media_or_current_finance_cannot_reopen(maker,monkeypatch):
    # Mutation: admit restore with corrupt bytes, missing newer spend, or unbound report.
    from tests.test_recap_retention import seed_asset
    from app.services.generation.recovery import reconcile_restore,reopen_restore
    from app.services.generation.store import digest,Held
    from app.services.generation.recap_models import RecapAsset
    identity,key,_=await seed_asset(maker)
    for env,value in {'RECAP_PUBLICATION_MODE':'quarantine','GENERATION_EMERGENCY_PAUSE':'true',
            'RECAP_RESTORE_EPOCH':'new','RECAP_SERVING_EPOCH':'new','GENERATION_EXECUTION_EPOCH':'new'}.items():
        monkeypatch.setenv('TRADE_GRADER_'+env,value)
    current={'share_decisions':[],'financial_digest':'newer-ledger-missing-from-backup'}
    monkeypatch.setenv('TRADE_GRADER_RECAP_RESTORE_EVIDENCE_DIGEST',digest(current))
    async with maker.begin() as db:
        asset=await db.get(RecapAsset,identity)
        report=await reconcile_restore(db,{'media_objects':{key:{'sha256':asset.digest,'size':5}},
            'current_authority':current},{key:{'sha256':'corrupt','size':5}})
        assert report['object_errors']==[key] and not report['financial_ledger_matches']
        with pytest.raises(Held,match='restore_reconciliation_required'):
            await reopen_restore(db,expected_digest=digest(report),actor_id='admin')


def test_private_metadata_not_in_public_article_schema():
    # Mutation: return worker/provider payload fields instead of approved public allowlist.
    from app.services.recap_video.publication import public_article
    result=public_article({'edition_type':'roast','markdown':'Approved recap','provider_metadata':{'secret':'draft'},
        'draft_script':'unreviewed draft','request_json':'private request','caption_draft':'private'})
    assert result['markdown']=='Approved recap'
    assert not set(result).intersection({'provider_metadata','draft_script','request_json','caption_draft'})


@pytest.mark.asyncio
async def test_page_event_storage_never_retains_share_credentials(maker):
    # Mutation: normalize route but persist original credential-bearing path.
    from app.repositories.events import record_event
    from app.db.models import PageEvent,User
    from sqlalchemy import select
    async with maker.begin() as db:
        db.add(User(id='synthetic-user',google_sub='synthetic-sub',email='synthetic@example.test'))
    async with maker.begin() as db:
        await record_event(db,user_id='synthetic-user',path='/share%2Fanalyst%2Fsecret-token?token=secret-token')
        row=await db.scalar(select(PageEvent))
        assert 'secret-token' not in row.path and 'secret-token' not in row.route


@pytest.mark.asyncio
async def test_financial_reconciliation_includes_current_caps_and_provider_holds(maker):
    # Mutation: same receipts certify restore despite newer lowered cap/provider hold.
    from app.services.generation.recovery import financial_digest
    from app.services.generation.recap_models import RecapBudgetPolicy,ProviderAccountControl
    async with maker.begin() as db:
        before=await financial_digest(db)
        db.add(RecapBudgetPolicy(series_id='series',caps_json='{"video_episode_microusd":1000000}'))
    async with maker.begin() as db:
        after=await financial_digest(db)
        assert before != after
        db.add(ProviderAccountControl(provider='synthetic',account_key='synthetic',hold='provider_auth_failed'))
    async with maker() as db:assert await financial_digest(db) != after


def test_restore_media_verifies_configured_destination_bytes_not_only_backup(monkeypatch):
    # Mutation: accept an existing object with extra bytes sharing a valid prefix.
    import sys,hashlib,uuid
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
    import restore
    key=str(uuid.uuid4())
    class Store:
        def put_verified(self,*args):raise ValueError('Immutable object exists')
        def head(self,key):return {'size':10,'sha256':'untrusted metadata'}
        def read_range(self,key,start,end):return b'bytes'
    monkeypatch.setattr('app.services.recap_video.storage.configured_store',lambda:Store())
    monkeypatch.setattr(restore,'_get',lambda *args:b'bytes')
    with pytest.raises(ValueError,match='differs'):
        restore.restore_media(None,'synthetic','prefix',{'media_objects':{key:{'size':5,
            'sha256':hashlib.sha256(b'bytes').hexdigest()}}},None,configured=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['withdrawn','replacement'])
async def test_post_backup_publication_changes_survive_unchanged_share_token(maker,monkeypatch,change):
    # Mutation: current sharing consent certifies stale pre-correction content.
    from app.services.generation.recovery import export_restore_authority,reconcile_restore
    from app.services.generation.recap_models import RecapShareDecision,RecapPublication
    from app.services.generation.store import digest
    for key,value in {'RECAP_PUBLICATION_MODE':'quarantine','GENERATION_EMERGENCY_PAUSE':'true',
            'RECAP_RESTORE_EPOCH':'new','RECAP_SERVING_EPOCH':'new','GENERATION_EXECUTION_EPOCH':'new'}.items():
        monkeypatch.setenv('TRADE_GRADER_'+key,value)
    async with maker.begin() as db:
        db.add(RecapShareDecision(scope='edition:episode',revision=1,allowed=True,token='same-token',token_digest='same'))
        db.add(RecapPublication(episode_id='episode',series_id='series',league_id='synthetic',season=2026,week=1,
            article_revision=1,article_digest='old-article',article_json='{}',facts_digest='old-facts',share_revision=1,
            epoch='old',media_id='old-media',media_json='{"hash":"old-master"}'))
    async with maker.begin() as db:
        row=await db.get(RecapPublication,'episode')
        if change=='withdrawn':row.withdrawn=True
        else:row.media_json='{"hash":"new-reviewed-master"}'
        row.authority_revision=2
    async with maker.begin() as db:current=await export_restore_authority(db)
    monkeypatch.setenv('TRADE_GRADER_RECAP_RESTORE_EVIDENCE_DIGEST',digest(current))
    async with maker.begin() as db:
        row=await db.get(RecapPublication,'episode')
        row.withdrawn=False;row.authority_revision=1;row.media_json='{"hash":"old-master"}'
    async with maker.begin() as db:
        result=await reconcile_restore(db,{'media_objects':{},'current_authority':current},{})
        row=await db.get(RecapPublication,'episode')
        assert result['current_authority_verified']
        if change=='withdrawn':assert row.withdrawn
        else:assert not row.enabled and row.hold=='restore_current_publication_changed'
        assert (await db.get(RecapShareDecision,'edition:episode')).token=='same-token'
