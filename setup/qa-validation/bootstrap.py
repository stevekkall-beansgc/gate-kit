#!/usr/bin/env python3
"""Prepare the explicitly pinned public QA executor; never run its tests/tasks."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_REPOSITORY = "https://github.com/stevekkall-beansgc/qa-kit.git"


def git(root, *args):
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'LANG', 'LC_ALL', 'TZ'}}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(['git', '-c', 'credential.helper=', '-c', 'credential.interactive=false',
                             '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
                             '-C', str(root), *args], env=env, capture_output=True,
                            text=True, timeout=90)
    if result.returncode:
        raise ValueError('public QA fixture Git operation failed')
    return result.stdout.strip()


def load_pin(root):
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValueError('duplicate fixture pin key')
            data[key] = value
        return data
    pin = json.loads((root / 'setup/qa-validation/fixture.json').read_text(), object_pairs_hook=unique)
    if (not isinstance(pin, dict) or set(pin) != {'schema', 'repository', 'commit', 'executor_sha256'}
            or pin['schema'] != 'gate-kit.qa-executor-fixture/v1'
            or pin['repository'] != PUBLIC_REPOSITORY
            or not isinstance(pin['commit'], str) or not re.fullmatch(r'[0-9a-f]{40}', pin['commit'])
            or not isinstance(pin['executor_sha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', pin['executor_sha256'])):
        raise ValueError('unsupported or malformed public QA fixture pin')
    return pin


def verify(path, pin):
    if path.is_symlink() or not path.is_dir():
        raise ValueError('QA fixture directory is missing or a symlink')
    if (Path(git(path, 'rev-parse', '--show-toplevel')).resolve() != path.resolve()
            or git(path, 'rev-parse', 'HEAD') != pin['commit']
            or git(path, 'status', '--porcelain', '--untracked-files=all')):
        raise ValueError('QA fixture is not clean/exact')
    flags = git(path, 'ls-files', '-v', '-z').split('\0')
    if any(row and (not row[0].isupper() or row[0] == 'S') for row in flags):
        raise ValueError('QA fixture hidden index flags are unsupported')
    for row in git(path, 'ls-tree', '-rz', 'HEAD').split('\0'):
        if not row:
            continue
        metadata, name = row.split('\t', 1)
        mode, kind, blob = metadata.split()
        current = path
        for part in Path(name).parts:
            current /= part
            if current.is_symlink():
                raise ValueError('QA fixture tracked symlink is unsupported')
        if kind != 'blob' or mode not in ('100644', '100755') or not current.is_file():
            raise ValueError('QA fixture unsupported tracked source')
        data = current.read_bytes()
        physical = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if physical != blob or bool(current.stat().st_mode & 0o111) != (mode == '100755'):
            raise ValueError('QA fixture physical bytes/modes differ from HEAD')
    executor = path / 'bin/validation.py'
    if executor.is_symlink() or executor.parent.is_symlink() or not executor.is_file():
        raise ValueError('QA fixture executor is not a regular file')
    git(path, 'ls-files', '--error-unmatch', 'bin/validation.py')
    if hashlib.sha256(executor.read_bytes()).hexdigest() != pin['executor_sha256']:
        raise ValueError('QA fixture executor digest mismatch')


def bootstrap(root=ROOT):
    root = Path(root).resolve()
    pin = load_pin(root)
    parent = root / '.qa-fixtures'
    if parent.is_symlink():
        raise ValueError('QA fixture parent must not be a symlink')
    destination = parent / 'qa-kit'
    if destination.exists() or destination.is_symlink():
        verify(destination, pin)
        return destination
    parent.mkdir(exist_ok=True)
    # Only this newly allocated scratch clone is disposable; existing fixtures
    # are verified/refused, never reset, replaced or deleted by bootstrap.
    with tempfile.TemporaryDirectory(prefix='qa-kit-bootstrap-', dir=parent) as directory:
        scratch = Path(directory)
        git(scratch, 'init', '-q')
        git(scratch, 'fetch', '--depth=1', pin['repository'], pin['commit'])
        git(scratch, 'checkout', '--detach', '-q', pin['commit'])
        verify(scratch, pin)
        if destination.exists() or destination.is_symlink():
            raise ValueError('QA fixture destination appeared during bootstrap')
        scratch.rename(destination)
    return destination


if __name__ == '__main__':
    try:
        print('public QA executor fixture ready: ' + str(bootstrap()))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        raise SystemExit('public QA executor fixture bootstrap failed; no tests were run')
