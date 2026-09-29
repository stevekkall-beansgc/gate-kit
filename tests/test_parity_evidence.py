"""Same-host comparison cannot substitute another source/runtime/coverage."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from check_parity import check_parity


class TestParityEvidence(unittest.TestCase):
    def setUp(self):
        identity = {"head": "a" * 40, "dirty": False, "tracked_sha256": "b" * 64,
                    "matches_head": True}
        result = {"schema": "qa-kit.validation-result/v1", "repo": "sample", "context": "local",
                  "status": "pass", "selection_complete": True, "required": ["unit@host"],
                  "selected": ["unit@host"], "remaining_required": [],
                  "candidate": {"before": identity, "after": identity.copy()},
                  "tasks": [{"task": "unit", "variant": "host", "status": "pass",
                             "exit_code": 0, "timed_out": False}],
                  "github_repository": "example/sample", "selection": "ci-required", "variant": "host",
                  "observed": {"os": "linux", "runtimes": {"python": "3.12"}}, "fixtures": {},
                  "controls": {"qa": identity.copy()}}
        for key in ("contract_sha256", "registry_sha256", "authorization_sha256",
                    "bundle_sha256", "plan_sha256"):
            result[key] = "c" * 64
        self.local = {"gate": "compliance", "mode": "enrolled", "failures": 0,
                      "trusted_controls": {"bundle_sha256": "c" * 64, "commit": "a" * 40,
                                           "adapter_commit": "a" * 40, "executor_commit": "a" * 40},
                      "validation": result}
        self.ci = copy.deepcopy(self.local)
        self.ci["validation"]["context"] = "ci"

    def check(self):
        return check_parity(self.local, self.ci, repo="sample", head="a" * 40, bundle="c" * 64)

    def test_matching_execution_is_not_a_verified_github_check(self):
        self.assertEqual(self.check()["parity"], "pass")
        self.assertFalse(self.check()["github_check_verified"])

    def test_isolated_cli_compares_real_serialized_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            local, ci = [Path(directory) / name for name in ("local.json", "ci.json")]
            local.write_text(json.dumps(self.local))
            ci.write_text(json.dumps(self.ci))
            result = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve().parents[1] / "bin/check_parity.py"),
                                     "--local", str(local), "--ci", str(ci), "--repo", "sample",
                                     "--head", "a" * 40, "--bundle", "c" * 64], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)["github_check_verified"])

    def test_wrong_candidate_is_rejected(self):
        self.ci["validation"]["candidate"]["before"]["head"] = "d" * 40
        with self.assertRaises(ValueError):
            self.check()

    def test_os_runtime_or_plan_difference_is_not_equivalence(self):
        for key, value in (("observed", {"os": "darwin"}), ("plan_sha256", "d" * 64),
                           ("variant", "other"), ("fixtures", {"unexpected": {}})):
            with self.subTest(key=key):
                original = self.ci["validation"][key]
                self.ci["validation"][key] = value
                with self.assertRaises(ValueError):
                    self.check()
                self.ci["validation"][key] = original

    def test_partial_or_failed_check_is_rejected(self):
        self.ci["validation"]["selection_complete"] = False
        with self.assertRaises(ValueError):
            self.check()
        self.ci["validation"]["selection_complete"] = True
        self.ci["failures"] = 1
        with self.assertRaises(ValueError):
            self.check()

    def test_timeout_or_cancelled_task_is_not_a_pass(self):
        for key in ("timed_out", "cancelled"):
            with self.subTest(key=key):
                self.ci["validation"]["tasks"][0][key] = True
                with self.assertRaises(ValueError):
                    self.check()
                self.ci["validation"]["tasks"][0][key] = False

    def test_missing_or_unbound_executor_source_cannot_compare_green(self):
        for value in ({}, {"qa": {"head": "d" * 40}}, None):
            with self.subTest(value=value):
                self.local["validation"]["controls"] = value
                self.ci["validation"]["controls"] = value
                with self.assertRaises(ValueError):
                    self.check()


if __name__ == "__main__":
    unittest.main()
