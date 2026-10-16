import io
import json
from types import SimpleNamespace

import pytest

from media.controller import bootstrap


def configure(monkeypatch, image='sha256:' + 'a' * 64):
    payload = {'image': image, 'env': {'MEDIA_API_URL': 'https://api.example.test',
        'MEDIA_WORKER_TOKEN': 'synthetic-worker-token', 'ELEVENLABS_API_KEY': 'synthetic-provider-key'}}
    monkeypatch.setattr(bootstrap.sys, 'stdin', io.StringIO(json.dumps(payload)))
    return payload


def test_bootstrap_reconnects_without_rewriting_credentials_or_duplicate_container(monkeypatch):
    payload = configure(monkeypatch)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps([{'Image': payload['image'], 'State': {'Running': True}}]))
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    monkeypatch.setattr(bootstrap.os, 'open', lambda *a: pytest.fail('rewrote existing credentials'))
    bootstrap.main()
    assert calls == [['docker', 'inspect', 'recap-worker']]


def test_bootstrap_rejects_mutable_image_before_any_process_or_credentials(monkeypatch):
    configure(monkeypatch, 'recap:latest')
    monkeypatch.setattr(bootstrap.subprocess, 'run', lambda *a, **kw: pytest.fail('unbound image executed'))
    with pytest.raises(ValueError, match='Immutable'):
        bootstrap.main()


def test_bootstrap_refuses_conflicting_existing_image(monkeypatch):
    configure(monkeypatch)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps([{'Image': 'sha256:' + 'b' * 64, 'State': {'Running': False}}]))
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    with pytest.raises(ValueError, match='differs'):
        bootstrap.main()
    assert len(calls) == 1


def test_new_worker_mounts_only_pinned_model_readonly_and_keeps_secrets_out_of_argv(monkeypatch, tmp_path):
    configure(monkeypatch)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1 if args[1]=='inspect' else 0, stdout='')
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    original_open = bootstrap.os.open
    monkeypatch.setattr(bootstrap.os, 'open', lambda path, flags, mode: original_open(tmp_path/'env', flags, mode))
    bootstrap.main()
    command = calls[-1]
    assert command[command.index('--mount')+1] == 'type=bind,src=/opt/recap-model,dst=/opt/model,readonly'
    assert 'synthetic-worker-token' not in ' '.join(command)
    assert 'synthetic-provider-key' not in ' '.join(command)
    assert (tmp_path/'env').stat().st_mode & 0o777 == 0o600
