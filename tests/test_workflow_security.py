"""Contract tests for the report-only workflow security check."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTERNAL_WORKFLOW = "stevekkall-beansgc/gate-kit/.github/workflows/compliance.yml"
WORKFLOW = (ROOT / ".github/workflows/workflow-security.yml").read_text()
COMPLIANCE = (ROOT / ".github/workflows/compliance.yml").read_text()
TEST = (ROOT / ".github/workflows/test.yml").read_text()
GATE = (ROOT / ".github/workflows/gate.yml").read_text()
ZIZMOR = (ROOT / "zizmor.yml").read_text()
CONTRIBUTING = (ROOT / "CONTRIBUTING.md").read_text()
README = (ROOT / "README.md").read_text()


class TestWorkflowSecurityCheck(unittest.TestCase):
    def test_workflow_uses_pinned_offline_container_without_action_or_token(self):
        self.assertIn(
            "uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5.0.0",
            WORKFLOW,
        )
        self.assertNotIn("zizmorcore/zizmor-action", WORKFLOW)
        self.assertIn("run: |", WORKFLOW)
        self.assertIn("docker run --rm", WORKFLOW)
        self.assertIn("--network none", WORKFLOW)
        self.assertIn('--volume "$GITHUB_WORKSPACE:/workspace:ro"', WORKFLOW)
        self.assertIn("--workdir /workspace", WORKFLOW)
        self.assertIn(
            "ghcr.io/zizmorcore/zizmor:1.28.0@sha256:8e6b3e4fb74d1aa5d23e83ea369f386c66eced0d1fb944d32cd8b2aac100b00d",
            WORKFLOW,
        )
        for flag in (
            "--persona=regular",
            "--no-online-audits",
            "--no-exit-codes",
            "--color=never",
        ):
            self.assertIn(flag, WORKFLOW)
        self.assertIn(".github/workflows", WORKFLOW)
        self.assertNotIn("token", WORKFLOW.lower())
        self.assertNotIn("secret", WORKFLOW.lower())
        self.assertNotIn("--gh-token", WORKFLOW)
        self.assertNotIn("|| true", WORKFLOW)

    def test_scan_is_read_only_report_only_and_scanner_errors_remain_visible(self):
        self.assertIn("permissions:\n  contents: read", WORKFLOW)
        self.assertIn("persist-credentials: false", WORKFLOW)
        self.assertIn("jobs:\n  zizmor:\n    continue-on-error: true", WORKFLOW)
        self.assertNotIn("security-events: write", WORKFLOW)
        self.assertNotIn("advanced-security", WORKFLOW)
        self.assertNotIn("workflow_call", WORKFLOW)
        self.assertNotIn("|| true", WORKFLOW)

    def test_third_party_actions_use_sha_pins_and_internal_caller_uses_annotated_tag(self):
        checkout = "actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8"
        self.assertEqual(COMPLIANCE.count(checkout), 4)
        self.assertEqual(TEST.count(checkout), 1)
        self.assertIn(
            "actions/setup-python@e797f83bcb11b83ae66e0230d6156d7c80228e7c",
            COMPLIANCE,
        )
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            TEST,
        )
        self.assertEqual(GATE.count(f"uses: {INTERNAL_WORKFLOW}@v0.4.11"), 1)
        for workflow in (COMPLIANCE, TEST, WORKFLOW):
            for _, ref in re.findall(r"uses: ([^@\s]+)@([^\s#]+)", workflow):
                self.assertRegex(ref, r"^[0-9a-f]{40}$")
        for action, ref in re.findall(r"uses: ([^@\s]+)@([^\s#]+)", GATE):
            if action == INTERNAL_WORKFLOW:
                self.assertEqual(ref, "v0.4.11")
            else:
                self.assertRegex(ref, r"^[0-9a-f]{40}$")

    def test_zizmor_allows_only_the_exact_internal_workflow_ref_pin(self):
        self.assertEqual(
            ZIZMOR,
            "rules:\n"
            "  unpinned-uses:\n"
            "    config:\n"
            "      policies:\n"
            f'        "{INTERNAL_WORKFLOW}": ref-pin\n'
            '        "*": hash-pin\n',
        )

    def test_checkouts_do_not_persist_credentials_and_callers_are_read_only(self):
        for workflow, count in ((COMPLIANCE, 4), (TEST, 1), (WORKFLOW, 1)):
            self.assertEqual(workflow.count("persist-credentials: false"), count)
            self.assertEqual(workflow.count("uses: actions/checkout@"), count)
        for workflow in (TEST, GATE):
            self.assertIn("permissions:\n  contents: read", workflow.split("jobs:", 1)[0])

    def test_documented_scope_severity_policy_and_reproduction_are_public(self):
        for text in (CONTRIBUTING, README):
            self.assertIn("report-only", text.lower())
            self.assertIn("caller repositories", text.lower())
            self.assertIn("pinned", text.lower())
            self.assertIn("container", text.lower())
            self.assertIn("no GitHub token or secret", text)
        for heading in ("High", "Medium", "Low, informational, or unknown", "Confidence"):
            self.assertIn(heading, CONTRIBUTING)
        self.assertIn(
            "08c6903cd8c0fde910a37f88322edcfb5dd907a8",
            CONTRIBUTING,
        )
        for text in (CONTRIBUTING, README):
            self.assertIn(
                "sha256:8e6b3e4fb74d1aa5d23e83ea369f386c66eced0d1fb944d32cd8b2aac100b00d",
                text,
            )
        self.assertIn("does not certify caller repositories", CONTRIBUTING)
        self.assertIn("--network none", CONTRIBUTING)
        self.assertIn('--volume "$PWD:/workspace:ro"', CONTRIBUTING)
        self.assertIn("--no-online-audits", CONTRIBUTING)
        self.assertIn("--no-exit-codes", CONTRIBUTING)
        self.assertNotIn("zizmorcore/zizmor-action", CONTRIBUTING)
        self.assertNotIn("6fc4b006235f201fdab3722e17240ab420d580e5", CONTRIBUTING)
        self.assertNotIn('token: ""', CONTRIBUTING)
        self.assertNotIn("GH_TOKEN", CONTRIBUTING)
        self.assertIn("passes no GitHub token or secret", README)
        self.assertIn("`zizmor.yml` applies `hash-pin` to `*`", CONTRIBUTING)
        self.assertIn(
            "permits `ref-pin` only for the exact reusable-workflow identity",
            CONTRIBUTING,
        )
        for text in (CONTRIBUTING, README):
            self.assertIn(INTERNAL_WORKFLOW, text)
            self.assertIn("annotated tag is never moved", text)
            self.assertIn("release gate proves the referenced workflow SHA", text)
            self.assertIn("third-party actions", text.lower())
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
