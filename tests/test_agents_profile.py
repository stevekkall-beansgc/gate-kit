"""Offline behavior tests for the proposed immutable agents workflow profile."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/compliance.yml').read_text()
PROFILE = textwrap.dedent(WORKFLOW.split("      - name: Prepare isolated agents compliance profile\n", 1)[1].split("python3 - <<'PY'\n", 1)[1].split('          PY\n', 1)[0])
NS = {'__name__': 'profile_test'}
exec(compile(PROFILE, '<workflow-profile>', 'exec'), NS)
CHECKER = (ROOT / 'bin/compliance.py').read_text()
ENV = {'RUNNER_ENVIRONMENT': 'github-hosted', 'RUNNER_OS': 'macOS', 'GATE_RUNNER': 'macos-15'}
SHA = 'a' * 40


class TestTimeoutAdaptation(unittest.TestCase):
    def test_checksum_rejects_other_code_or_timeout_drift(self):
        for source in (CHECKER + '# changed\n', CHECKER.replace('timeout=900', 'timeout=901'),
                       CHECKER.replace('return 1 if failures else 0', 'return 0')):
            with self.subTest(source=source[-30:]), self.assertRaises(RuntimeError):
                NS['adapt_checker'](source)

    def test_only_two_timeout_literals_change(self):
        adapted = NS['adapt_checker'](CHECKER)
        self.assertEqual(adapted, CHECKER.rstrip('\n').replace('timeout=900', 'timeout=14400').replace('timeout 900s', 'timeout 14400s') + '\n')
        before, after = ast.parse(CHECKER), ast.parse(adapted)
        changed = []
        for node in ast.walk(after):
            if isinstance(node, ast.Constant) and node.value == 14400:
                changed.append(node.value)
                node.value = 900
            elif isinstance(node, ast.Constant) and node.value == 'timeout 14400s':
                changed.append(node.value)
                node.value = 'timeout 900s'
        self.assertEqual(changed, [14400, 'timeout 14400s'])
        self.assertEqual(ast.dump(before), ast.dump(after))

    def test_real_checker_keeps_docs_setup_unit_full_and_failures(self):
        namespace = {'__name__': 'adapted_test', '__file__': str(ROOT / 'bin/compliance.py')}
        exec(compile(NS['adapt_checker'](CHECKER), '<adapted-checker>', 'exec'), namespace)
        for unit_exit, full in ((0, False), (9, False), (0, True)):
            with self.subTest(unit_exit=unit_exit, full=full), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                unit = ['/bin/sh', '-c', f'test -f setup.ok && exit {unit_exit}']
                (root/'AGENTS.md').write_text('## Test commands\n' + ' '.join(unit))
                (root/'README.md').write_text('See AGENTS.md')
                manifest = root/'manifest.json'
                manifest.write_text(json.dumps({'repos': [{'name': 'agents', 'status': 'unit-only', 'path': '/unused',
                    'setup': {'cmd': ['/bin/sh', '-c', 'touch setup.ok']},
                    'unit': {'cmd': unit}, 'e2e': {'cmd': ['/bin/sh', '-c', 'exit 7']}}]}))
                namespace['MANIFEST'] = manifest
                args = ['compliance.py', '--repo', 'agents', '--root', str(root), '--markdown'] + (['--full'] if full else [])
                output = io.StringIO()
                with mock.patch.object(sys, 'argv', args), contextlib.redirect_stdout(output):
                    result = namespace['main']()
                self.assertEqual(result, 1 if unit_exit or full else 0)
                checks = json.loads(output.getvalue().splitlines()[-1])['repos'][0]['checks']
                self.assertEqual([c['name'] for c in checks], ['docs', 'setup', 'unit'] + (['e2e'] if full else []))
                self.assertTrue((root/'setup.ok').is_file())
                self.assertEqual(checks[2]['ok'], unit_exit == 0)

    def test_timeout_still_fails_with_correct_budget(self):
        namespace = {'__name__': 'adapted_test', '__file__': str(ROOT/'bin/compliance.py')}
        exec(compile(NS['adapt_checker'](CHECKER), '<adapted-checker>', 'exec'), namespace)
        with mock.patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired(['test'], 14400)) as run:
            result = namespace['sh'](['test'], ROOT)
        self.assertFalse(result['ok'])
        self.assertEqual(result['tail'], 'timeout 14400s')
        self.assertEqual(run.call_args.kwargs['timeout'], 14400)


class TestCanonicalPreparation(unittest.TestCase):
    def test_existing_target_and_symlink_ancestor_refuse_before_commands(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            existing = root/'exists'
            existing.mkdir()
            (existing/'sentinel').write_text('keep')
            (root/'alias').symlink_to(existing, target_is_directory=True)
            (root/'broken').symlink_to(root/'missing')
            empty = root/'empty'
            empty.mkdir()
            for target in (existing, empty, root/'alias/child', root/'broken'):
                with self.subTest(target=target), mock.patch.object(subprocess, 'run') as run, mock.patch.object(subprocess, 'check_output') as read:
                    with self.assertRaises(RuntimeError):
                        NS['prepare_checkout'](root/'caller', target, SHA, ENV)
                    run.assert_not_called()
                    read.assert_not_called()
            self.assertEqual((existing/'sentinel').read_text(), 'keep')

    def test_local_self_hosted_wrong_os_and_wrong_runner_cannot_touch_root(self):
        for change in ({'RUNNER_ENVIRONMENT': 'self-hosted'}, {'RUNNER_ENVIRONMENT': ''},
                       {'RUNNER_OS': 'Linux'}, {'GATE_RUNNER': 'beans-mac'}):
            with tempfile.TemporaryDirectory() as raw, mock.patch.object(subprocess, 'run') as run, mock.patch.object(subprocess, 'check_output') as read:
                with self.assertRaises(RuntimeError):
                    NS['prepare_checkout'](Path(raw).resolve()/'caller', Path(raw).resolve()/'target', SHA, {**ENV, **change})
                run.assert_not_called()
                read.assert_not_called()

    def test_wrong_input_sha_denies_before_creation(self):
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(subprocess, 'run') as run, mock.patch.object(subprocess, 'check_output', return_value='b'*40):
            with self.assertRaises(RuntimeError):
                NS['prepare_checkout'](Path(raw).resolve()/'caller', Path(raw).resolve()/'target', SHA, ENV)
            run.assert_not_called()

    def test_empty_exclusive_creation_and_exact_copy(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            caller, target = root/'caller', root/'parent/target'
            caller.mkdir()
            (caller/'sentinel').write_text('exact source bytes')
            calls = []
            def owned_commands(argv, **kwargs):
                self.assertTrue(kwargs['check'])
                calls.append(argv)
                if argv[:3] == ['sudo', 'mkdir', '-p']:
                    Path(argv[3]).mkdir(parents=True, exist_ok=True)
                elif argv[:4] == ['sudo', 'mkdir', '-m', '700']:
                    Path(argv[4]).mkdir(mode=0o700)
                else:
                    self.assertEqual(argv, ['sudo', 'chown', f'{os.getuid()}:{os.getgid()}', str(target)])
            with mock.patch.object(subprocess, 'run', side_effect=owned_commands), mock.patch.object(subprocess, 'check_output', return_value=SHA+'\n') as read:
                NS['prepare_checkout'](caller, target, SHA, ENV)
            self.assertEqual((target/'sentinel').read_bytes(), (caller/'sentinel').read_bytes())
            self.assertEqual(read.call_count, 2)
            self.assertEqual(len(calls), 3)
            self.assertFalse(any('-R' in call or '-r' in call for call in calls))

    def test_exclusive_mkdir_race_does_not_chown_or_copy(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            calls = []
            def denied_mkdir(argv, **kwargs):
                calls.append(argv)
                if argv[:4] == ['sudo', 'mkdir', '-m', '700']:
                    raise subprocess.CalledProcessError(1, argv)
            with mock.patch.object(subprocess, 'run', side_effect=denied_mkdir), mock.patch.object(subprocess, 'check_output', return_value=SHA), mock.patch.object(NS['shutil'], 'copytree') as copy:
                with self.assertRaises(subprocess.CalledProcessError):
                    NS['prepare_checkout'](root/'caller', root/'target', SHA, ENV)
                copy.assert_not_called()
            self.assertEqual(len(calls), 2)


class TestActualShellRouting(unittest.TestCase):
    def test_both_profiles_full_flag_env_and_pipeline_failure(self):
        step = WORKFLOW.split('      - name: Run compliance gate\n', 1)[1].split('      - name: Attach summary', 1)[0]
        script = textwrap.dedent(step.split('        run: |\n', 1)[1])
        for repo in ('agents', 'agency'):
            for full in ('true', 'false'):
                for code in (0, 9):
                    with self.subTest(repo=repo, full=full, code=code), tempfile.TemporaryDirectory() as raw:
                        root = Path(raw).resolve()
                        shim = root/'python3'
                        shim.write_text('#!/bin/sh\nprintf "%s\\n" "$*" "$PYTHONPATH" > "$CAPTURE"\nexit "$TEST_EXIT"\n')
                        shim.chmod(0o700)
                        capture = root/'capture.txt'
                        env = {**os.environ, 'PATH': str(root)+os.pathsep+os.environ['PATH'], 'GATE_REPO': repo,
                               'GATE_FULL': full, 'CAPTURE': str(capture), 'TEST_EXIT': str(code), 'PYTHONPATH': 'unchanged'}
                        result = subprocess.run(['/bin/bash', '-e', '-c', script], cwd=root, env=env, capture_output=True, text=True)
                        self.assertEqual(result.returncode, code, result.stderr)
                        argv, pythonpath = capture.read_text().splitlines()
                        self.assertEqual('--full' in argv, full == 'true')
                        if repo == 'agents':
                            self.assertEqual(argv, 'compliance-with-suite-timeout.py --repo agents --root /Users/stephenkall/beans/catalog/agents --markdown' + (' --full' if full == 'true' else ''))
                            self.assertEqual(pythonpath, '/Users/stephenkall/beans/catalog/agents:/Users/stephenkall/beans/catalog/agents/src:/Users/stephenkall/beans/catalog/agents/tests')
                        else:
                            self.assertEqual(argv, 'gate-kit/bin/compliance.py --repo agency --root caller --markdown' + (' --full' if full == 'true' else ''))
                            self.assertEqual(pythonpath, 'unchanged')


if __name__ == '__main__':
    unittest.main()
