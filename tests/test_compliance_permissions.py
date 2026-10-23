"""Reusable compliance token ceilings preserve the existing workflow contract."""

import hashlib
import unittest
from pathlib import Path
from workflow_checker_pin import before_workflow_adoption


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

    def test_only_permissions_and_the_qa_caller_profile_change_the_frozen_workflow(self):
        # Undo only the separately proven checker and Bean Counter changes.
        original = before_workflow_adoption(WORKFLOW).replace(" || inputs.repo == 'bean-counter' && 50", "", 1)
        original = original.replace(" || inputs.repo == 'bean-counter' && 'v0.6.1'", "", 1)
        original = original.replace("\npermissions:\n  contents: read\n", "", 1)
        original = original.replace("    permissions:\n      contents: read\n", "", 1)
        # Remove only the separately tested QA caller additions before comparing
        # the historical workflow. Other callers, pins, identities and guards
        # must still match the exact pre-permissions baseline.
        start = original.index('      - name: Select QA Kit caller Python 3.12')
        end = original.index('      - name: Prepare JavaScript test runtime', start)
        original = original[:start] + original[end:]
        original = original.split('      - name: Retain bounded QA Kit caller provenance', 1)[0]
        original = original.replace("python-version: ${{ inputs.repo == 'qa-kit' && '3.12' || '3.13' }}", 'python-version: "3.13"', 1)
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         "06ea36df57132a0b5eb6271f02ebe3db2f33592e9089470d849297568a5903ee")


if __name__ == "__main__":
    unittest.main()
