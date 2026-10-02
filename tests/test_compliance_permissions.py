"""Reusable compliance token ceilings preserve the existing workflow contract."""

import hashlib
import unittest
from pathlib import Path


WORKFLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/compliance.yml").read_text()


class TestCompliancePermissions(unittest.TestCase):
    def test_workflow_has_only_explicit_contents_read(self):
        header = WORKFLOW.split("\njobs:\n", 1)[0]
        self.assertIn("\npermissions:\n", header)
        self.assertEqual(header.split("\npermissions:\n", 1)[1], "  contents: read\n")

    def test_compliance_job_has_only_explicit_contents_read(self):
        job = WORKFLOW.split("\n  compliance:\n", 1)[1]
        self.assertIn("    permissions:\n", job)
        self.assertEqual(job.split("    permissions:\n", 1)[1].split("    runs-on:", 1)[0], "      contents: read\n")
        self.assertEqual(WORKFLOW.count("permissions:"), 2)

    def test_permissions_are_the_only_workflow_change(self):
        original = WORKFLOW.replace("\npermissions:\n  contents: read\n", "", 1)
        original = original.replace("    permissions:\n      contents: read\n", "", 1)
        # Freeze every caller/runner/fixture command and the workflow/job identity.
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         "06ea36df57132a0b5eb6271f02ebe3db2f33592e9089470d849297568a5903ee")


if __name__ == "__main__":
    unittest.main()
