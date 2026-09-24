"""Contract tests for the report-only workflow security check."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/workflow-security.yml").read_text()
CONTRIBUTING = (ROOT / "CONTRIBUTING.md").read_text()
README = (ROOT / "README.md").read_text()


class TestWorkflowSecurityCheck(unittest.TestCase):
    def test_upstream_tools_and_scanner_input_are_immutable(self):
        self.assertIn(
            "uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5.0.0",
            WORKFLOW,
        )
        self.assertIn(
            "uses: zizmorcore/zizmor-action@6fc4b006235f201fdab3722e17240ab420d580e5 # v0.6.1",
            WORKFLOW,
        )
        self.assertIn('inputs: .github/workflows', WORKFLOW)
        self.assertIn("collect: workflows", WORKFLOW)
        self.assertIn('online-audits: "false"', WORKFLOW)
        self.assertIn('token: ""', WORKFLOW)
        self.assertNotIn("github.token", WORKFLOW)
        self.assertIn('version: "1.28.0"', WORKFLOW)
        self.assertNotIn("min-severity:", WORKFLOW)
        self.assertNotIn("min-confidence:", WORKFLOW)

    def test_scan_is_read_only_report_only_and_not_a_code_scanning_upload(self):
        self.assertIn("permissions:\n  contents: read", WORKFLOW)
        self.assertIn("persist-credentials: false", WORKFLOW)
        self.assertIn("jobs:\n  zizmor:\n    continue-on-error: true", WORKFLOW)
        self.assertIn('advanced-security: "false"', WORKFLOW)
        self.assertIn('fail-on-no-inputs: "true"', WORKFLOW)
        self.assertNotIn("security-events: write", WORKFLOW)
        self.assertNotIn("workflow_call", WORKFLOW)

    def test_documented_scope_severity_policy_and_reproduction_are_public(self):
        for text in (CONTRIBUTING, README):
            self.assertIn("report-only", text.lower())
            self.assertIn("caller repositories", text.lower())
        for heading in ("High", "Medium", "Low, informational, or unknown", "Confidence"):
            self.assertIn(heading, CONTRIBUTING)
        for pin in (
            "08c6903cd8c0fde910a37f88322edcfb5dd907a8",
            "6fc4b006235f201fdab3722e17240ab420d580e5",
            "sha256:8e6b3e4fb74d1aa5d23e83ea369f386c66eced0d1fb944d32cd8b2aac100b00d",
        ):
            self.assertIn(pin, CONTRIBUTING)
        self.assertIn("does not certify caller repositories", CONTRIBUTING)
        self.assertIn('token: ""', CONTRIBUTING)
        self.assertIn("empty `GH_TOKEN`", CONTRIBUTING)
        self.assertIn("receives no GitHub token", README)
        self.assertIn("--no-online-audits", CONTRIBUTING)
        self.assertIn("--no-exit-codes", CONTRIBUTING)
        for match in re.findall(r"uses: ([^@\s]+)@([^\s#]+)", WORKFLOW):
            self.assertRegex(match[1], r"^[0-9a-f]{40}$")


class TestPublicContributionGuide(unittest.TestCase):
    def test_guide_has_exact_setup_test_demo_and_review_steps(self):
        for command in (
            "git clone https://github.com/stevekkall-beansgc/gate-kit.git",
            "python3 -m py_compile bin/compliance.py",
            "python3 scripts/check_stdlib.py bin/",
            "python3 -m unittest discover -s tests -v",
            "python3 examples/synthetic_quickstart.py",
            "git diff --check",
            "git diff --stat",
            "git diff",
            "git status --short",
        ):
            self.assertIn(command, CONTRIBUTING)
        self.assertNotIn("agency/docs", CONTRIBUTING.lower())
        self.assertNotIn("canonical guide", CONTRIBUTING.lower())
        self.assertIn("Python 3.12, the version CI verifies on Ubuntu", CONTRIBUTING)
        self.assertNotIn("Python 3.12 or newer", CONTRIBUTING)


if __name__ == "__main__":
    unittest.main()
