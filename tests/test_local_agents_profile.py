"""Behavioral tests of the workflow-embedded, closed self-hosted profile."""
import ast
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT/'.github/workflows/compliance.yml').read_text()
STEP = WORKFLOW.split('      - name: Guard trusted local agents runner before checkout\n', 1)[1].split('      - uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8', 1)[0]
BOOTSTRAP = textwrap.dedent(STEP.split("/opt/homebrew/bin/python3 - <<'PY'\n", 1)[1].split('          PY\n', 1)[0])
TREE = ast.parse(BOOTSTRAP)
WRAPPER = ast.literal_eval(next(node.value for node in TREE.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'wrapper' for t in node.targets)))
NS = {'__name__': 'local_profile_test'}
exec(compile(WRAPPER, '<local-profile>', 'exec'), NS)
SHA = 'a'*40


class LocalFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.canonical = self.root/'canonical'
        self.workspace = self.root/'workspace'
        self.runner_temp = self.root/'runner-temp'
        for path in (self.canonical/'.git', self.workspace/'caller', self.runner_temp):
            path.mkdir(parents=True)
        for path in (self.canonical, self.workspace/'caller'):
            (path/'source.py').write_text('original source\n')
        checker = (ROOT/'bin/compliance.py').read_text().rstrip('\n').replace('timeout=900','timeout=14400').replace('timeout 900s','timeout 14400s')+'\n'
        (self.workspace/'compliance-with-suite-timeout.py').write_text(checker)
        self.env = {'RUNNER_ENVIRONMENT': 'self-hosted', 'RUNNER_OS': 'macOS', 'GATE_RUNNER': 'beans-mac',
                    'GATE_REPO': 'agents', 'GATE_EVENT_NAME': 'push', 'GATE_REPOSITORY': NS['REPOSITORY'],
                    'GATE_EVENT_REPOSITORY': NS['REPOSITORY'], 'GATE_REF': 'refs/heads/main',
                    'GATE_EXPECTED_SHA': SHA, 'GATE_PUSH_AFTER': SHA, 'GATE_FULL': 'false',
                    'GITHUB_WORKSPACE': str(self.workspace), 'RUNNER_TEMP': str(self.runner_temp)}
        self.heads = {}
        self.dirty = {}
        self.flags = {}

    def fake_git(self, root, *args):
        if args == ('rev-parse', '--show-toplevel'):
            return str(root).encode()+b'\n'
        if args == ('rev-parse', 'HEAD'):
            return self.heads.get(root, SHA).encode()+b'\n'
        if args[0] == 'status':
            return self.dirty.get(root,b'')
        if args == ('ls-files', '-v', '-z'):
            return self.flags.get(root,b'H source.py\0')
        if args == ('ls-tree', '-r', '-z', 'HEAD'):
            data = b'original source\n'
            blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest().encode()
            return b'100644 blob ' + blob + b'\tsource.py\0'
        self.assertEqual(args, ('ls-files','-z'))
        return b'source.py\0'

    def run_checker(self, effect=None, env=None):
        with mock.patch.dict(NS, {'git': self.fake_git}), mock.patch.object(NS['runpy'], 'run_path', side_effect=effect) as run, mock.patch.dict(os.environ, env or self.env), mock.patch.object(sys, 'argv', ['test']):
            status = NS['run_compliance'](env or self.env, self.canonical)
        return status,run


