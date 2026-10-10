"""Fail-closed Linux child boundary. Supervisor secrets never enter this mount/PID namespace."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess

DEADLINE = 1200
MEMORY = 2 * 1024**3
SCRATCH = 4 * 1024**3

def command(argv, work):
    work = Path(work).resolve()
    if not work.is_dir() or work.is_symlink():
        raise RuntimeError("Media scratch missing; allocate private bounded scratch")
    os.chmod(work, 0o777)
    # No host root/home/checkout bind. /opt/recap in image contains only packaged
    # worker code and synthetic tests; never mount a developer checkout there.
    args = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
        "--uid", "65534", "--gid", "65534", "--clearenv"]
    for path in ("/usr", "/lib", "/lib64", "/bin", "/opt/venv", "/opt/recap", "/ms-playwright"):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    if Path("/opt/model").exists():
        args += ["--dir", "/opt/model"]
        for name in ("model.bin", "tokenizer.json", "config.json", "vocabulary.txt"):
            args += ["--ro-bind", "/opt/model/"+name, "/opt/model/"+name]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/etc",
        "--ro-bind", "/etc/fonts", "/etc/fonts", "--ro-bind", "/etc/alternatives", "/etc/alternatives",
        "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache", "--bind", str(work), "/work", "--chdir", "/work"]
    for key, value in {"PATH":"/opt/venv/bin:/usr/bin:/bin", "HOME":"/work", "TMPDIR":"/work", "LANG":"C.UTF-8",
            "PYTHONPATH":"/opt/recap:/opt/recap/api:/opt/recap/src", "PLAYWRIGHT_BROWSERS_PATH":"/ms-playwright"}.items():
        args += ["--setenv", key, value]
    return args + ["--", *argv]

def require_limits(work):
    try:
        memory = int(Path("/sys/fs/cgroup/memory.max").read_text())
        fs = os.statvfs(work)
        mount = subprocess.check_output(["findmnt", "-n", "-o", "FSTYPE", "-T", str(work)], text=True).strip()
        if memory > MEMORY or mount != "tmpfs" or fs.f_blocks * fs.f_frsize > SCRATCH:
            raise ValueError()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError("Media resource isolation unavailable; require cgroup memory <=2 GiB and scratch tmpfs <=4 GiB") from None

def probe(work):
    require_limits(work)
    # Called by credentialed supervisor itself. Neither its /proc environment nor
    # a secret file outside assigned scratch may be visible to the child.
    marker = "recap-boundary-sentinel"
    secret = Path(work).parent / "supervisor-secret"
    secret.write_text(marker)
    code = """import json,os,pathlib,socket,sys
paths=list(pathlib.Path('/proc').glob('[0-9]*/environ'))
visible=[]
for p in paths:
 try: visible.append(p.read_bytes())
 except OSError: pass
sock=socket.socket(); sock.settimeout(.2)
try: sock.connect(('1.1.1.1',443)); network=True
except OSError: network=False
separate=os.readlink('/proc/self/ns/net')!=sys.argv[2]
print(json.dumps(dict(isolated=os.getuid()!=0 and separate and not network and not pathlib.Path(sys.argv[1]).exists() and all(b'recap-boundary-sentinel' not in x for x in visible),uid=os.getuid(),network=network,separate_network_namespace=separate,pids=len(paths))))
"""
    try:
        result = subprocess.run(command(["/usr/bin/python3", "-c", code, str(secret), os.readlink('/proc/self/ns/net')], work), env={"PATH":"/usr/bin:/bin"},
            capture_output=True, text=True, timeout=15)
        report = json.loads(result.stdout) if result.returncode == 0 else {}
        if not report.get("isolated"):
            raise RuntimeError("Media namespace isolation unavailable; hold worker until supported mount/user/PID/network boundary is configured")
        return report
    finally:
        secret.unlink(missing_ok=True)

async def run(argv, work, timeout=DEADLINE):
    """One namespace init owns every descendant; killing it kills entire PID namespace."""
    require_limits(work)
    proc = await asyncio.create_subprocess_exec(*command(argv, work), env={"PATH":"/usr/bin:/bin"},
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), min(timeout, DEADLINE))
        if proc.returncode:
            # Packaged tools only; never return raw private input or credentials.
            raise RuntimeError("Isolated media process failed; inspect private scratch evidence and packaged runtime")
    finally:
        if proc.returncode is None:
            os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
