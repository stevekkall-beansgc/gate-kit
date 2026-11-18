"""The Savvy cohort changes one manifest pin and preserves every prior profile."""
import hashlib,re,unittest
from pathlib import Path
from savvy_profile_delta import ADDITION,before_savvy
ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=(ROOT/'.github/workflows/compliance.yml').read_text()

class SavvyProfileTests(unittest.TestCase):
    def test_exact_delta_preserves_published_workflow(self):
        self.assertEqual(1,WORKFLOW.count(ADDITION))
        self.assertEqual('7143cf2652b7e74e10b470ccd5438ff4caf2e486ddeb6e4631619685894517fa',hashlib.sha256(before_savvy(WORKFLOW).encode()).hexdigest())

    def test_manifest_selection_keeps_prior_cohorts_and_unknown_default(self):
        expression=re.search(r"ref: (\$\{\{ inputs.repo == 'savvy-proto'.+? \}\})",WORKFLOW).group(1)
        def selected(repo):
            return eval(expression[3:-3].replace('inputs.repo',repr(repo)).replace('&&','and').replace('||','or'),{'__builtins__':{}})
        for repo,pin in [('savvy-proto','v0.9.0'),('bean-fleet','v0.8.0'),('agency','v0.7.0'),('bean-counter','v0.6.1'),('beanlabs','v0.7.10'),('agents','v0.7.10'),('qa-kit','v0.6.6'),('unknown','v0.6.6')]:
            with self.subTest(repo=repo):self.assertEqual(pin,selected(repo))
