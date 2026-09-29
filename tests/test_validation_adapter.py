"""Gate authority tests; common task execution remains QA-owned."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


def adapter():
    path = Path(__file__).resolve().parents[1] / "bin/validation_adapter.py"
    spec = importlib.util.spec_from_file_location("validation_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestExecutorBoundary(unittest.TestCase):
    def test_shared_interpreter_does_not_receive_operator_environment(self):
        gate = adapter()
        ambient = {"PATH": os.environ["PATH"], "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
                   "SYNTHETIC_CREDENTIAL": "must-not-pass", "HOME": "/private/operator",
                   "PYTHONPATH": "/unreviewed", "GITHUB_TOKEN": "synthetic"}
        command = [sys.executable, "-I", "-c",
                   "import os,json;print(json.dumps(dict(os.environ)))"]
        process, cancelled = gate.invoke_executor(command, gate.executor_environment(ambient),
                                                  tempfile.gettempdir())
        child = json.loads(process.stdout)
        self.assertEqual(process.returncode, 0)
        self.assertFalse(cancelled)
        self.assertEqual(child["PATH"], ambient["PATH"])
        for key in ("SYNTHETIC_CREDENTIAL", "HOME", "PYTHONPATH", "GITHUB_TOKEN"):
            self.assertNotIn(key, child)

    def test_unresponsive_executor_is_stopped_at_wrapper_deadline(self):
        gate = adapter()
        with tempfile.TemporaryDirectory() as directory:
            pid = Path(directory) / "pid"
            command = [sys.executable, "-I", "-c",
                       "import os,signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                       "pathlib.Path(__import__('sys').argv[1]).write_text(str(os.getpid()));time.sleep(20)",
                       str(pid)]
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "deadline"):
                gate.invoke_executor(command, gate.executor_environment(os.environ), directory,
                                     timeout=0.5, cleanup_timeout=0.2)
            self.assertLess(time.monotonic() - started, 5)
            self.assertTrue(pid.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid.read_text()), 0)


class TestQualificationWorkflow(unittest.TestCase):
    def test_agency_bootstrap_cohort_preserves_legacy_controls_and_coverage(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/compliance.yml").read_text()
        self.assertIn("ref: ${{ inputs.repo == 'agency' && 'v0.7.0' || 'v0.6.6' }}", workflow)
        self.assertIn("ref: v0.4.4", workflow)
        self.assertIn("ref: v0.4.0", workflow)
        self.assertIn("if [[ \"$GATE_FULL\" == \"true\" ]]; then", workflow)
        self.assertIn("gate_args+=(--full)", workflow)

    def test_real_shared_fixture_and_exact_candidate_are_required(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/test.yml").read_text()
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", workflow)
        self.assertIn("repository: stevekkall-beansgc/qa-kit", workflow)
        self.assertIn("ref: v0.7.0", workflow)
        self.assertIn("path: .qa-fixtures/qa-kit", workflow)
        self.assertIn("bash setup/qa-validation/bootstrap.sh", workflow)
        self.assertIn("bash scripts/test_validation_e2e.sh", workflow)
        self.assertNotIn("continue-on-error", workflow)


class TestCIContext(unittest.TestCase):
    def setUp(self):
        self.gate = adapter()
        self.sha = "a" * 40
        self.repository = "example/portable"
        self.environ = {
            "RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
            "GATE_EVENT_NAME": "push", "GATE_REPOSITORY": self.repository,
            "GATE_EVENT_REPOSITORY": self.repository,
            "GATE_EXPECTED_SHA": self.sha, "GATE_REF": "refs/heads/main",
            "GATE_PUSH_AFTER": self.sha,
        }
        self.event = {"repository": {"full_name": self.repository},
                      "after": self.sha, "ref": "refs/heads/main"}

    def check(self):
        return self.gate.validate_ci_context(
            self.environ, self.event, self.repository, self.sha)

    def test_hosted_push_reports_execution_context_not_check_success(self):
        result = self.check()
        self.assertEqual(result["expected_head"], self.sha)
        self.assertEqual(result["run_id"], "123")
        self.assertFalse(result["github_check_verified"])

    def test_fork_pr_is_hosted_exact_head_only(self):
        self.environ.update(GATE_EVENT_NAME="pull_request",
                            GATE_REF="refs/pull/8/merge", GATE_PUSH_AFTER="")
        self.event = {"repository": {"full_name": self.repository},
                      "number": 8, "pull_request": {
                          "head": {"sha": self.sha, "repo": {"full_name": "fork/portable"}},
                          "base": {"repo": {"full_name": self.repository}}}}
        self.assertEqual(self.check()["event"], "pull_request")

    def test_local_or_self_hosted_cannot_claim_initial_ci_profile(self):
        for value in ("self-hosted", "", "local"):
            with self.subTest(value=value):
                self.environ["RUNNER_ENVIRONMENT"] = value
                with self.assertRaises(ValueError):
                    self.check()

    def test_repository_input_cannot_select_other_enrollment(self):
        for key in ("GATE_REPOSITORY", "GATE_EVENT_REPOSITORY"):
            with self.subTest(key=key):
                original = self.environ[key]
                self.environ[key] = "other/repository"
                with self.assertRaises(ValueError):
                    self.check()
                self.environ[key] = original

    def test_event_file_and_environment_repository_must_agree(self):
        self.event["repository"]["full_name"] = "other/repository"
        with self.assertRaises(ValueError):
            self.check()

    def test_malformed_event_metadata_is_a_closed_denial(self):
        for value in ("example/portable", [], None):
            with self.subTest(value=value):
                self.event["repository"] = value
                with self.assertRaises(ValueError):
                    self.check()

    def test_wrong_head_or_push_ref_fails_before_execution(self):
        for field, value in (("after", "b" * 40), ("ref", "refs/tags/v1")):
            with self.subTest(field=field):
                old = self.event[field]
                self.event[field] = value
                with self.assertRaises(ValueError):
                    self.check()
                self.event[field] = old

    def test_privileged_or_unknown_event_denied(self):
        for event in ("pull_request_target", "workflow_dispatch", "schedule", "repository_dispatch"):
            with self.subTest(event=event):
                self.environ["GATE_EVENT_NAME"] = event
                with self.assertRaises(ValueError):
                    self.check()

    def test_pr_merge_sha_cannot_replace_reviewed_head(self):
        self.environ.update(GATE_EVENT_NAME="pull_request", GATE_REF="refs/pull/8/merge")
        self.event = {"repository": {"full_name": self.repository}, "number": 8,
                      "pull_request": {"head": {"sha": "b" * 40},
                                       "base": {"repo": {"full_name": self.repository}}}}
        with self.assertRaises(ValueError):
            self.check()


class TestMacPilotContext(TestCIContext):
    def setUp(self):
        super().setUp()
        self.repository = "stevekkall-beansgc/legume-labs"
        self.variant = "macos-arm64-py312"
        self.environ.update(RUNNER_ENVIRONMENT="self-hosted", RUNNER_OS="macOS",
                            RUNNER_ARCH="ARM64", RUNNER_NAME="beans-macbook-legume-labs-validation",
                            GATE_REPOSITORY=self.repository, GATE_EVENT_REPOSITORY=self.repository)
        self.event["repository"]["full_name"] = self.repository

    def check(self):
        return self.gate.validate_ci_context(self.environ, self.event, self.repository,
                                             self.sha, self.variant)

    def test_fork_pr_is_hosted_exact_head_only(self):
        self.environ.update(GATE_EVENT_NAME="pull_request", GATE_REF="refs/pull/8/merge")
        self.event = {"repository": {"full_name": self.repository}, "number": 8,
                      "pull_request": {"head": {"sha": self.sha},
                                       "base": {"repo": {"full_name": self.repository}}}}
        with self.assertRaises(ValueError):
            self.check()

    def test_local_or_self_hosted_cannot_claim_initial_ci_profile(self):
        for value in ("local", ""):
            self.environ["RUNNER_ENVIRONMENT"] = value
            with self.assertRaises(ValueError):
                self.check()

    def test_name_os_arch_and_variant_are_closed_bindings(self):
        for key, value in (("RUNNER_NAME", "beans-macbook-beanfit"), ("RUNNER_OS", "Linux"),
                           ("RUNNER_ARCH", "X64"), ("GATE_REF", "refs/heads/release/test")):
            with self.subTest(key=key):
                old = self.environ[key]
                self.environ[key] = value
                with self.assertRaises(ValueError):
                    self.check()
                self.environ[key] = old
        self.variant = "linux-py312"
        with self.assertRaises(ValueError):
            self.check()

    def test_separate_app_runner_and_full_variant_are_required(self):
        self.repository = "stevekkall-beansgc/beanfit-app"
        self.environ.update(GATE_REPOSITORY=self.repository, GATE_EVENT_REPOSITORY=self.repository,
                            RUNNER_NAME="beans-macbook-beanfit-app-validation")
        self.event["repository"]["full_name"] = self.repository
        self.variant = "macos-arm64-node22-py312"
        self.assertEqual(self.check()["runner_name"], "beans-macbook-beanfit-app-validation")

    def test_precheckout_cli_uses_fixed_alias_and_rejects_fork_without_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            event.write_text(json.dumps(self.event))
            environment = {**os.environ, **self.environ, "GITHUB_EVENT_PATH": str(event),
                           "GATE_REPO": "bean-labs"}
            command = [sys.executable, "-I", str(Path(__file__).resolve().parents[1] / "bin/check_ci_context.py")]
            result = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)["github_check_verified"])
            for key, value in (("GATE_REPO", "agency"), ("GATE_EVENT_NAME", "pull_request"),
                               ("RUNNER_NAME", "beans-macbook-beanfit")):
                changed = {**environment, key: value}
                result = subprocess.run(command, env=changed, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


class TestTrustedControls(unittest.TestCase):
    def setUp(self):
        self.gate = adapter()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.control = self.root / "authorization.json"
        self.control.write_text(json.dumps({"effects": ["scratch"]}))
        self.digest = hashlib.sha256(self.control.read_bytes()).hexdigest()
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        (self.root / ".gitignore").write_text("ignored/\n")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Synthetic",
                        "-c", "user.email=synthetic@example.invalid", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "tracked controls"], check=True)

    def test_ignored_control_is_not_commit_provenance_even_with_correct_digest(self):
        ignored = self.root / "ignored"
        ignored.mkdir()
        path = ignored / "bundle.json"
        path.write_text('{"effects": []}')
        head = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"],
                                       text=True).strip()
        self.gate.verify_checkout(self.root, head)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            self.gate.read_trusted_json(path, self.root, digest)

    def test_git_administrative_file_cannot_authorize_control(self):
        path = self.root / ".git/config"
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.gate.read_trusted_json(path, self.root, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_exact_control_digest_is_required(self):
        value = self.gate.read_trusted_json(self.control, self.root, self.digest)
        self.assertEqual(value, {"effects": ["scratch"]})
        with self.assertRaises(ValueError):
            self.gate.read_trusted_json(self.control, self.root, "0" * 64)

    def test_symlink_control_is_not_trusted(self):
        link = self.root / "linked.json"
        link.symlink_to(self.control)
        with self.assertRaises(ValueError):
            self.gate.read_trusted_json(link, self.root, self.digest)

    def test_caller_file_outside_trusted_root_cannot_authorize_execution(self):
        inside = self.root / "trusted"
        inside.mkdir()
        with self.assertRaises(ValueError):
            self.gate.read_trusted_json(self.control, inside, self.digest)

    def test_missing_or_malformed_control_never_falls_back(self):
        with self.assertRaises(ValueError):
            self.gate.read_trusted_json(self.root / "absent.json", self.root, self.digest)
        self.control.write_text("[]")
        digest = hashlib.sha256(self.control.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            self.gate.read_trusted_json(self.control, self.root, digest)


class TestControlSource(unittest.TestCase):
    def setUp(self):
        self.gate = adapter()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.source = self.root / "source.py"
        self.source.write_text("print('reviewed')\n")
        self.git("add", ".")
        self.git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic control")
        self.head = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args],
                                       stderr=subprocess.DEVNULL, text=True)

    def test_clean_control_is_verified(self):
        self.assertEqual(self.gate.verify_checkout(self.root, self.head), self.root.resolve())

    def test_wrong_commit_and_dirty_source_are_denied(self):
        with self.assertRaises(ValueError):
            self.gate.verify_checkout(self.root, "0" * 40)
        self.source.write_text("print('changed')\n")
        with self.assertRaises(ValueError):
            self.gate.verify_checkout(self.root, self.head)

    def test_assume_unchanged_cannot_hide_executable_control_edit(self):
        self.git("update-index", "--assume-unchanged", "source.py")
        self.source.write_text("print('unreviewed')\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaises(ValueError):
            self.gate.verify_checkout(self.root, self.head)

    def test_skip_worktree_cannot_hide_executable_control_edit(self):
        self.git("update-index", "--skip-worktree", "source.py")
        self.source.write_text("print('unreviewed')\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaises(ValueError):
            self.gate.verify_checkout(self.root, self.head)

    def test_git_filemode_false_cannot_hide_mode_drift(self):
        self.git("config", "core.filemode", "false")
        self.source.chmod(0o755)
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaises(ValueError):
            self.gate.verify_checkout(self.root, self.head)

    def test_ambient_git_override_cannot_redirect_source(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"GIT_DIR": "/not/a/repository", "GIT_WORK_TREE": "/wrong"}):
            self.assertEqual(self.gate.verify_checkout(self.root, self.head), self.root.resolve())


if __name__ == "__main__":
    unittest.main()
