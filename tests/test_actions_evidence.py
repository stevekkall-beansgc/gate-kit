"""Sanitized artifact assembly never manufactures GitHub check provenance."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("actions_evidence", ROOT / "bin/assemble_evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class TestActionsEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = self.base / "runtime"
        (self.runtime / "bin").mkdir(parents=True)
        for name in ("validation_adapter.py", "check_parity.py"):
            (self.runtime / "bin" / name).write_bytes((ROOT / "bin" / name).read_bytes())
        subprocess.run(["git", "-C", str(self.runtime), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.runtime), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.runtime), "-c", "user.name=Synthetic",
                        "-c", "user.email=synthetic@example.invalid", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "synthetic exact runtime"], check=True)
        runtime_sha = subprocess.check_output(["git", "-C", str(self.runtime), "rev-parse", "HEAD"], text=True).strip()
        self.directory = self.base / "evidence"
        self.directory.mkdir()
        self.variant = "macos-arm64-py312"
        self.policy = {"schema": "gate-kit.validation-workflow-policy/v1", "adapter_commit": runtime_sha,
                       "executor_commit": "a" * 40, "controls_commit": "b" * 40,
                       "repos": {"bean-labs": {"github_repository": "stevekkall-beansgc/legume-labs",
                                               "variant": self.variant, "selection": "ci-required",
                                               "fixtures": {}, "bundle_sha256": "c" * 64,
                                               "registry_sha256": "c" * 64,
                                               "authorization_sha256": "c" * 64,
                                               "contract_sha256": "c" * 64}}}
        self.policy_path = self.base / "policy.json"
        self.event_path = self.base / "event.json"
        self.event = {"repository": {"full_name": "stevekkall-beansgc/legume-labs"},
                      "after": "a" * 40, "ref": "refs/heads/main"}
        self.env = {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_EVENT_PATH": str(self.event_path), "GITHUB_JOB": "compliance",
                    "GITHUB_WORKFLOW_REF": "stevekkall-beansgc/legume-labs/.github/workflows/gate.yml@refs/heads/main",
                    "GITHUB_WORKFLOW_SHA": "a" * 40,
                    "GATE_REPOSITORY": "stevekkall-beansgc/legume-labs",
                    "GATE_EVENT_REPOSITORY": "stevekkall-beansgc/legume-labs",
                    "GATE_EXPECTED_SHA": "a" * 40, "GATE_EVENT_NAME": "push",
                    "GATE_REF": "refs/heads/main", "GATE_PUSH_AFTER": "a" * 40,
                    "RUNNER_ENVIRONMENT": "self-hosted", "RUNNER_NAME": "beans-macbook-legume-labs-validation",
                    "RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64",
                    "GATE_JOB_WORKFLOW_REF": "stevekkall-beansgc/gate-kit/.github/workflows/validation.yml@refs/tags/v0.7.0",
                    "GATE_JOB_WORKFLOW_SHA": "d" * 40,
                    "GATE_JOB_WORKFLOW_REPOSITORY": "stevekkall-beansgc/gate-kit",
                    "GATE_JOB_WORKFLOW_PATH": ".github/workflows/validation.yml",
                    "GATE_JOB_CHECK_RUN_ID": "456"}
        identity = {"head": "a" * 40, "dirty": False, "matches_head": True, "tracked_sha256": "b" * 64}
        result = {"schema": "qa-kit.validation-result/v1", "repo": "bean-labs", "context": "local",
                  "status": "pass", "selection_complete": True,
                  "required": ["unit@" + self.variant], "selected": ["unit@" + self.variant], "remaining_required": [],
                  "candidate": {"before": identity, "after": copy.deepcopy(identity)},
                  "tasks": [{"task": "unit", "variant": self.variant, "status": "pass", "exit_code": 0,
                             "timed_out": False, "cancelled": False}],
                  "github_repository": "stevekkall-beansgc/legume-labs", "selection": "ci-required",
                  "variant": self.variant, "observed": {"os": "darwin", "arch": "arm64", "runtimes": {}},
                  "fixtures": {}, "controls": {"qa": identity, "adapter": {**identity, "head": runtime_sha}}}
        for key in ("contract_sha256", "registry_sha256", "authorization_sha256", "bundle_sha256", "plan_sha256"):
            result[key] = "c" * 64
        controls = {"commit": "b" * 40, "adapter_commit": runtime_sha,
                    "executor_commit": "a" * 40, "bundle_sha256": "c" * 64}
        self.local = {"gate": "compliance", "mode": "enrolled", "failures": 0,
                      "trusted_controls": controls, "validation": result}
        self.ci = copy.deepcopy(self.local)
        self.ci["validation"]["context"] = "ci"
        adapter = runpy.run_path(str(self.runtime / "bin/validation_adapter.py"))
        self.ci["execution_context"] = adapter["validate_ci_context"](
            self.env, self.event, "stevekkall-beansgc/legume-labs", "a" * 40, self.variant)
        self.parity = runpy.run_path(str(self.runtime / "bin/check_parity.py"))["check_parity"](
            self.local, self.ci, repo="bean-labs", head="a" * 40, bundle="c" * 64)

    def assemble(self):
        for path, value in ((self.policy_path, self.policy), (self.event_path, self.event),
                            (self.directory / "local-envelope.json", self.local),
                            (self.directory / "ci-envelope.json", self.ci),
                            (self.directory / "parity.json", self.parity)):
            path.write_text(json.dumps(value))
        return evidence.assemble(self.directory, self.policy_path, "bean-labs", self.runtime, self.env)

    def test_exact_sanitized_receipts_are_hashed_but_not_a_verified_check(self):
        result = self.assemble()
        self.assertEqual(result["schema"], "gate-kit.actions-validation-provenance/v1")
        self.assertFalse(result["github_check_verified"])
        self.assertEqual(set(path.name for path in self.directory.iterdir()),
                         {*evidence.RECEIPTS, "gate-provenance.json"})
        for name, digest in result["receipt_sha256"].items():
            self.assertEqual(digest, hashlib.sha256((self.directory / name).read_bytes()).hexdigest())

    def test_legacy_caller_or_missing_reusable_identity_is_refused(self):
        for key, value in (("GITHUB_WORKFLOW_REF", "stevekkall-beansgc/legume-labs/.github/workflows/gate-linux.yml@refs/heads/main"),
                           ("GATE_JOB_WORKFLOW_SHA", ""), ("GATE_JOB_CHECK_RUN_ID", "")):
            with self.subTest(key=key):
                old = self.env[key]
                self.env[key] = value
                with self.assertRaises(ValueError):
                    self.assemble()
                self.env[key] = old

    def test_fixed_bundle_control_or_contract_mismatch_is_refused(self):
        for key, value in (("bundle_sha256", "d" * 64), ("contract_sha256", "d" * 64)):
            with self.subTest(key=key):
                row = self.policy["repos"]["bean-labs"]
                old = row[key]
                row[key] = value
                with self.assertRaises(ValueError):
                    self.assemble()
                row[key] = old

    def test_partial_evidence_or_stale_event_is_refused(self):
        self.ci["validation"]["selection_complete"] = False
        with self.assertRaises(ValueError):
            self.assemble()
        self.ci["validation"]["selection_complete"] = True
        self.event["after"] = "d" * 40
        with self.assertRaises(ValueError):
            self.assemble()

    def test_hidden_runtime_replacement_is_rejected_before_loading_it(self):
        subprocess.run(["git", "-C", str(self.runtime), "update-index", "--assume-unchanged", "bin/validation_adapter.py"], check=True)
        marker = self.base / "unreviewed-code-ran"
        (self.runtime / "bin/validation_adapter.py").write_text(
            "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
        with self.assertRaises(ValueError):
            self.assemble()
        self.assertFalse(marker.exists())

    def test_existing_provenance_is_never_overwritten(self):
        self.assemble()
        with self.assertRaises(FileExistsError):
            self.assemble()


class TestArtifactUploaderReceipt(unittest.TestCase):
    def test_marker_binds_upload_id_digest_and_attempt(self):
        env = {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2", "GATE_ARTIFACT_ID": "456",
               "GATE_ARTIFACT_DIGEST": "a" * 64}
        self.assertEqual(evidence.artifact_receipt(env), {
            "artifact_id": "456", "artifact_digest": "sha256:" + "a" * 64,
            "artifact_name": "gate-validation-123-2", "run_id": "123", "run_attempt": "2"})
        for key, value in (("GATE_ARTIFACT_ID", ""), ("GATE_ARTIFACT_DIGEST", "bad"), ("GITHUB_RUN_ATTEMPT", "0")):
            with self.assertRaises(ValueError):
                evidence.artifact_receipt({**env, key: value})
