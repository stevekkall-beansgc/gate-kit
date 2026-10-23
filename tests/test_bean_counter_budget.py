"""Bean Counter keeps its manifest and budgets with the reviewed checker pin."""
import hashlib
import re
import unittest
from pathlib import Path
from workflow_checker_pin import before_workflow_adoption

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/compliance.yml').read_text()
OLD_TIMEOUT = "${{ inputs.repo == 'agents' && 270 || 15 }}"
NEW_TIMEOUT = "${{ inputs.repo == 'agents' && 270 || inputs.repo == 'bean-counter' && 50 || 15 }}"
OLD_MANIFEST = "${{ inputs.repo == 'agency' && 'v0.7.0' || 'v0.6.6' }}"
COUNTER_MANIFEST = "${{ inputs.repo == 'agency' && 'v0.7.0' || inputs.repo == 'bean-counter' && 'v0.6.1' || 'v0.6.6' }}"
NEW_MANIFEST = "${{ inputs.repo == 'agency' && 'v0.7.0' || inputs.repo == 'bean-counter' && 'v0.6.1' || (inputs.repo == 'beanlabs' || inputs.repo == 'agents') && 'v0.7.10' || 'v0.6.6' }}"


def selected(expression, repo, runner=None):
    # These closed expressions contain only nonempty strings/positive integers,
    # whose short-circuit truth semantics match GitHub's && / || selection.
    return eval(expression[3:-3].replace('inputs.repo', repr(repo))
                .replace('inputs.runner', repr(runner)).replace('&&', 'and').replace('||', 'or'), {'__builtins__': {}})


class TestBeanCounterBudget(unittest.TestCase):
    def test_only_two_closed_selections_change_the_current_workflow(self):
        self.assertEqual(WORKFLOW.count(NEW_TIMEOUT), 1)
        self.assertEqual(WORKFLOW.count(NEW_MANIFEST), 1)
        original = before_workflow_adoption(WORKFLOW).replace(NEW_TIMEOUT, OLD_TIMEOUT, 1).replace(COUNTER_MANIFEST, OLD_MANIFEST, 1)
        # Exact published v0.7.4/current-main4399826 workflow bytes. Existing
        # fleet defaults, security pins, permissions and command bodies remain.
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         '36c9ae6ba5d61b71b2de697850e9eb9259911934f3a0c3b622595e9b7e736cce')

    def test_outer_allowance_changes_only_for_bean_counter(self):
        expression = re.search(r'^    timeout-minutes: (.+)$', WORKFLOW, re.M).group(1)
        self.assertEqual(expression, NEW_TIMEOUT)
        for repo, expected in [('bean-counter', 50), ('agents', 270), ('agency', 15),
                               ('qa-kit', 15), ('beanfit-app', 15), ('unknown', 15)]:
            with self.subTest(repo=repo):
                self.assertEqual(selected(expression, repo), expected)

    def test_manifest_compatibility_preserves_raw_checker_command_timeouts(self):
        self.assertIn('ref: ' + NEW_MANIFEST, WORKFLOW)
        for repo, expected in [('bean-counter', 'v0.6.1'), ('agency', 'v0.7.0'),
                               ('agents', 'v0.7.10'), ('beanlabs', 'v0.7.10'), ('qa-kit', 'v0.6.6'), ('unknown', 'v0.6.6')]:
            with self.subTest(repo=repo):
                self.assertEqual(selected(NEW_MANIFEST, repo), expected)
        checker = (ROOT / 'tests/fixtures/compliance-v0.7.6.py').read_text().rstrip('\n')
        self.assertEqual(hashlib.sha256(checker.encode()).hexdigest(),
                         '8ff1f344a18206441829791c55fd7fd60176aec170a7445aad93c0cf5e61dd4c')
        self.assertEqual(checker.count('timeout=900'), 1)
        self.assertIn('repository: stevekkall-beansgc/gate-kit\n          ref: v0.7.6', WORKFLOW)
        self.assertIn('python3 gate-kit/bin/compliance.py "${gate_args[@]}"', WORKFLOW)


if __name__ == '__main__':
    unittest.main()
