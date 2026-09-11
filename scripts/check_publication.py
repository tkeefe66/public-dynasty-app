"""Check indexed content without publishing private matching values.

Default: changed staged files. --all: every file in the index, also used in CI.
Optional private literal patterns live outside the worktree and are selected through
local git config publication.privatePatternsFile. Missing configured files fail closed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], stderr=subprocess.PIPE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='Scan the complete index')
    args = parser.parse_args()
    try:
        root = Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve()
        os.chdir(root)
        scanner = shutil.which('gitleaks')
        if scanner is None:
            print('Publication check blocked: install gitleaks before committing.', file=sys.stderr)
            return 2
        config = subprocess.run(['git', 'config', '--local', '--get',
                                 'publication.privatePatternsFile'], capture_output=True, check=False)
        if config.returncode not in (0, 1):
            raise RuntimeError('Cannot read private-pattern configuration')
        patterns: list[bytes] = []
        if config.returncode == 0:
            private = Path(config.stdout.decode().strip()).expanduser()
            if not private.is_absolute():
                raise RuntimeError('Private pattern path must be absolute')
            private = private.resolve()
            # .git is private Git metadata, not published working-tree content.
            gitdir = Path(git('rev-parse', '--absolute-git-dir').decode().strip()).resolve()
            if private.is_relative_to(root) and not private.is_relative_to(gitdir):
                raise RuntimeError('Private patterns must be outside publishable working-tree content')
            if not private.is_file():
                raise RuntimeError('Configured private pattern file is missing')
            if private.stat().st_mode & 0o077:
                raise RuntimeError('Private pattern file must have owner-only permissions (chmod 600)')
            patterns = [line for line in private.read_bytes().splitlines() if line]
            if not patterns:
                raise RuntimeError('Configured private pattern file is empty')
        else:
            print('Private identifier matching is not configured in this clone; checking secrets only.')
        paths = (git('ls-files', '-z') if args.all else
                 git('diff', '--cached', '--name-only', '--diff-filter=ACMRT', '-z')).split(b'\0')
        paths = sorted({p for p in paths if p})
        with tempfile.TemporaryDirectory(prefix='publication-check-') as scratch:
            base = Path(scratch)
            export = base / 'content'
            export.mkdir()
            configfile = base / 'scanner.toml'
            configfile.write_text('[extend]\nuseDefault = true\n')
            ignore = base / 'empty-ignore'
            ignore.mkdir()
            blocked = []
            for raw_path in paths:
                name = os.fsdecode(raw_path)
                path = Path(name)
                if path.is_absolute() or '..' in path.parts:
                    raise RuntimeError('Unexpected index path')
                data = git('show', ':' + name)
                if any(pattern in data or pattern in raw_path for pattern in patterns):
                    safe_path = raw_path
                    for pattern in patterns:
                        safe_path = safe_path.replace(pattern, b'[private]')
                    blocked.append(os.fsdecode(safe_path))
                target = export / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if blocked:
                for name in blocked:
                    print(f'Private identifier found in indexed file: {name}', file=sys.stderr)
                return 1
            if not paths:
                print('No added or modified indexed files to scan.')
                return 0
            result = subprocess.run([
                scanner, 'dir', str(export), '--config', str(configfile),
                '--gitleaks-ignore-path', str(ignore), '--ignore-gitleaks-allow',
                '--redact', '--no-banner', '--no-color', '--max-archive-depth=2',
            ], check=False)
            return result.returncode
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        # Do not include command output or file contents in diagnostics.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f'Publication check could not complete: {message}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