class TestTrustedContext(LocalFixture):
    def test_main_and_release_push_only(self):
        for ref in ('refs/heads/main','refs/heads/release/v0.3.0','refs/heads/release/2026/september'):
            self.assertEqual(NS['validate_context']({**self.env,'GATE_REF':ref},self.canonical),SHA)
        changes = [
            {'GATE_EVENT_NAME':event} for event in ('pull_request','pull_request_target','workflow_dispatch','schedule')
        ] + [{'GATE_REF':ref} for ref in ('refs/heads/codex/work','refs/tags/v0.3.0','refs/heads/release/','refs/heads/release/a..b')]
        changes += [{'GATE_REPOSITORY':'other/Beanstalk'},{'GATE_EVENT_REPOSITORY':'other/Beanstalk'},
                    {'RUNNER_ENVIRONMENT':'github-hosted'},{'RUNNER_OS':'Linux'},{'GATE_RUNNER':'macos-15'},
                    {'GATE_REPO':'agency'},{'GATE_PUSH_AFTER':'b'*40},{'GATE_EXPECTED_SHA':'bad'}, {'GATE_FULL':'maybe'}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                NS['validate_context']({**self.env,**change},self.canonical)

    def test_workspace_and_temp_must_not_overlap_or_alias_canonical(self):
        for name in ('GITHUB_WORKSPACE','RUNNER_TEMP'):
            for path in (self.canonical,self.root,self.canonical/'.git'):
                with self.subTest(name=name,path=path),self.assertRaises(RuntimeError):
                    NS['validate_context']({**self.env,name:str(path)},self.canonical)
        (self.workspace/'gate-kit').symlink_to(self.canonical, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            NS['validate_context'](self.env,self.canonical)

    def test_guard_and_working_git_path_precede_checkout(self):
        self.assertLess(WORKFLOW.index('name: Guard trusted local agents'),WORKFLOW.index('uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8'))
        self.assertIn("if: inputs.repo == 'agents' && inputs.runner == 'beans-mac'",STEP)
        self.assertIn('/opt/homebrew/bin/python3',STEP)
        self.assertIn("namespace['validate_context'](os.environ)",BOOTSTRAP)
        self.assertLess(BOOTSTRAP.index("namespace['validate_context']"),BOOTSTRAP.index(".open('x')"))
        self.assertIn('/Library/Developer/CommandLineTools/usr/bin\\n/opt/homebrew/bin\\n',BOOTSTRAP)


class TestCanonicalLock(LocalFixture):
    def test_exclusive_nonblocking_persistent_inode_and_release(self):
        with NS['canonical_lock'](self.canonical):
            path = self.canonical/'.git/beanstalk-canonical-tests.lock'
            inode=path.stat().st_ino
            with self.assertRaises(RuntimeError):
                with NS['canonical_lock'](self.canonical):
                    self.fail('concurrent acquisition')
        with NS['canonical_lock'](self.canonical):
            self.assertEqual(path.stat().st_ino,inode)
            self.assertEqual(path.read_bytes(),b'')

    def test_symlink_and_hardlink_lock_are_rejected(self):
        sentinel=self.root/'sentinel'; sentinel.write_text('preserve')
        path=self.canonical/'.git/beanstalk-canonical-tests.lock'
        path.symlink_to(sentinel)
        with self.assertRaises(RuntimeError):
            with NS['canonical_lock'](self.canonical):
                self.fail('symlink lock')
        path.unlink()  # Fixture construction only; wrapper never unlinks a lock.
        os.link(sentinel,path)
        with self.assertRaises(RuntimeError):
            with NS['canonical_lock'](self.canonical):
                self.fail('hardlink lock')
        self.assertEqual(sentinel.read_text(),'preserve')

    def test_failure_releases_lock_without_markers(self):
        with self.assertRaisesRegex(ValueError,'fixture'):
            with NS['canonical_lock'](self.canonical):
                raise ValueError('fixture')
        with NS['canonical_lock'](self.canonical):
            self.assertEqual([p.name for p in (self.canonical/'.git').iterdir()],['beanstalk-canonical-tests.lock'])


class TestLocalExecution(LocalFixture):
    def test_lock_covers_full_checker_and_failure_codes(self):
        for full in ('false','true'):
            for code in (0,7):
                def effect(path,run_name):
                    self.assertEqual(run_name,'__main__')
                    self.assertEqual('--full' in sys.argv,full=='true')
                    self.assertEqual(sys.argv[1:7],['--repo','agents','--root',str(self.canonical),'--markdown']+(['--full'] if full=='true' else []))
                    self.assertEqual(os.environ['PYTHONPATH'],f'{self.canonical}:{self.canonical}/src:{self.canonical}/tests')
                    with self.assertRaises(RuntimeError):
                        with NS['canonical_lock'](self.canonical):
                            self.fail('checker not locked')
                    raise SystemExit(code)
                status,run=self.run_checker(effect,{**self.env,'GATE_FULL':full})
                self.assertEqual(status,code)
                run.assert_called_once()
        self.assertEqual((self.canonical/'source.py').read_text(),'original source\n')

    def test_wrong_head_dirty_hidden_index_or_caller_bytes_deny_before_checker(self):
        cases=('head','dirty','hidden','caller')
        for case in cases:
            with self.subTest(case=case):
                self.heads.clear(); self.dirty.clear(); self.flags.clear()
                (self.workspace/'caller/source.py').write_text('original source\n')
                if case=='head': self.heads[self.canonical]='b'*40
                if case=='dirty': self.dirty[self.canonical]=b' M source.py\n'
                if case=='hidden': self.flags[self.canonical]=b'h source.py\0'
                if case=='caller': (self.workspace/'caller/source.py').write_text('different\n')
                with mock.patch.dict(NS,{'git':self.fake_git}),mock.patch.object(NS['runpy'],'run_path') as run:
                    with self.assertRaises(RuntimeError):
                        NS['run_compliance'](self.env,self.canonical)
                    run.assert_not_called()

    def test_post_run_source_or_head_drift_overrides_checker_success(self):
        for change in ('bytes','head','dirty'):
            with self.subTest(change=change):
                self.heads.clear();self.dirty.clear()
                (self.canonical/'source.py').write_text('original source\n')
                def effect(*args,**kwargs):
                    if change=='bytes': (self.canonical/'source.py').write_text('changed\n')
                    elif change=='head': self.heads[self.canonical]='b'*40
                    else: self.dirty[self.canonical]=b' M source.py\n'
                    raise SystemExit(0)
                with self.assertRaises(RuntimeError): self.run_checker(effect)

    def test_checker_drift_denied(self):
        (self.workspace/'compliance-with-suite-timeout.py').write_text('raise SystemExit(0)\n')
        with self.assertRaisesRegex(RuntimeError,'checker drift'):
            self.run_checker()
        self.assertFalse((self.canonical/'.git/beanstalk-canonical-tests.lock').exists())

    def test_git_is_preinstalled_read_only_and_ignores_ambient_redirects(self):
        with mock.patch.dict(os.environ,{'GIT_DIR':'/wrong','GIT_INDEX_FILE':'/wrong'}),mock.patch.object(subprocess,'check_output',return_value=b'ok') as run:
            self.assertEqual(NS['git'](self.canonical,'rev-parse','HEAD'),b'ok')
        argv=run.call_args.args[0]
        self.assertEqual(argv[0],'/Library/Developer/CommandLineTools/usr/bin/git')
        self.assertIn('--no-optional-locks',argv)
        self.assertIn('core.fsmonitor=false',argv)
        self.assertNotIn('GIT_DIR',run.call_args.kwargs['env'])
        self.assertNotIn('GIT_INDEX_FILE',run.call_args.kwargs['env'])


class TestLocalShellRouting(LocalFixture):
    def test_local_shell_runs_wrapper_and_retains_pipefail(self):
        step=WORKFLOW.split('      - name: Run compliance gate\n',1)[1].split('      - name: Attach summary',1)[0]
        shell=textwrap.dedent(step.split('        run: |\n',1)[1])
        shim=self.workspace/'python3'
        shim.write_text('#!/bin/sh\nprintf "%s\\n" "$*" "$GATE_FULL" > "$CAPTURE"\nexit 9\n')
        shim.chmod(0o700)
        capture=self.workspace/'capture.txt'
        env={**os.environ,**self.env,'GATE_FULL':'true','PATH':str(self.workspace)+os.pathsep+os.environ['PATH'],'CAPTURE':str(capture)}
        result=subprocess.run(['/bin/bash','-e','-c',shell],cwd=self.workspace,env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,9,result.stderr)
        self.assertEqual(capture.read_text().splitlines(),[str(self.runner_temp/'beanstalk-local-compliance.py'),'true'])


if __name__=='__main__':
    unittest.main()
