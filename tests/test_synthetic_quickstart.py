"""Regression coverage for the synthetic CLI quickstart (examples/).

Exercises the real bin/compliance.py through a self-contained, stdlib-only
synthetic repo + qa-kit manifest. No BeanLabs workspace, private repos,
credentials, or network touched.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
import synthetic_quickstart as quick  # noqa: E402

NAME = "synthetic"


class QuickstartFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "synthetic"
        self.repo = self.base / "repo"
        self.qa = self.base / "qa-kit"

    def write_realities(self, broken=False, broken_infra=False):
        quick.build_synthetic_repo(self.repo, broken=broken)
        if not broken_infra:
            quick.write_manifest(self.qa, self.repo, name=NAME)

    def gate_run(self, *extra):
        proc = quick.run_gate(ROOT / "bin" / "compliance.py", self.qa,
                              self.repo, *extra, name=NAME)
        return proc.returncode, quick.last_verdict(proc.stdout)


class TestSyntheticGateRegression(QuickstartFixture):
    def test_healthy_repo_emits_green_json_verdict(self):
        self.write_realities()
        code, verdict = self.gate_run()
        self.assertEqual(code, 0)
        self.assertEqual(verdict["gate"], "compliance")
        self.assertEqual(verdict["failures"], 0)
        self.assertEqual(verdict["coverage"]["selected"], 1)
        self.assertEqual(verdict["repos"][0]["repo"], NAME)
        self.assertEqual(verdict["repos"][0]["verdict"], "PASS")

    def test_broken_docs_fail_closed_with_fail_verdict(self):
        self.write_realities(broken=True)
        code, verdict = self.gate_run()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["failures"], 1)
        self.assertEqual(verdict["repos"][0]["verdict"], "FAIL")
        docs = [c for c in verdict["repos"][0]["checks"] if c["name"] == "docs"][0]
        self.assertFalse(docs["ok"])
        self.assertIn("does not state manifest unit cmd",
                      docs["detail"] or docs.get("detail", ""))

    def test_missing_manifest_fails_closed_on_infrastructure(self):
        self.write_realities(broken_infra=True)
        code, verdict = self.gate_run()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["failures"], 1)
        self.assertEqual(verdict["repos"], [])
        self.assertIn("infrastructure", verdict)
        self.assertTrue(any("manifest" in str(line)
                            for line in verdict["infrastructure"]))

    def test_quickstart_program_run_stays_clean_start_to_finish(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "examples" / "synthetic_quickstart.py")],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("scenario 1", result.stdout)
        self.assertIn("scenario 2", result.stdout)
        self.assertIn("scenario 3", result.stdout)
        self.assertIn("summary", result.stdout)


if __name__ == "__main__":
    unittest.main()