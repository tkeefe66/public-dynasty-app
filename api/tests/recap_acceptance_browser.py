"""Owned localhost listeners, clean Next copy and real auth. Never loads .env files."""
import asyncio
import json
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import httpx
import uvicorn
from sqlalchemy import select
from app.services.generation import recap_models as m
from app.services.generation.store import Held
from app.services.recap_video import publication as p

ROOT = Path(__file__).resolve().parents[2]


async def exercise_browser(app,maker,tmp_path,episode,store,monkeypatch):
    from app.db.session import get_db
    from app.services.generation.recap_budget import reserve_plan
    from app.services.generation.models import stamp
    ident,media_id,source = episode
    from app.services import nfl_state
    async def synthetic_state():
        return {'season': '2026', 'season_type': 'regular', 'week': 7}
    monkeypatch.setattr(nfl_state, 'fetch_state', synthetic_state)
    original_send = httpx.AsyncClient.send
    async def localhost_only(client, request, *args, **kwargs):
        assert request.url.host in {'127.0.0.1', 'localhost'}, 'Acceptance attempted non-local API network'
        return await original_send(client, request, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, 'send', localhost_only)
    async def database():
        async with maker.begin() as db:
            yield db
    assert not app.dependency_overrides, 'Auth acceptance refuses existing dependency overrides'
    app.dependency_overrides[get_db]=database
    listener=socket.socket()
    listener.bind(('127.0.0.1',0))
    api_origin=f'http://127.0.0.1:{listener.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(app,lifespan='off',access_log=False,log_config=None))
    task=asyncio.create_task(server.serve(sockets=[listener]))
    next_process=None
    try:
        for _ in range(100):
            if server.started:break
            await asyncio.sleep(.02)
        assert server.started
        async with maker() as db:
            publication=await p.authority_for_episode(db,await db.get(m.RecapEpisode,ident))
            token=(await p.share_state(db,publication))['token']
            selected=json.loads(publication.media_json)
            selected_article=json.loads(publication.article_json)
        async with httpx.AsyncClient(base_url=api_origin) as client:
            assert (await client.get('/api/admin/generation/recap-budgets/series')).status_code==401
            response=await client.get('/api/public/analyst/'+token)
            assert response.status_code==200,response.text
            assert p.public_article(response.json())==p.public_article(selected_article)
            assert 'Private verified scoring-period' not in response.text
            # Public transport is exact selected immutable bytes, all formats/HEAD/range.
            media=response.json()['media']
            base=f'/api/public/analyst/{token}/media/{media["id"]}'
            for name in ('video.mp4','audio.mp3','poster.jpg','captions.vtt'):
                body=await client.get(base+'/'+name)
                assert body.status_code==200
                assert hashlib.sha256(body.content).hexdigest()==selected['files'][name]['sha256']
                partial=await client.get(base+'/'+name,headers={'Range':'bytes=5-19'})
                assert partial.status_code==206 and partial.content==body.content[5:20]
                head=await client.head(base+'/'+name)
                assert int(head.headers['content-length'])==len(body.content)
        workspace=tmp_path/'next'
        shutil.copytree(ROOT/'web',workspace,ignore=shutil.ignore_patterns('node_modules','.next','.env*','playwright-report','test-results','.auth'))
        shutil.copytree(ROOT/'.design', tmp_path/'.design')
        (workspace/'node_modules').symlink_to(ROOT/'web/node_modules',target_is_directory=True)
        assert not list(workspace.glob('.env*'))
        with socket.socket() as available:
            available.bind(('127.0.0.1',0))
            web_port=available.getsockname()[1]
        origin=f'http://127.0.0.1:{web_port}'
        env={key:os.environ[key] for key in ('PATH','HOME','TMPDIR','CI') if key in os.environ}
        env.update(AUTH_SECRET='throwaway-recap-acceptance-session-secret',AUTH_BACKEND_SECRET='throwaway-recap-acceptance-backend-secret',
            AUTH_TRUST_HOST='true',AUTH_URL=origin,NEXTAUTH_URL=origin,API_URL=api_origin,NEXT_TELEMETRY_DISABLED='1',
            RECAP_ACCEPTANCE_ORIGIN=origin,RECAP_ACCEPTANCE_EPISODE=ident,RECAP_ACCEPTANCE_MEDIA=media_id,
            RECAP_ACCEPTANCE_TOKEN=token,RECAP_ACCEPTANCE_OUTPUT=str(tmp_path/'browser'))
        if os.environ.get('RECAP_ACCEPTANCE_CHROME'):
            env['RECAP_ACCEPTANCE_CHROME']=os.environ['RECAP_ACCEPTANCE_CHROME']
        (tmp_path/'browser').mkdir()
        with (tmp_path/'next.log').open('w') as output:
            next_process=subprocess.Popen(['node',str(ROOT/'web/node_modules/next/dist/bin/next'),'dev','-H','127.0.0.1','-p',str(web_port)],cwd=workspace,env=env,stdout=output,stderr=subprocess.STDOUT)
            async with httpx.AsyncClient() as client:
                for _ in range(60):
                    assert next_process.poll() is None,(tmp_path/'next.log').read_text()
                    try:
                        if (await client.get(origin+'/login',timeout=2)).status_code==200:break
                    except httpx.HTTPError:pass
                    await asyncio.sleep(.5)
                else:raise AssertionError('Owned Next listener did not become ready')
            run=await asyncio.to_thread(subprocess.run,['node',str(ROOT/'web/node_modules/@playwright/test/cli.js'),
                'test','--config',str(workspace/'e2e/recap.config.ts')],cwd=workspace,env=env,capture_output=True,text=True,timeout=240)
            (tmp_path/'browser.log').write_text(run.stdout+'\n'+run.stderr)
            assert run.returncode==0,run.stdout+run.stderr
        # Browser-saved cap governs the next real admission transaction, no provider call.
        async with maker.begin() as db:
            with __import__('pytest').raises(Held,match='recap_budget_video_episode'):
                await reserve_plan(db,ident,'series','after-ui-save',[dict(key='new',category='video',operation_id='synthetic-new',
                    max_microusd=20_000,rate_snapshot={'unit':'character'})],stamp())
        async with maker.begin() as db:
            row=await p.authority_for_episode(db,await db.get(m.RecapEpisode,ident))
            await p.change_share(db,row,enabled=False,actor_id='owner')
        async with httpx.AsyncClient(base_url=api_origin) as client:
            assert (await client.get(base+'/video.mp4',headers={'Range':'bytes=0-1'})).status_code==404
        async with maker.begin() as db:
            row=await p.authority_for_episode(db,await db.get(m.RecapEpisode,ident))
            restored=await p.change_share(db,row,enabled=True,actor_id='owner')
            restored_token=restored['token']
        async with httpx.AsyncClient(base_url=api_origin) as client:
            assert (await client.get('/api/public/analyst/'+token)).status_code==404
            assert (await client.get('/api/public/analyst/'+restored_token)).status_code==200
            base=base.replace(token,restored_token)
        # Material correction withdraws selected content before any replacement request.
        from app.services.recap_video.corrections import observe_correction
        changed=json.loads(json.dumps(source))
        changed['scores'][str(changed['week'])][0]['points']='99.000'
        async with maker.begin() as db:
            current=await db.get(m.RecapEpisode,ident)
            await observe_correction(db,ident,changed,now=current.observed_at+60)
        async with httpx.AsyncClient(base_url=api_origin) as client:
            assert (await client.get(base+'/video.mp4')).status_code==404
    finally:
        if next_process is not None:
            next_process.terminate()
            try:await asyncio.to_thread(next_process.wait,timeout=10)
            except subprocess.TimeoutExpired:next_process.kill();await asyncio.to_thread(next_process.wait)
        server.should_exit=True
        await task
        listener.close()
        app.dependency_overrides.pop(get_db,None)
