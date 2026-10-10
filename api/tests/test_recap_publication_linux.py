"""Actual synthetic Linux render/QA -> API selection -> public HTTP transport."""
import hashlib
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import uuid

import pytest
from tests.test_recap_publication import approve_current
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.skipif(os.getenv('RECAP_PUBLICATION_LINUX_TEST') != '1', reason='Explicit local Docker media integration')


@pytest.mark.asyncio
async def test_checked_media_selection_and_real_public_formats(app, maker, tmp_path, monkeypatch):
    # Mutation: select unverified/private manifest bytes or label WAV as public MP3.
    from tests.test_recap_speech_reviews import reviewed_artifact
    from tests.test_recap_audio import transcript
    from app.db.session import get_db
    from app.services.generation.models import ContentArtifact
    from app.services.generation.recap_models import RecapAsset, RecapStage, RecapPublicationControl, RecapShareDecision, RecapPublication
    from app.services.generation.store import dump, digest
    from app.services.recap_video.storage import LocalPrivateMediaStore
    from app.services.recap_video import publication as p
    from app.services.recap_video.rendering import validate_render, validate_check
    from app.services.generation.publication import drain
    from media.timeline import build_episode
    ident, speech_id = await reviewed_artifact(maker, tmp_path, monkeypatch)
    monkeypatch.setenv('TRADE_GRADER_MEDIA_ASSET_ROOT', str(tmp_path/'objects'))
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE', 'database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH', 'test-serving')
    store = LocalPrivateMediaStore(tmp_path/'objects')
    output = tmp_path/'encoded'
    output.mkdir()
    fixture = Path(__file__).parent/'fixtures/recap_media'
    shutil.copyfile(fixture/'audio.wav', output/'audio.wav')
    raw = transcript('Welcome. Avery and Blake tied. That is all.')
    async with maker.begin() as db:
        db.add(RecapPublicationControl(id='global', epoch='test-serving', reconciliation_digest='synthetic', quarantined=False))
        db.add(RecapShareDecision(scope='series:series', allowed=True, opted_out=False))
        artifact = await db.get(ContentArtifact, 'script')
        payload = json.loads(artifact.payload_json)
        inputs = dict(script=payload['script'], claims=payload['claims'], script_digest=artifact.digest)
        speech = await db.get(RecapStage, speech_id)
        stages = {row.kind:row for row in (await db.scalars(select(RecapStage).where(RecapStage.script_id=='script'))).all()}
        async def save(data, mime, owner):
            key, identity = str(uuid.uuid4()), str(uuid.uuid4())
            sha = hashlib.sha256(data).hexdigest()
            store.put_verified(key, data, sha)
            db.add(RecapAsset(id=identity, stage_id=owner.id, generation=owner.generation, digest=sha,
                size=len(data), media_type=mime, storage_key=key))
            await db.flush()
            return identity
        speech.state = 'succeeded'
        raw_id = await save(dump(raw).encode(), 'application/json', speech)
        audio_id = await save((output/'audio.wav').read_bytes(), 'audio/wav', speech)
        speech.evidence_json = dump(dict(transcript_asset_id=raw_id, audio_asset_ids=[audio_id], speech_review={'aliases':{}}))
        episode = build_episode(inputs, raw, [audio_id], hashlib.sha256((output/'audio.wav').read_bytes()).hexdigest(), 2)
        (output/'episode.json').write_text(json.dumps(episode))
        mount = ['docker','run','--rm','--network','none','--memory','2g','-v',f'{output}:/work','recap-media:task9']
        for command in (
            ['node','/opt/recap/media/render/render.cjs','--episode','/work/episode.json','--output','/work'],
            ['python','-m','media.public_package','/work'], ['python','-m','media.qa','/work']):
            subprocess.run([*mount,*command], check=True, capture_output=True, timeout=120)
        render = stages['render']
        render.generation = 1
        render.input_json, render.input_digest = dump(inputs), digest(inputs)
        render.predecessor_id = speech_id
        render_report = json.loads((output/'render.json').read_text())
        types = {'video.mp4':'video/mp4','audio.wav':'audio/wav','episode.json':'application/json',
            'render.json':'application/json','audio.mp3':'audio/mpeg','poster.jpg':'image/jpeg','captions.vtt':'text/vtt'}
        types.update({frame['file']:'image/png' for frame in render_report['representative_frames']})
        files = {name:await save((output/name).read_bytes(),mime,render) for name,mime in types.items()}
        manifest = await save(json.dumps(dict(version='recap-bundle-1',script_digest=artifact.digest,files=files)).encode(),'application/json',render)
        result = dict(asset_ids=[manifest,*files.values()],report={'manifest_asset_id':manifest})
        await validate_render(db,render,result)
        render.state, render.result_json = 'succeeded', dump(result)
        check = stages['media_check']
        check.generation = 1
        check.input_json, check.input_digest = dump(inputs), digest(inputs)
        qa = json.loads((output/'qa.json').read_text())
        assert qa['issues'] == []
        frames = {frame['file']:await save((output/frame['file']).read_bytes(),'image/png',check) for frame in qa['measurements']['representative_frames']}
        qa_id = await save((output/'qa.json').read_bytes(),'application/json',check)
        result = dict(asset_ids=[qa_id,*frames.values()],report=dict(qa_asset_id=qa_id,frames=frames))
        await validate_check(db,check,result)
        check.state, check.result_json = 'succeeded', dump(result)
        media_id = check.id
    async with maker.begin() as db:
        proof = await approve_current(db, ident, 0, media_id, reviewer=SimpleNamespace(id='admin',is_admin=True), reason='Synthetic completed preview')
    async with maker.begin() as db:
        await p.select_publication(db, ident, 0, media_id, proof)
    await drain(maker, tmp_path)
    async with maker() as db:
        row = await db.get(RecapPublication,ident)
        token = (await p.share_state(db,row))['token']
        assert await p.published_script_selections(db,'series') == ['script']
    async def dependency():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    import socket
    import uvicorn
    listener = socket.socket()
    listener.bind(('127.0.0.1',0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan='off', access_log=False, log_config=None))
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(.02)
    assert server.started
    origin = f'http://127.0.0.1:{port}'
    try:
        async with AsyncClient(base_url=origin) as client:
            page = await client.get(f'/api/public/analyst/{token}')
            assert page.status_code == 200, page.text
            base = f'/api/public/analyst/{token}/media/{page.json()["media"]["id"]}'
            for name in ('video.mp4','audio.mp3','poster.jpg','captions.vtt'):
                response = await client.get(base+'/'+name+'?download=true')
                assert response.status_code == 200, response.text[:100]
                assert response.content == (output/name).read_bytes()
                partial = await client.get(base+'/'+name,headers={'Range':'bytes=5-19'})
                assert partial.status_code == 206 and partial.content == response.content[5:20]
                head = await client.head(base+'/'+name)
                assert int(head.headers['content-length']) == len(response.content)
            if os.getenv('RECAP_PHONE_TEST') == '1':
                script = Path(__file__).parents[2]/'scripts/check_recap_public_phone.cjs'
                completed = await asyncio.to_thread(subprocess.run,
                    ['node',str(script),origin,token,str(output)],capture_output=True,text=True,timeout=180)
                assert completed.returncode == 0, completed.stdout+'\n'+completed.stderr
                print(completed.stdout)
            async with maker.begin() as db:
                row = await db.get(RecapPublication,ident)
                await p.change_share(db,row,enabled=False,actor_id='member')
            assert (await client.get(base+'/video.mp4',headers={'Range':'bytes=0-1'})).status_code == 404
    finally:
        server.should_exit = True
        await server_task
        listener.close()
        app.dependency_overrides.pop(get_db,None)
