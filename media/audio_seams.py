"""Canonical decoded chunk boundaries and conservative, explicit seam qualification."""
import array
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import wave

RATE = 44100
# Initial automated review thresholds, not proof of perceptual seamlessness.
RULES = {'window_ms':500, 'step_window_ms':5, 'silence_db':-50, 'max_gap_ms':250, 'max_step':.2}

def chunk_record(identity, sha, frames, start=0):
    return dict(asset_id=identity,sha256=sha,sample_rate=RATE,frames=frames,start_frame=start,end_frame=start+frames)

def boundaries_valid(chunks, ids, frames):
    try:
        end=0
        if not 1 <= len(chunks) <= 64 or [c['asset_id'] for c in chunks] != ids:
            return False
        for c in chunks:
            if (c['sample_rate'] != RATE or type(c['frames']) is not int or c['frames']<=0
                or type(c['start_frame']) is not int or c['start_frame']!=end
                or type(c['end_frame']) is not int or c['end_frame']!=end+c['frames']
                or len(c['sha256'])!=64 or any(x not in '0123456789abcdef' for x in c['sha256'])):
                return False
            end=c['end_frame']
        return end==frames
    except (KeyError,TypeError):
        return False

def measure_seams(path, chunks):
    with wave.open(str(path)) as wav:
        if (wav.getframerate(),wav.getsampwidth(),wav.getnchannels())!=(RATE,2,1):
            raise ValueError('seam_pcm_format')
        frames=wav.getnframes(); samples=array.array('h',wav.readframes(frames))
    if sys.byteorder!='little': samples.byteswap()
    rows=[]
    threshold=32768*10**(RULES['silence_db']/20)
    for left,right in zip(chunks,chunks[1:]):
        at=left['end_frame']; radius=round(RATE*RULES['window_ms']/1000)
        lo,hi=max(0,at-radius),min(frames,at+radius)
        a,b=at,at
        while a>lo and abs(samples[a-1])<threshold: a-=1
        while b<hi and abs(samples[b])<threshold: b+=1
        small=round(RATE*RULES['step_window_ms']/1000)
        steps=[abs(samples[i]-samples[i-1])/32768 for i in range(max(1,at-small),min(frames,at+small))]
        rows.append(dict(left_asset=left['asset_id'],right_asset=right['asset_id'],boundary_frame=at,
            window_start_frame=lo,window_end_frame=hi,jump=abs(samples[at]-samples[at-1])/32768,
            max_step=max(steps),silence_start_frame=a,silence_end_frame=b,gap_ms=(b-a)/RATE*1000))
    return rows

def seam_issues(rows,chunks):
    if not isinstance(rows,list) or not isinstance(chunks,list):
        return ['seam_evidence_invalid']
    if len(rows)!=len(chunks)-1:
        return ['seam_evidence_missing']
    issues=[]
    try:
        for row,left,right in zip(rows,chunks,chunks[1:]):
            if not isinstance(row,dict): raise ValueError()
            if (row['left_asset']!=left['asset_id'] or row['right_asset']!=right['asset_id']
                or row['boundary_frame']!=left['end_frame'] or right['start_frame']!=left['end_frame']
                or any(type(v) not in (int,float) or not math.isfinite(v) for k,v in row.items() if k not in ('left_asset','right_asset'))
                or row['window_start_frame']!=max(0,left['end_frame']-round(RATE*RULES['window_ms']/1000))
                or row['window_end_frame']!=min(chunks[-1]['end_frame'],left['end_frame']+round(RATE*RULES['window_ms']/1000))
                or not 0<=row['window_start_frame']<=row['silence_start_frame']<=row['boundary_frame']<=row['silence_end_frame']<=row['window_end_frame']
                or abs(row['gap_ms']-(row['silence_end_frame']-row['silence_start_frame'])/RATE*1000)>.001
                or not 0<=row['jump']<=row['max_step']<=2):
                raise ValueError()
            if row['gap_ms']>RULES['max_gap_ms']: issues.append('chunk_seam_gap')
            if row['max_step']>RULES['max_step']: issues.append('chunk_seam_discontinuity')
    except (KeyError,TypeError,ValueError):
        issues.append('seam_evidence_invalid')
    return sorted(set(issues))

def join(root):
    spec=json.loads((root/'chunk-inputs.json').read_text()); chunks=[]; offset=0
    with wave.open(str(root/'audio.wav'),'wb') as joined:
        joined.setparams((1,2,RATE,0,'NONE','not compressed'))
        for i,entry in enumerate(spec):
            src=root/f'chunk-{i}.mp3'; target=root/f'chunk-{i}.wav'
            if hashlib.sha256(src.read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError('chunk_hash_mismatch')
            result=subprocess.run(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(src),'-ac','1','-ar',str(RATE),'-c:a','pcm_s16le',str(target)],capture_output=True,timeout=120)
            if result.returncode: raise ValueError('chunk_decode_failed')
            with wave.open(str(target)) as wav:
                count=wav.getnframes(); joined.writeframes(wav.readframes(count))
            chunks.append(chunk_record(entry['asset_id'],entry['sha256'],count,offset));offset+=count
    (root/'chunks.json').write_text(json.dumps(chunks))

if __name__=='__main__':
    join(Path(sys.argv[1]))
