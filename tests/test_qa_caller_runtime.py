"""Caller-scoped proposal preserves existing checks, pins, events and other runtimes."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/compliance.yml').read_text()


class QaCallerRuntime(unittest.TestCase):
    def test_runtime_selection_is_qa_only_and_pins_stay_immutable(self):
        self.assertIn("python-version: ${{ inputs.repo == 'qa-kit' && '3.12' || '3.13' }}", WORKFLOW)
        local = WORKFLOW.split('      - name: Select QA Kit caller Python 3.12')[1].split('      - name: Configure')[0]
        self.assertIn("if: inputs.repo == 'qa-kit' && inputs.runner == 'beans-mac'", local)
        self.assertIn('test -x "$qa_python"', local)
        self.assertIn('sys.version_info[:2] != (3, 12)', local)
        self.assertNotIn('setup-python', local)
        self.assertIn('ref: v0.4.4', WORKFLOW)
        self.assertIn("'v0.7.0' || inputs.repo == 'bean-counter' && 'v0.6.1' || 'v0.6.6'", WORKFLOW)
        self.assertIn('ref: v0.4.0', WORKFLOW)
        self.assertIn('  compliance:\n', WORKFLOW)
        self.assertIn('python3 gate-kit/bin/compliance.py "${gate_args[@]}" | tee gate-report.md', WORKFLOW)

    def test_summary_validation_survives_optimization_without_disclosing_raw_values(self):
        step = WORKFLOW.split('      - name: Retain bounded QA Kit caller provenance')[1]
        script = step.split("python3 - <<'PY'\n", 1)[1].rsplit('          PY', 1)[0]
        script = '\n'.join(line[10:] for line in script.splitlines())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Supply only synthetic Git identities; no product checkout or network.
            for name in ('caller', 'gate-kit', 'qa-kit'):
                (root / name).mkdir()
                subprocess.run(['git', 'init', '-q', str(root / name)], check=True)
                subprocess.run(['git', '-C', str(root / name), '-c', 'user.name=Synthetic',
                                '-c', 'user.email=synthetic@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture'], check=True)
            summary = root / 'summary'
            r = subprocess.run([sys.executable, '-c', script], cwd=root,
                               env={**os.environ, 'RUNNER_TEMP': temp, 'GITHUB_STEP_SUMMARY': str(summary)},
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('"execution": "unavailable"', summary.read_text())
            self.assertNotIn(temp, summary.read_text())
            self.assertNotIn('stdout', summary.read_text())
            (root / 'caller/bin').mkdir()
            entrypoint = b'# synthetic entrypoint\n'
            (root / 'caller/bin/qa_selfcheck.sh').write_bytes(entrypoint)
            head = subprocess.check_output(['git', '-C', str(root / 'caller'), 'rev-parse', 'HEAD'], text=True).strip()
            report = {'schema': 'qa-kit.selfcheck-provenance/v1', 'candidate': head,
                      'candidate_source': {'head': head, 'dirty': False, 'matches_head': True, 'tracked_sha256': 'b' * 64},
                      'entrypoint': 'bash bin/qa_selfcheck.sh',
                      'entrypoint_sha256': hashlib.sha256(entrypoint).hexdigest(),
                      'python_version': [3, 12, 14], 'python_binary_sha256': 'a' * 64,
                      'exit_code': 0, 'checks': dict.fromkeys(['runtime', 'docs', 'standards', 'unit', 'stdlib'], 'pass')}
            for mutation, expected in [({}, 0), ({'python_version': [3, 12, 'private']}, 1),
                                       ({'candidate': 'f' * 40}, 1), ({'checks': {'unit': 'private'}}, 1),
                                       ({'checks': {**report['checks'], 'unit': 'fail'}}, 1),
                                       ({'exit_code': 1, 'checks': {**report['checks'], 'unit': 'fail', 'stdlib': 'blocked'}}, 0)]:
                (root / 'qa-selfcheck-provenance.json').write_text(json.dumps({**report, **mutation}))
                summary.write_text('')
                r = subprocess.run([sys.executable, '-c', script], cwd=root,
                                   env={**os.environ, 'RUNNER_TEMP': temp, 'GITHUB_STEP_SUMMARY': str(summary), 'PYTHONOPTIMIZE': '1'},
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, expected, r.stderr)
                self.assertNotIn('private', summary.read_text())
                self.assertIn('"execution": "recorded"' if expected == 0 else '"execution": "unavailable"', summary.read_text())



if __name__ == '__main__': unittest.main()
