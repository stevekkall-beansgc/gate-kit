"""Wrong workflow authority and hidden source edits fail before task launch."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
workflow = runpy.run_path(str(ROOT / "bin/run_workflow_validation.py"))


class TestWorkflowPreflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source, self.workspace, self.temporary = [self.base / name for name in ("source", "workspace", "temp")]
        for path in (self.source, self.workspace, self.temporary):
            path.mkdir()
        (self.source / "bin").mkdir()
        for name in ("validation_adapter.py", "assemble_evidence.py", "run_workflow_validation.py"):
            (self.source / "bin" / name).write_bytes((ROOT / "bin" / name).read_bytes())
        (self.source / ".github").mkdir()
        policy = {"schema": "gate-kit.validation-workflow-policy/v1", "controls_commit": "b" * 40,
                  "adapter_commit": workflow["RUNTIME_COMMIT"], "executor_commit": workflow["EXECUTOR_COMMIT"],
                  "repos": {"bean-labs": {"github_repository": "stevekkall-beansgc/legume-labs",
                                           "variant": "macos-arm64-py312", "selection": "ci-required", "fixtures": {},
                                           **{key: "c" * 64 for key in ("bundle_sha256", "registry_sha256",
                                                                       "authorization_sha256", "contract_sha256")}}}}
        (self.source / ".github/validation-policy.json").write_text(json.dumps(policy))
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic workflow source")
        head = self.git("rev-parse", "HEAD")
        self.env = {"GATE_REPO": "bean-labs", "GATE_EXPECTED_SHA": "a" * 40,
                    "GITHUB_WORKFLOW_REF": "stevekkall-beansgc/legume-labs/.github/workflows/gate.yml@refs/heads/main",
                    "GITHUB_WORKFLOW_SHA": "a" * 40, "GITHUB_JOB": "compliance",
                    "GATE_JOB_WORKFLOW_REF": "stevekkall-beansgc/gate-kit/.github/workflows/validation.yml@refs/tags/v0.7.0",
                    "GATE_JOB_WORKFLOW_SHA": head, "GATE_JOB_WORKFLOW_REPOSITORY": "stevekkall-beansgc/gate-kit",
                    "GATE_JOB_WORKFLOW_PATH": ".github/workflows/validation.yml", "GATE_JOB_CHECK_RUN_ID": "456"}

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args], text=True).strip()

    def run_pair(self):
        return workflow["run_pair"](self.workspace, self.temporary, self.env, self.source)

    def test_wrong_caller_job_or_source_is_refused_before_runtime_or_task_launch(self):
        # Runtime/executor/candidate roots intentionally do not exist: identity
        # must fail first, before any subsequent source load or task can occur.
        for key, value in (("GITHUB_WORKFLOW_REF", "stevekkall-beansgc/legume-labs/.github/workflows/gate-linux.yml@refs/heads/main"),
                           ("GITHUB_JOB", "other"), ("GITHUB_WORKFLOW_SHA", "d" * 40),
                           ("GATE_JOB_WORKFLOW_REF", "stevekkall-beansgc/gate-kit/.github/workflows/validation.yml@main"),
                           ("GATE_JOB_CHECK_RUN_ID", "")):
            with self.subTest(key=key):
                old = self.env[key]
                self.env[key] = value
                with self.assertRaisesRegex(ValueError, "workflow identity metadata"):
                    self.run_pair()
                self.env[key] = old
                self.assertEqual(list(self.temporary.iterdir()), [])

    def test_hidden_evidence_helper_is_refused_before_loading_its_code(self):
        marker = self.base / "untrusted-ran"
        self.git("update-index", "--assume-unchanged", "bin/assemble_evidence.py")
        (self.source / "bin/assemble_evidence.py").write_text(
            "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaises(ValueError):
            self.run_pair()
        self.assertFalse(marker.exists())
        self.assertEqual(list(self.temporary.iterdir()), [])

    def test_hidden_bootstrap_never_runs_before_entrypoint_source_verification(self):
        marker = self.base / "untrusted-bootstrap-ran"
        target = self.source / "bin/validation_adapter.py"
        original = target.read_bytes()
        env = {**os.environ, **self.env, "GITHUB_WORKSPACE": str(self.workspace), "RUNNER_TEMP": str(self.temporary)}
        for flag, undo in (("--assume-unchanged", "--no-assume-unchanged"),
                           ("--skip-worktree", "--no-skip-worktree")):
            with self.subTest(flag=flag):
                self.git("update-index", flag, "bin/validation_adapter.py")
                target.write_text("from pathlib import Path\nPath(" + repr(str(marker)) +
                                  ").touch()\nraise ValueError('untrusted bootstrap ran')\n")
                try:
                    result = subprocess.run([os.sys.executable, "-I", str(self.source / "bin/run_workflow_validation.py")],
                                            env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 1)
                    self.assertFalse(marker.exists(), result.stdout)
                    self.assertEqual(list(self.temporary.iterdir()), [])
                finally:
                    target.write_bytes(original)
                    self.git("update-index", undo, "bin/validation_adapter.py")
                    marker.unlink(missing_ok=True)

    def test_replaced_or_symlinked_index_cannot_attest_altered_bootstrap(self):
        index = self.source / ".git/index"
        original_index = index.read_bytes()
        target = self.source / "bin/validation_adapter.py"
        original_source = target.read_bytes()
        marker = self.base / "untrusted-index-bootstrap-ran"
        target.write_text("from pathlib import Path\nPath(" + repr(str(marker)) +
                          ").touch()\nraise ValueError('untrusted index bootstrap ran')\n")
        self.git("add", "bin/validation_adapter.py")
        replacement = index.read_bytes()
        index.write_bytes(original_index)
        external = self.base / "replacement-index"
        external.write_bytes(replacement)
        env = {**os.environ, **self.env, "GITHUB_WORKSPACE": str(self.workspace), "RUNNER_TEMP": str(self.temporary)}
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    index.unlink()
                    index.symlink_to(external)
                else:
                    index.write_bytes(replacement)
                result = subprocess.run([os.sys.executable, "-I", str(self.source / "bin/run_workflow_validation.py")],
                                        env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertFalse(marker.exists(), result.stdout)
                self.assertEqual(list(self.temporary.iterdir()), [])
        index.unlink()
        index.write_bytes(original_index)
        target.write_bytes(original_source)
