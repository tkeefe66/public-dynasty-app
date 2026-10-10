"""Offline benchmark driver. Optional saved inputs must be private copied files."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import threading
import time
from media.runtime import probe, run
from media.timeline import synthetic_episode, digest_file
from scripts.check_recap_media_runtime import tone

root = Path("/scratch/benchmark")
root.mkdir()
probe(root)
if len(sys.argv) > 1 and sys.argv[1] == "saved":
    shutil.copyfile("/inputs/audio.wav", root / "audio.wav")
    episode = json.loads(Path("/inputs/episode.json").read_text())
else:
    duration = 2 if len(sys.argv)>1 and sys.argv[1] == "short" else 240
    episode = synthetic_episode(duration)
    tone(root / "audio.wav", duration)
    episode["audio_sha256"] = digest_file(root / "audio.wav")
(root / "episode.json").write_text(json.dumps(episode))
peak = {"memory_bytes": 0, "scratch_bytes": 0}
stopped = threading.Event()
def measure():
    while not stopped.wait(.2):
        peak["memory_bytes"] = max(peak["memory_bytes"], int(Path("/sys/fs/cgroup/memory.current").read_text()))
        peak["scratch_bytes"] = max(peak["scratch_bytes"], sum(p.stat().st_size for p in root.rglob("*") if p.is_file()))
thread = threading.Thread(target=measure)
thread.start()
started = time.monotonic()
try:
    asyncio.run(run(["/usr/bin/node", "/opt/recap/media/render/render.cjs", "--episode", "/work/episode.json", "--output", "/work"], root))
    try:
        asyncio.run(run(["/opt/venv/bin/python", "-m", "media.qa", "/work"], root))
    except RuntimeError:
        if not (root / "qa.json").exists():
            raise
finally:
    stopped.set(); thread.join()
    peak["sampled_memory_bytes"] = peak["memory_bytes"]
    peak["memory_bytes"] = int(Path("/sys/fs/cgroup/memory.peak").read_text())
    peak["wall_seconds"] = time.monotonic()-started
    peak["duration_seconds"] = episode["duration"]
    (root / "resources.json").write_text(json.dumps(peak))
    shutil.copytree(root, "/outputs", dirs_exist_ok=True)
    print(json.dumps(peak))
