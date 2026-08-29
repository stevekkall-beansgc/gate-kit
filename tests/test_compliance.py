"""Unit tests for gate-kit compliance.py — pure logic only, no network."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import compliance  # noqa: E402


class TestExpand(unittest.TestCase):
    def test_tilde(self):
        self.assertFalse(str(compliance.expand("~/x")).startswith("~"))

    def test_plain(self):
        self.assertEqual(str(compliance.expand("/tmp/x")), "/tmp/x")


class TestSh(unittest.TestCase):
    def test_success(self):
        r = compliance.sh(["true"], Path(tempfile.gettempdir()))
        self.assertTrue(r["ok"])

    def test_failure_captures_tail(self):
        r = compliance.sh(["/bin/sh", "-c", "echo boom >&2; exit 3"], Path(tempfile.gettempdir()))
        self.assertFalse(r["ok"])
        self.assertIn("boom", r["tail"])

    def test_missing_binary(self):
        r = compliance.sh(["definitely-not-a-binary-xyz"], Path(tempfile.gettempdir()))
        self.assertFalse(r["ok"])
        self.assertIn("entrypoint missing", r["tail"])


class TestDocsCheck(unittest.TestCase):
    def _root(self, agents=None, readme=None):
        d = tempfile.mkdtemp()
        root = Path(d)
        if agents is not None:
            (root / "AGENTS.md").write_text(agents)
        if readme is not None:
            (root / "README.md").write_text(readme)
        return root

    def test_missing_agents(self):
        problems = compliance.docs_check(self._root(readme="# r"), ["true"])
        self.assertIn("missing AGENTS.md", problems)

    def test_missing_test_commands_section(self):
        problems = compliance.docs_check(
            self._root(agents="# a\n", readme="# r\nreferences AGENTS.md"), ["true"])
        self.assertTrue(any("Test commands" in p for p in problems))

    def test_unit_cmd_not_stated(self):
        problems = compliance.docs_check(
            self._root(agents="## Test commands\nnothing here", readme="# r\nAGENTS.md"),
            ["python3", "-m", "unittest"])
        self.assertTrue(any("does not state" in p for p in problems))

    def test_valid_docs_pass(self):
        problems = compliance.docs_check(
            self._root(agents="## Test commands\n`python3 -m unittest`",
                       readme="# r\nsee AGENTS.md"),
            ["python3", "-m", "unittest"])
        self.assertEqual(problems, [])

    def test_missing_readme(self):
        problems = compliance.docs_check(
            self._root(agents="## Test commands\ncmd"), ["cmd"])
        self.assertTrue(any("README" in p for p in problems))


class TestManifestContract(unittest.TestCase):
    def test_active_rows_require_unit_entrypoint(self):
        problems = compliance.manifest_problems({
            "repos": [{"name": "active-repo", "status": "active", "path": "/tmp"}]
        })
        self.assertIn("active-repo: missing unit entrypoint", problems)

    def test_planned_rows_are_explicitly_excluded(self):
        problems = compliance.manifest_problems({
            "repos": [{"name": "planned-repo", "status": "planned",
                       "gap": "not started"}]
        })
        self.assertEqual(problems, ["manifest has no active/unit-only repos"])

    def test_unknown_status_fails_closed(self):
        problems = compliance.manifest_problems({
            "repos": [{"name": "mystery", "status": "paused", "path": "/tmp",
                       "unit": {"cmd": ["true"]}}]
        })
        self.assertTrue(any("unknown status" in p for p in problems))

    def test_relative_manifest_env_resolves_from_repo_root(self):
        root = Path(tempfile.mkdtemp())
        env = compliance.command_env(root, {"env": {"PYTHONPATH": "src",
                                                      "ABS": "/opt/bin"}})
        self.assertEqual(env["PYTHONPATH"], str(root / "src"))
        self.assertEqual(env["ABS"], "/opt/bin")


class TestMainContract(unittest.TestCase):
    def _run(self, args, manifest):
        old_manifest = compliance.MANIFEST
        try:
            compliance.MANIFEST = manifest
            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["compliance.py", *args]), \
                    contextlib.redirect_stdout(output):
                result = compliance.main()
        finally:
            compliance.MANIFEST = old_manifest
        return result, output.getvalue()

    def test_missing_manifest_fails_closed_with_verdict_json(self):
        manifest = Path(tempfile.mkdtemp()) / "manifest.json"
        result, output = self._run([], manifest)
        self.assertEqual(result, 1)
        verdict = json.loads(output.splitlines()[-1])
        self.assertEqual(verdict["failures"], 1)
        self.assertIn("infrastructure", verdict)

    def test_root_override_checks_the_caller_checkout(self):
        root = Path(tempfile.mkdtemp())
        (root / "AGENTS.md").write_text("## Test commands\ntrue\n")
        (root / "README.md").write_text("See AGENTS.md\n")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"repos": [{
            "name": "caller", "status": "active", "path": "/not-used",
            "unit": {"cmd": ["true"]}
        }]}))
        result, output = self._run(["--repo", "caller", "--root", str(root)], manifest)
        self.assertEqual(result, 0)
        verdict = json.loads(output.splitlines()[-1])
        self.assertEqual(verdict["coverage"]["selected"], 1)
        self.assertEqual(verdict["repos"][0]["verdict"], "PASS")

    def test_missing_root_is_a_gate_failure(self):
        root = Path(tempfile.mkdtemp())
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"repos": [{
            "name": "caller", "status": "active", "path": "/not-used",
            "unit": {"cmd": ["true"]}
        }]}))
        result, output = self._run(["--repo", "caller", "--root", str(root / "missing")], manifest)
        self.assertEqual(result, 1)
        verdict = json.loads(output.splitlines()[-1])
        self.assertEqual(verdict["repos"][0]["verdict"], "FAIL")


class TestWorkflowContract(unittest.TestCase):
    def test_workflow_runs_tracked_gate_entrypoint_and_preserves_failures(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/compliance.yml").read_text()
        self.assertIn("path: gate-kit", workflow)
        self.assertIn("ref: v0.4.2", workflow)
        self.assertIn("ref: v0.3.1", workflow)
        self.assertIn("ref: v0.1.1", workflow)
        self.assertIn("python3 gate-kit/bin/compliance.py", workflow)
        self.assertIn("--root caller", workflow)
        self.assertIn("QA_KIT_DIR: ${{ github.workspace }}/qa-kit", workflow)
        self.assertIn("GATE_REPO: ${{ inputs.repo }}", workflow)
        self.assertIn("GATE_FULL: ${{ inputs.full }}", workflow)
        self.assertIn("set -o pipefail", workflow)
        self.assertIn('if [[ "$GATE_FULL" == "true" ]]', workflow)
        self.assertIn("gate_args+=(--full)", workflow)
        self.assertIn('"${gate_args[@]}"', workflow)
        self.assertNotIn("python3 qa-kit/bin/compliance.py", workflow)


if __name__ == "__main__":
    unittest.main()
