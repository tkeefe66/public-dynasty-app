"""Idempotent VM bootstrap; credentials arrive on stdin, never command arguments."""
import json
import os
import re
import subprocess
import sys


def main():
    value = json.load(sys.stdin)
    image = value['image']
    environment = value['env']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
        raise ValueError('Immutable worker image required')
    if set(environment) != {'MEDIA_API_URL', 'MEDIA_WORKER_TOKEN', 'ELEVENLABS_API_KEY'}:
        raise ValueError('Unexpected worker credential')
    if any(not isinstance(v, str) or not v or '\n' in v or '\r' in v for v in environment.values()):
        raise ValueError('Invalid worker configuration')
    existing = subprocess.run(['docker', 'inspect', 'recap-worker'], capture_output=True)
    if existing.returncode == 0:
        container = json.loads(existing.stdout)[0]
        if container['Image'] != image:
            raise ValueError('Existing worker image differs; stop VM before replacing')
        if not container['State']['Running']:
            subprocess.run(['docker', 'start', 'recap-worker'], check=True, capture_output=True)
        return
    path = '/opt/recap-worker.env'
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(''.join(k + '=' + v + '\n' for k, v in environment.items()))
    subprocess.run(['docker', 'run', '-d', '--name', 'recap-worker', '--restart', 'unless-stopped',
        '--memory', '2g', '--memory-swap', '2g', '--cpus', '2', '--pids-limit', '512',
        '--mount', 'type=bind,src=/opt/recap-model,dst=/opt/model,readonly',
        '--tmpfs', '/scratch:size=4g', '--cap-add', 'SYS_ADMIN',
        '--security-opt', 'seccomp=unconfined', '--security-opt', 'apparmor=unconfined',
        '--security-opt', 'systempaths=unconfined', '--env-file', path,
        '-e', 'TMPDIR=/scratch', image], check=True, capture_output=True)


if __name__ == '__main__':
    try:
        main()
        print('worker_running')
    except Exception:
        print('Worker startup failed; inspect image/runtime configuration', file=sys.stderr)
        sys.exit(1)
