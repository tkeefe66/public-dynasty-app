"""Measure actual decoded media; reports never inherit worker success booleans."""
import json
import math
from pathlib import Path
import re
import subprocess

from media.timeline import digest, digest_file, validate_episode

def check_sync(*, audio_start_ms: float, video_start_ms: float) -> list[str]:
    return ["av_sync_exceeded"] if abs(audio_start_ms - video_start_ms) > 100 else []

def _call(args):
    return subprocess.run(args, capture_output=True, timeout=120)

def _probe(path):
    result = _call(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(path)])
    if result.returncode:
        raise ValueError("decode_failed")
    return json.loads(result.stdout)

def measure_bundle(bundle_dir: Path, episode: dict) -> dict:
    root = Path(bundle_dir)
    issues = validate_episode(episode)
    report = dict(version="recap-media-qa-1", episode_digest=digest(episode), issues=issues,
                  decoded=False, measurements={}, hashes={})
    try:
        for filename in ("video.mp4", "audio.wav", "render.json"):
            report["hashes"][filename] = digest_file(root / filename)
        render = json.loads((root / "render.json").read_text())
        from media.geometry import geometry_issues
        issues.extend(geometry_issues(render.get("geometry"),episode))
        if render["fonts"] != episode["fonts"]:
            issues.append("font_missing")
        if render["frame_count"] != math.ceil(episode["duration"]*30):
            issues.append("frame_count_invalid")
        report["render"] = render
        actual = _probe(root / "video.mp4")
        source = _probe(root / "audio.wav")
        video = next((s for s in actual["streams"] if s["codec_type"] == "video"), None)
        audio = next((s for s in actual["streams"] if s["codec_type"] == "audio"), None)
        if not video:
            issues.append("video_missing")
        if not audio:
            issues.append("audio_missing")
        if not video or not audio:
            return report
        decoded = _call(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(root/"video.mp4"), "-f", "null", "-"])
        report["decoded"] = decoded.returncode == 0
        if not report["decoded"]:
            issues.append("decode_failed")
        # ffprobe -show_frames timestamps come from actual decoder, including AAC
        # priming/discard effects; container declared start times alone are insufficient.
        first = {}
        for kind in ("a", "v"):
            decoded_frames = _call(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", kind+":0",
                "-read_intervals", "%+1", "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(root/"video.mp4")])
            rows = json.loads(decoded_frames.stdout)["frames"]
            first[kind] = float(rows[0]["best_effort_timestamp_time"]) * 1000
        issues.extend(check_sync(audio_start_ms=first["a"], video_start_ms=first["v"]))
        source_duration = float(source["format"]["duration"])
        m = report["measurements"]
        from media.audio_seams import measure_seams, seam_issues, RULES, pcm_frame_count, decoded_length_issues
        m['seam_rules']=RULES
        m['chunk_timing']=episode['chunk_timing']
        encoded=root/'qa-decoded.wav'
        seam_decode=_call(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(root/'video.mp4'),'-vn','-ac','1','-ar','44100','-c:a','pcm_s16le','-y',str(encoded)])
        if seam_decode.returncode: raise ValueError()
        m['source_audio_frames']=pcm_frame_count(root/'audio.wav')
        m['decoded_audio_frames']=pcm_frame_count(encoded)
        content_frames=episode['chunk_timing'][-1]['end_frame']
        length_issues=decoded_length_issues(m['source_audio_frames'],m['decoded_audio_frames'],content_frames)
        issues.extend(length_issues)
        m['source_seams']=measure_seams(root/'audio.wav',episode['chunk_timing']) if m['source_audio_frames']>=content_frames else []
        m['encoded_seams']=measure_seams(encoded,episode['chunk_timing']) if m['decoded_audio_frames']>=content_frames else []
        encoded.unlink()
        issues.extend(seam_issues(m['source_seams'],episode['chunk_timing']))
        issues.extend(seam_issues(m['encoded_seams'],episode['chunk_timing']))
        m.update(audio_start_ms=first["a"], video_start_ms=first["v"], sync_error_ms=abs(first["a"]-first["v"]),
            audio_duration=float(audio["duration"]), video_duration=float(video["duration"]), source_duration=source_duration,
            bytes=(root/"video.mp4").stat().st_size, frames=int(video["nb_frames"]))
        if abs(m["audio_duration"]-source_duration) > .1:
            issues.append("audio_ending_missing")
        if abs(m["video_duration"]-episode["duration"]) > 1/30+.001 or m["frames"] != math.ceil(episode["duration"]*30):
            issues.append("video_ending_missing")
        if source_duration > episode["duration"] + .1 or episode["duration"]-source_duration > 2:
            issues.append("timeline_audio_duration_mismatch")
        if (video["width"], video["height"], video["codec_name"], audio["codec_name"]) != (1280,720,"h264","aac"):
            issues.append("media_format_invalid")
        analysis = _call(["ffmpeg", "-hide_banner", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(root/"video.mp4"),
            "-vn", "-af", "silencedetect=noise=-50dB:d=2,astats=metadata=0:reset=0", "-f", "null", "-"])
        log = analysis.stderr.decode(errors="replace")
        m["silence_seconds"] = [float(v) for v in re.findall(r"silence_duration: ([\d.]+)", log)]
        m["peak_db"] = [float(v) for v in re.findall(r"Peak level dB: ([-\d.]+)", log)]
        m["rms_db"] = [float(v) for v in re.findall(r"RMS level dB: ([-\d.]+)", log)]
        if m["silence_seconds"]:
            issues.append("unexpected_silence")
        if not m["rms_db"] or max(m["rms_db"]) < -50:
            issues.append("audio_silent")
        if m["peak_db"] and max(m["peak_db"]) >= -.01:
            issues.append("audio_clipping")
        if report["hashes"]["audio.wav"] != episode["audio_sha256"]:
            issues.append("audio_hash_mismatch")
        m["representative_frames"] = []
        for frame in render["representative_frames"]:
            name = "decoded-" + frame["file"]
            if not re.fullmatch(r"decoded-frame-\d{7}\.png", name):
                raise ValueError()
            decoded_frame = _call(["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-ss", str(frame["time"]),
                "-i", str(root/"video.mp4"), "-frames:v", "1", "-y", str(root/name)])
            if decoded_frame.returncode or not (root/name).exists():
                issues.append("representative_decode_failed")
                continue
            # Decode and retain actual encoded pixels for phone-size review.
            m["representative_frames"].append(dict(file=name, time=frame["time"], sha256=digest_file(root/name)))
    except (OSError, KeyError, ValueError, IndexError, subprocess.SubprocessError):
        issues.append("decode_failed")
    report["issues"] = sorted(set(issues))
    return report

if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1])
    result = measure_bundle(root, json.loads((root/"episode.json").read_text()))
    (root/"qa.json").write_text(json.dumps(result))
    raise SystemExit(bool(result["issues"]))
