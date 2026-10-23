"""Gate's self-caller must use its canonical Python 3.12 test runtime."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

from test_bean_counter_budget import selected
from workflow_checker_pin import before_gate_runtime

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/compliance.yml').read_text()
LOCAL = WORKFLOW.split('      - name: Select ', 1)[1].split('      - name: Configure', 1)[0]


class GateCallerRuntime(unittest.TestCase):
    def test_only_three_runtime_selections_change_released_workflow(self):
        self.assertEqual(hashlib.sha256(before_gate_runtime(WORKFLOW).encode()).hexdigest(),
                         '55e3a62e73b7b6482a425887efc979d7b33346d217befb2bcbda917863928041')

    def test_hosted_runtime_matches_canonical_gate_tests(self):
        step = WORKFLOW.split('uses: actions/setup-python@', 1)[1].split('      - name:', 1)[0]
        self.assertIn("if: inputs.runner != 'beans-mac'", step)
        expression = re.search(r'python-version: (\$\{\{ .+ \}\})', step).group(1)
        for repo, expected in [('gate-kit', '3.12'), ('qa-kit', '3.12'),
                               ('beanlabs', '3.14'), ('agents', '3.13'),
                               ('agency', '3.13'), ('bean-counter', '3.13'),
                               ('unknown', '3.13')]:
            with self.subTest(repo=repo):
                self.assertEqual(selected(expression, repo), expected)
        self.assertIn('sys.version_info[:2] != (3, 12)', (ROOT / 'Taskfile.yml').read_text())

    def test_local_selection_adds_only_gate_to_existing_qa_cohort(self):
        expression = re.search(r'if: (.+)', LOCAL).group(1)
        for repo in ('gate-kit', 'qa-kit', 'beanlabs', 'agents', 'agency', 'bean-counter', 'unknown'):
            for runner in ('beans-mac', 'ubuntu-latest', 'macos-15'):
                with self.subTest(repo=repo, runner=runner):
                    self.assertEqual(selected('${{ ' + expression + ' }}', repo, runner),
                                     repo in {'gate-kit', 'qa-kit'} and runner == 'beans-mac')
        self.assertNotIn('setup-python', LOCAL)

    def test_local_step_checks_installed_runtime_before_exporting_path(self):
        script = textwrap.dedent(LOCAL.split('run: |\n', 1)[1])
        installed = '/opt/homebrew/opt/python@3.12/libexec/bin'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            python = root / 'python3'
            path_file = root / 'github-path'
            env = {**os.environ, 'GITHUB_PATH': str(path_file)}
            script = script.replace(installed, str(root))
            missing = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertFalse(path_file.exists())
            # A rejected version probe cannot put the interpreter on PATH.
            python.write_text('#!/bin/sh\nexit 1\n')
            python.chmod(0o755)
            wrong = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertFalse(path_file.exists())
            python.unlink()
            python.symlink_to(sys.executable)
            valid = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(path_file.read_text(), str(root) + '\n')


if __name__ == '__main__':
    unittest.main()
