"""Runtime and manifest repairs select only their explicitly owned cohorts."""
from pathlib import Path
import re
import unittest

from test_bean_counter_budget import selected

WORKFLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/compliance.yml").read_text()


class TestSetupCohorts(unittest.TestCase):
    def test_repaired_manifest_only_for_core_and_agents(self):
        checkout = WORKFLOW.split("repository: stevekkall-beansgc/qa-kit", 1)[1].split("path: qa-kit", 1)[0]
        expression = re.search(r"ref: (\$\{\{ .+ \}\})", checkout).group(1)
        for repo, version in (("beanlabs", "v0.7.10"), ("agents", "v0.7.10"),
                              ("agency", "v0.7.0"), ("bean-counter", "v0.6.1"),
                              ("qa-kit", "v0.6.6"), ("beanfit-app", "v0.6.6"),
                              ("unknown", "v0.6.6")):
            with self.subTest(repo=repo):
                self.assertEqual(selected(expression, repo), version)

    def test_python_314_only_for_core_hosted_setup(self):
        step = WORKFLOW.split("uses: actions/setup-python@", 1)[1].split("      - name:", 1)[0]
        self.assertIn("if: inputs.runner != 'beans-mac'", step)
        expression = re.search(r"python-version: (\$\{\{ .+ \}\})", step).group(1)
        for repo, version in (("beanlabs", "3.14"), ("qa-kit", "3.12"), ("gate-kit", "3.12"),
                              ("agents", "3.13"), ("agency", "3.13"),
                              ("bean-counter", "3.13"), ("unknown", "3.13")):
            with self.subTest(repo=repo):
                self.assertEqual(selected(expression, repo), version)

    def test_node22_adds_only_core_to_existing_cohort(self):
        step = WORKFLOW.split("      - name: Prepare JavaScript test runtime\n", 1)[1].split("      - name:", 1)[0]
        self.assertIn('node-version: "22"', step)
        expression = re.search(r"if: (\$\{\{ .+ \}\})", step).group(1)
        for runner in ("ubuntu-latest", "beans-mac"):
            for repo in ("beanlabs", "agency", "beanfit-app", "bean-counter", "agents", "qa-kit", "unknown"):
                with self.subTest(repo=repo, runner=runner):
                    self.assertEqual(selected(expression, repo, runner),
                                     repo in {"agency", "beanfit-app", "bean-counter"}
                                     or (repo == "beanlabs" and runner != "beans-mac"))


if __name__ == "__main__":
    unittest.main()
