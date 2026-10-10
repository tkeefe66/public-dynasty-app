"""Deterministic free public derivatives; invoked inside the media sandbox."""
import html
import json
import math
from pathlib import Path
import subprocess

from media.timeline import digest_file

DERIVATIVES = {'audio.mp3':'audio/mpeg', 'poster.jpg':'image/jpeg', 'captions.vtt':'text/vtt'}


def timestamp(value):
    milliseconds = round(value*1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}'


def captions_vtt(episode):
    lines = ['WEBVTT', '']
    previous = 0
    for cue in episode['captions']:
        start, end = cue['start'], cue['end']
        if not all(type(v) in (float,int) and math.isfinite(v) for v in (start,end)) or not previous <= start < end:
            raise ValueError('caption_time_invalid')
        text = html.escape(' '.join(cue['text'].split()), quote=False)
        if not text or '\x00' in text:
            raise ValueError('caption_text_invalid')
        lines.extend([f'{timestamp(start)} --> {timestamp(end)}', text, ''])
        previous = end
    return '\n'.join(lines)+'\n'


def call(args):
    result = subprocess.run(args, capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError('public_derivative_decode_failed')
    return result.stdout


def package(root, episode):
    root = Path(root)
    if digest_file(root/'audio.wav') != episode['audio_sha256']:
        raise ValueError('public_audio_source_changed')
    common = ['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-y']
    call([*common,'-i',str(root/'audio.wav'),'-map_metadata','-1','-c:a','libmp3lame','-b:a','128k',str(root/'audio.mp3')])
    call([*common,'-i',str(root/'video.mp4'),'-map_metadata','-1','-frames:v','1','-q:v','2',str(root/'poster.jpg')])
    (root/'captions.vtt').write_text(captions_vtt(episode), encoding='utf-8')
    return measure(root, episode)


def measure(root, episode):
    root = Path(root)
    def probe(name):
        return json.loads(call(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_streams','-show_format','-of','json',str(root/name)]))
    for name in ('audio.mp3','poster.jpg'):
        call(['ffmpeg','-v','error','-nostdin','-xerror','-protocol_whitelist','file,pipe','-i',str(root/name),'-f','null','-'])
    audio, poster = probe('audio.mp3'), probe('poster.jpg')
    return dict(audio_codec=audio['streams'][0]['codec_name'], audio_duration=float(audio['format']['duration']),
        poster_codec=poster['streams'][0]['codec_name'], width=poster['streams'][0]['width'], height=poster['streams'][0]['height'],
        source_sha256=digest_file(root/'audio.wav'), hashes={name:digest_file(root/name) for name in DERIVATIVES},
        captions=(root/'captions.vtt').read_text(encoding='utf-8'))


def evidence_issues(report, episode, hashes):
    try:
        duration = report['audio_duration']
        if (type(duration) not in (float,int) or not math.isfinite(duration)
                or report['audio_codec'] != 'mp3' or abs(duration-episode['audio_duration']) > .1
                or report['poster_codec'] != 'mjpeg' or (report['width'],report['height']) != (1280,720)
                or report['source_sha256'] != episode['audio_sha256']
                or report['captions'] != captions_vtt(episode)
                or report['hashes'] != {name:hashes[name] for name in DERIVATIVES}):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        return ['public_derivatives_invalid']
    return []


if __name__ == '__main__':
    import sys
    root = Path(sys.argv[1])
    package(root, json.loads((root/'episode.json').read_text()))
