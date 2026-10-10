"""Recompute layout qualification from bounded raw canvas geometry, on worker/API."""
import math

def geometry_issues(rows, episode):
    if not isinstance(rows,list) or not rows or len(rows)>4096:
        return ['geometry_missing']
    issues=[];captions=set();scenes=set();keys=set();cue_lines={};scene_rows={}
    try:
        for r in rows:
            if r['key'] in keys: raise ValueError()
            keys.add(r['key'])
            if (r['family'] not in ('Bricolage','Geist','GeistMono') or type(r['text']) is not str
                or len(r['text'])>2000 or any(type(r[k]) not in (int,float) or not math.isfinite(r[k]) for k in ('size','weight','left','right','top','bottom','samples'))
                or r['size']<=0 or not 100<=r['weight']<=1000 or type(r['samples']) is not int or r['samples']<1 or r['left']>r['right'] or r['top']>r['bottom']):
                raise ValueError()
            bounds=[56,0,1224,675] if r['caption'] is not None else [0,0,1280,716]
            if r['bounds']!=bounds: raise ValueError()
            margins=[r['left']-bounds[0],r['top']-bounds[1],bounds[2]-r['right'],bounds[3]-r['bottom']]
            if (len(r['margins'])!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in r['margins']) or any(abs(a-b)>.001 for a,b in zip(r['margins'],margins))): raise ValueError()
            if min(margins)<-.001: issues.append('caption_overflow' if r['caption'] is not None else 'text_overflow')
            if r['caption'] is not None:
                cue=r['caption'];captions.add(cue);cue_lines.setdefault(cue,[]).append(r)
                if type(cue) is not int or not 0<=cue<len(episode['captions']) or r['text'] not in episode['captions'][cue]['text'] or r['size']!=30 or r['family']!='Geist': raise ValueError()
            else:
                if type(r['scene']) is not int: raise ValueError()
                scenes.add(r['scene']);scene_rows.setdefault(r['scene'],[]).append(r)
        for cue,lines in cue_lines.items():
            if ' '.join(r['text'] for r in sorted(lines,key=lambda r:int(r['key'].rsplit(':',1)[1]))).split()!=episode['captions'][cue]['text'].split(): raise ValueError()
        for scene,items in scene_rows.items():
            slots=sorted(int(r['key'].rsplit(':',1)[1]) for r in items)
            if slots!=list(range(len(items))) or not any(r['text']=='CAL MERCER / FICTIONAL REPORTER / AI VOICE' for r in items): raise ValueError()
        if captions!={i for i,c in enumerate(episode['captions']) if c['text'].strip()} or scenes!=set(range(len(episode['scenes']))):
            issues.append('geometry_missing')
    except (KeyError,ValueError,TypeError,IndexError):
        issues.append('geometry_invalid')
    return sorted(set(issues))
