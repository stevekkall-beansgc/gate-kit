"""Real shared-CLI qualification with synthetic source/control repositories.

Requires GATE_SHARED_QA_FIXTURE (or .qa-fixtures/qa-kit). Missing fixtures fail;
this explicit integration suite never substitutes a fake executor or skips.
"""
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
from check_parity import check_parity


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args],
                                   stderr=subprocess.DEVNULL, text=True).strip()


def commit(root):
    git(root, "add", ".")
    changed = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--quiet"]).returncode
    if changed:
        git(root, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic fixture")
    return git(root, "rev-parse", "HEAD")


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestSharedExecution(unittest.TestCase):
    def setUp(self):
        source = Path(os.environ.get("GATE_SHARED_QA_FIXTURE", REPO / ".qa-fixtures/qa-kit"))
        self.assertTrue((source / "bin/validation.py").is_file(), "required QA fixture is missing")
        self.temp = tempfile.TemporaryDirectory(prefix="gate-shared-execution-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.caller, self.qa, self.gate, self.controls = [self.base / name for name in
                                                       ("caller", "qa", "gate", "controls")]
        for root in (self.caller, self.qa, self.gate, self.controls):
            root.mkdir()
            git(root, "init", "-q")
        (self.qa / "bin").mkdir()
        (self.qa / "bin/validation.py").write_bytes((source / "bin/validation.py").read_bytes())
        write_json(self.qa / "manifest.json", {"repos": [{
            "name": "sample", "status": "active", "unit": {"cmd": ["python3", "unit.py"]}}]})
        self.qa_sha = commit(self.qa)
        (self.gate / "bin").mkdir()
        (self.gate / "bin/validation_adapter.py").write_bytes((REPO / "bin/validation_adapter.py").read_bytes())
        (self.gate / "bin/compliance.py").write_bytes((REPO / "bin/compliance.py").read_bytes())
        self.gate_sha = commit(self.gate)
        (self.caller / ".gitignore").write_text("scratch/\n")
        (self.caller / "README.md").write_text("See AGENTS.md\n")
        (self.caller / "AGENTS.md").write_text("## Test commands\npython3 unit.py\n")
        (self.caller / "setup.py").write_text("pass\n")
        (self.caller / "unit.py").write_text(
            "from pathlib import Path\nimport os\nPath('scratch').mkdir(exist_ok=True)\n"
            "Path('scratch/unit-ran').write_text(os.environ['CI'])\n")
        self.contract = {"schema": "qa-kit.validation-contract/v1", "variants": {
            "host": {"os": platform.system().lower(), "arch": platform.machine(),
                     "runtimes": {"python": f"{sys.version_info.major}.{sys.version_info.minor}"}}},
            "tasks": {"setup": {"argv": ["python3", "setup.py"], "cwd": ".", "after": [],
                                "variants": ["host"], "env": {}, "effects": [], "fixtures": [],
                                "timeout_seconds": 5},
                      "unit": {"argv": ["python3", "unit.py"], "cwd": ".", "after": ["setup"],
                               "variants": ["host"], "env": {"CI": {"literal": "true"}},
                               "effects": ["repo-write"], "fixtures": [], "timeout_seconds": 5}},
            "selections": {"ci-required": ["unit@host"], "release-required": ["unit@host"]}}
        self.output = self.base / "validation-result.json"
        self.sync()

    def sync(self):
        contract_hash = write_json(self.caller / "validation.json", self.contract)
        self.head = commit(self.caller)
        registry_hash = write_json(self.controls / "registry.json", {
            "schema": "qa-kit.validation-registry/v1", "repos": {"sample": {
                "contract": "validation.json", "contract_sha256": contract_hash,
                "github_repository": "example/sample", "selections": self.contract["selections"],
                "required_selections": {"ci": "ci-required", "release": "release-required"}}}})
        authorization_hash = write_json(self.controls / "authorization.json", {
            "schema": "qa-kit.validation-authorization/v1", "contexts": ["local", "ci"],
            "variants": list(self.contract["variants"]), "effects": ["repo-write"]})
        self.bundle_hash = write_json(self.controls / "bundle.json", {
            "schema": "qa-kit.validation-bundle/v1", "protocol": "1.0", "qa_commit": self.qa_sha,
            "registry_sha256": registry_hash, "authorization_sha256": authorization_hash,
            "adapters": {"ci": self.gate_sha}, "fixtures": {}})
        self.controls_sha = commit(self.controls)

    def command(self, *, context="local", digest=None, extra=()):
        command = [sys.executable, "-B", str(self.gate / "bin/validation_adapter.py"),
                   "--root", str(self.caller), "--repo", "sample", "--qa-root", str(self.qa),
                   "--controls-root", str(self.controls), "--controls-commit", self.controls_sha,
                   "--registry", "registry.json", "--bundle", "bundle.json",
                   "--expected-bundle", digest or self.bundle_hash,
                   "--authorization", "authorization.json", "--variant", "host",
                   "--expected-head", self.head, "--context", context, "--output", str(self.output),
                   *extra]
        return command

    def run_gate(self, *, context="local", digest=None, extra=(), environment=None):
        result = subprocess.run(self.command(context=context, digest=digest, extra=extra),
                                env={**os.environ, **(environment or {})},
                                capture_output=True, text=True, timeout=45)
        return result.returncode, json.loads(result.stdout.splitlines()[-1])

    def test_shared_cli_pass_and_literal_environment(self):
        code, result = self.run_gate()
        self.assertEqual(code, 0, result)
        self.assertEqual((self.caller / "scratch/unit-ran").read_text(), "true")
        self.assertEqual(result["validation"]["candidate"]["before"]["head"], self.head)
        self.assertTrue(result["validation"]["selection_complete"])
        self.assertFalse(result["github_check_verified"])

    def test_same_host_local_and_ci_use_identical_required_execution(self):
        code, local = self.run_gate()
        self.assertEqual(code, 0, local)
        self.output = self.base / "ci-validation-result.json"
        event = self.base / "event.json"
        write_json(event, {"repository": {"full_name": "example/sample"},
                           "after": self.head, "ref": "refs/heads/main"})
        environment = {"GITHUB_EVENT_PATH": str(event), "RUNNER_ENVIRONMENT": "github-hosted",
                       "GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                       "GATE_REPOSITORY": "example/sample", "GATE_EVENT_REPOSITORY": "example/sample",
                       "GATE_EXPECTED_SHA": self.head, "GATE_EVENT_NAME": "push",
                       "GATE_REF": "refs/heads/main", "GATE_PUSH_AFTER": self.head}
        code, ci = self.run_gate(context="ci", environment=environment)
        self.assertEqual(code, 0, ci)
        compared = check_parity(local, ci, repo="sample", head=self.head, bundle=self.bundle_hash)
        self.assertEqual(compared["parity"], "pass")
        self.assertFalse(compared["github_check_verified"])

    def test_setup_failure_blocks_real_dependent_task(self):
        (self.caller / "setup.py").write_text("raise SystemExit(7)\n")
        self.sync()
        code, result = self.run_gate()
        self.assertEqual(code, 1, result)
        self.assertEqual([(t["task"], t["status"]) for t in result["validation"]["tasks"]],
                         [("setup", "fail"), ("unit", "blocked")])
        self.assertFalse((self.caller / "scratch/unit-ran").exists())

    def test_existing_docs_failure_cannot_be_dropped_by_shared_plan(self):
        (self.caller / "AGENTS.md").write_text("Missing test commands\n")
        self.sync()
        code, result = self.run_gate()
        self.assertEqual(code, 1, result)
        self.assertEqual(result["validation"]["status"], "pass")
        self.assertFalse(result["repos"][0]["checks"][0]["ok"])

    def test_partial_variant_cannot_turn_compliance_green(self):
        self.contract["variants"]["second"] = self.contract["variants"]["host"].copy()
        for task in self.contract["tasks"].values():
            task["variants"].append("second")
        for selection in self.contract["selections"].values():
            selection.append("unit@second")
        self.sync()
        code, result = self.run_gate()
        self.assertEqual(code, 1, result)
        self.assertEqual(result["validation"]["status"], "pass")
        self.assertFalse(result["validation"]["selection_complete"])

    def test_bad_bundle_digest_blocks_before_task(self):
        code, result = self.run_gate(digest="0" * 64)
        self.assertEqual(code, 1, result)
        self.assertFalse((self.caller / "scratch/unit-ran").exists())

    def test_control_source_cannot_hide_unreviewed_code(self):
        git(self.qa, "update-index", "--assume-unchanged", "bin/validation.py")
        (self.qa / "bin/validation.py").write_text("raise SystemExit(0)\n")
        self.assertEqual(git(self.qa, "status", "--porcelain"), "")
        code, result = self.run_gate()
        self.assertEqual(code, 1, result)
        self.assertFalse(self.output.exists())

    def test_existing_result_artifact_is_not_overwritten(self):
        self.output.write_text("prior artifact\n")
        code, result = self.run_gate()
        self.assertEqual(code, 1, result)
        self.assertEqual(self.output.read_text(), "prior artifact\n")

    def test_ci_cannot_reduce_centrally_required_selection(self):
        code, result = self.run_gate(context="ci", extra=("--selection", "release-required"))
        self.assertEqual(code, 1, result)
        self.assertFalse((self.caller / "scratch/unit-ran").exists())

    def test_adapter_cancellation_reaches_executor_and_blocks_dependents(self):
        (self.caller / "setup.py").write_text(
            "from pathlib import Path\nimport os,time\nPath('scratch').mkdir(exist_ok=True)\n"
            "Path('scratch/pid').write_text(str(os.getpid()))\ntime.sleep(20)\n")
        self.contract["tasks"]["setup"]["timeout_seconds"] = 30
        self.sync()
        process = subprocess.Popen(self.command(), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        pid_path = self.caller / "scratch/pid"
        try:
            deadline = time.monotonic() + 10
            while not pid_path.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(pid_path.exists(), "synthetic setup did not start")
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 1, stderr)
            result = json.loads(stdout.splitlines()[-1])
            self.assertEqual(result["validation"]["tasks"][0]["status"], "fail")
            self.assertTrue(result["validation"]["tasks"][0]["cancelled"])
            self.assertEqual(result["validation"]["tasks"][1]["status"], "blocked")
            self.assertFalse((self.caller / "scratch/unit-ran").exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_path.read_text()), 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
