"""Offline Linux runtime contract, no provider network or production state."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def tone(path, duration):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-ar", "44100", "-y", str(path)], check=True)

def render(root, episode):
    from media.runtime import run
    root.mkdir(parents=True, exist_ok=True)
    (root / "episode.json").write_text(json.dumps(episode))
    asyncio.run(run(["/usr/bin/node", "/opt/recap/media/render/render.cjs", "--episode", "/work/episode.json", "--output", "/work"], root))

def media_contract(root):
    from media.qa import measure_bundle
    from media.timeline import synthetic_episode, digest_file
    episode = synthetic_episode(2)
    tone(root / "audio.wav", 2)
    episode["audio_sha256"] = digest_file(root / "audio.wav")
    render(root, episode)
    report = measure_bundle(root, episode)
    assert report["issues"] == [], report
    pristine = (root / "video.mp4").read_bytes()
    (root / "video.mp4").write_bytes(pristine[:len(pristine)//2])
    assert "decode_failed" in measure_bundle(root, episode)["issues"]
    (root / "video.mp4").write_bytes(pristine)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(root / "video.mp4"), "-i", str(root / "audio.wav"),
        "-filter_complex", "[1:a]atrim=end=1[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(root / "ending.mp4")], check=True)
    (root / "video.mp4").write_bytes((root / "ending.mp4").read_bytes())
    assert "audio_ending_missing" in measure_bundle(root, episode)["issues"]
    (root / "video.mp4").write_bytes(pristine)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(root / "video.mp4"), "-an", "-c:v", "copy", str(root / "silent.mp4")], check=True)
    (root / "video.mp4").write_bytes((root / "silent.mp4").read_bytes())
    assert "audio_missing" in measure_bundle(root, episode)["issues"]
    (root / "video.mp4").write_bytes(pristine)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(root / "video.mp4"), "-itsoffset", "0.2", "-i", str(root / "audio.wav"),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", str(root / "offset.mp4")], check=True)
    (root / "video.mp4").write_bytes((root / "offset.mp4").read_bytes())
    assert "av_sync_exceeded" in measure_bundle(root, episode)["issues"]
    for change, issue in (("caption", "caption_overflow"), ("font", "font_missing"), ("asset", "audio_missing")):
        bad = root / change
        bad.mkdir()
        shutil.copy(root / "audio.wav", bad / "audio.wav")
        clone = json.loads(json.dumps(episode))
        if change == "caption":
            clone["captions"][0]["text"] = "Oversized " * 100
        if change == "font":
            clone["fonts"]["Geist"] = "0" * 64
        if change == "asset":
            (bad / "audio.wav").unlink()
        try:
            render(bad, clone)
        except RuntimeError:
            pass
        else:
            raise AssertionError(issue + " accepted")

def isolation_contract(root):
    from media.runtime import probe, run
    assert probe(root)["isolated"]
    async def cancel():
        process = asyncio.create_task(run(["/usr/bin/python3", "-c", "import subprocess,time; subprocess.Popen(['sleep','300']); time.sleep(300)"], root))
        await asyncio.sleep(1)
        process.cancel()
        try:
            await process
        except asyncio.CancelledError:
            pass
        # Namespace init death must kill even a reparented descendant.
        result = subprocess.run(["pgrep", "-af", "^sleep 300$"], capture_output=True)
        assert result.returncode == 1, result.stdout
    asyncio.run(cancel())


def adapter_contract(root):
    """Actual lease→render→QA with synthetic API streams and no provider request."""
    import httpx
    from media.adapters import install
    from media.worker import run_stage, HANDLERS
    from media.timeline import synthetic_episode
    fixture = synthetic_episode(2)
    claims=fixture["claims"]
    claims.update(owners=[dict(id="alpha",name="Alpha"),dict(id="bravo",name="Bravo")],period_id="demo")
    script=dict(opening="Welcome.",closing="Goodbye.",segments=[dict(id="matchup",text="Alpha beat Bravo.",claim_ids=["result:demo"],spoken_numbers=[])])
    words="Welcome. Alpha beat Bravo. Goodbye.".split()
    raw=dict(text=" ".join(words),words=[dict(word=w,start=i*.3,end=(i+1)*.3,probability=.99) for i,w in enumerate(words)])
    tone(root/"tone.mp3",.75)
    assets={"speech":json.dumps(raw).encode(),"narration-one":(root/"tone.mp3").read_bytes(),"narration-two":(root/"tone.mp3").read_bytes()}
    def respond(request):
        if request.method == "GET":
            return httpx.Response(200,content=assets[request.url.path.rsplit("/",1)[-1]])
        identity="asset-"+str(len(assets));assets[identity]=request.content
        return httpx.Response(200,json={"asset_id":identity})
    async def exercise():
        async with httpx.AsyncClient(base_url="https://synthetic.invalid",transport=httpx.MockTransport(respond)) as client:
            install(client, HANDLERS)
            lease=dict(stage_id="render",generation=1,epoch="epoch",input_digest="digest",capability="render",allowed_assets=["speech","narration-two","narration-one"],
                input=dict(script=script,claims=claims,chunks=[{},{}],script_digest="synthetic",speech_review={"aliases":{}}))
            rendered=await run_stage(lease)
            assert rendered["status"] == "ok"
            manifest=json.loads(assets[rendered['report']['manifest_asset_id']])
            episode=json.loads(assets[manifest['files']['episode.json']])
            assert [c['asset_id'] for c in episode['chunk_timing']]==['narration-one','narration-two']
            assert sum(c['frames'] for c in episode['chunk_timing'])==66150
            checked=await run_stage({**lease,"stage_id":"check","capability":"media_check","allowed_assets":rendered["asset_ids"]+lease["allowed_assets"]})
            assert checked["status"] == "ok",checked
            report=json.loads(assets[checked["report"]["qa_asset_id"]])
            assert report["decoded"] and report["measurements"]["frames"] == 45
            assert len(checked["report"]["frames"]) >= 3
    asyncio.run(exercise())

def seam_contract(root):
    import array,math,wave
    from media.audio_seams import chunk_record, measure_seams, seam_issues, join
    from media.timeline import digest_file
    chunks=[chunk_record('one','0'*64,44100),chunk_record('two','1'*64,44100,44100)]
    original=[int(3000*math.sin(2*math.pi*440*i/44100)) for i in range(88200)]
    for name,gap,jump in [('natural-pause',.12,False),('injected-gap',.4,False),('click',0,True)]:
        values=list(original);half=round(gap*44100/2)
        # Smooth existing natural pause avoids manufacturing an edge click.
        for i in range(44100-half-220,44100+half+220):
            if not 0<=i<len(values): continue
            gain=min(1,max(0,(abs(i-44100)-half)/220))
            values[i]=int(values[i]*gain)
        if jump: values[44100]=30000
        path=root/(name+'.wav')
        with wave.open(str(path),'wb') as wav:
            wav.setparams((1,2,44100,0,'NONE','not compressed'));wav.writeframes(array.array('h',values).tobytes())
        case=root/name;case.mkdir();spec=[]
        for i,identity in enumerate(('one','two')):
            part=case/f'chunk-{i}.mp3'
            with wave.open(str(part),'wb') as wav:
                wav.setparams((1,2,44100,0,'NONE','not compressed'));wav.writeframes(array.array('h',values[i*44100:(i+1)*44100]).tobytes())
            spec.append(dict(asset_id=identity,sha256=digest_file(part)))
        (case/'chunk-inputs.json').write_text(json.dumps(spec));join(case)
        actual=json.loads((case/'chunks.json').read_text())
        assert [c['frames'] for c in actual]==[44100,44100] and actual[-1]['end_frame']==88200
        assert [c['sha256'] for c in actual]==[s['sha256'] for s in spec]
        assert [digest_file(case/f'chunk-{i}.mp3') for i in range(2)]==[s['sha256'] for s in spec]
        with wave.open(str(case/'audio.wav')) as wav:
            assert wav.readframes(wav.getnframes())==array.array('h',values).tobytes()
        subprocess.run(['ffmpeg','-v','error','-i',str(case/'audio.wav'),'-ar','16000',str(case/'speech.wav')],check=True)
        with wave.open(str(case/'speech.wav')) as wav:
            assert wav.getnframes()==32000 and wav.getnframes()/wav.getframerate()==actual[-1]['end_frame']/44100
        measured=measure_seams(case/'audio.wav',actual)
        issues=seam_issues(measured,chunks)
        assert issues==([] if name=='natural-pause' else ['chunk_seam_gap'] if gap else ['chunk_seam_discontinuity']), (name,measured,issues)
        if name=='natural-pause':
            assert 100<measured[0]['gap_ms']<140
        (root/(name+'.json')).write_text(json.dumps(measured))

def failure_contract(root):
    from media.runtime import run
    from media.worker import run_claim,HANDLERS
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'asset_id':'diagnostic'}
    class Client:
        def __init__(self): self.calls=[]
        async def post(self,path,**kw): self.calls.append((path,kw));return Response()
    async def exercise():
        for argv,seconds,reason in [(['/usr/bin/sleep','20'],.1,'timeout'),(['/usr/bin/false'],5,'exit_nonzero')]:
            async def fail(lease): await run(argv,root,seconds)
            HANDLERS['render']=fail;client=Client()
            await run_claim(client,dict(capability='render',stage_id='stage',generation=1,epoch='epoch',input_digest='digest'))
            assert [p for p,_ in client.calls]==['/api/internal/media/assets','/api/internal/media/complete']
            raw=json.loads(client.calls[0][1]['content'])
            assert raw['reason']==reason and raw['stage_kind']=='render' and len(json.dumps(raw))<512
            assert client.calls[1][1]['json']['result']['status']=='input_failure'
    asyncio.run(exercise())

if __name__ == "__main__":
    import sys
    if "--expect-refusal" in sys.argv:
        from media.runtime import probe
        target = Path("/scratch/refusal")
        target.mkdir()
        try:
            probe(target)
        except RuntimeError:
            print("Unsupported runtime refused before API claim")
            raise SystemExit(0)
        raise SystemExit("Default namespace assumptions changed; review isolation capability")
    raise SystemExit(subprocess.call(["python", "-m", "pytest", "api/tests/test_recap_render_contract.py", "-q", "-o", "markers=asyncio: API-only asynchronous test"]))
