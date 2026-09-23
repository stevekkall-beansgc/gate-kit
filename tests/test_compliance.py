"""Unit tests for gate-kit compliance.py — pure logic only, no network."""
import contextlib
import io
import json
import re
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

    def test_timeout_fails_closed(self):
        # The checker is source-pinned by CI, so retain its production 900s
        # argument while shortening only the real subprocess for this test.
        real_run = compliance.subprocess.run

        def short_run(*args, **kwargs):
            self.assertEqual(kwargs["timeout"], 900)
            return real_run(*args, **{**kwargs, "timeout": 0.1})

        with mock.patch.object(compliance.subprocess, "run", side_effect=short_run):
            r = compliance.sh([sys.executable, "-c", "import time; time.sleep(10)"],
                              Path(tempfile.gettempdir()))
        self.assertFalse(r["ok"])
        self.assertIn("timeout 900s", r["tail"])
        self.assertLess(r["secs"], 5)


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
    def test_gate_caller_keeps_pull_requests_off_self_hosted_runner(self):
        caller = (Path(__file__).resolve().parents[1] /
                  ".github/workflows/gate.yml").read_text()
        self.assertIn("on: [pull_request, push]", caller)
        self.assertIn(
            "runner: ${{ github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/')) && 'beans-mac' || 'ubuntu-latest' }}",
            caller,
        )

    def test_workflow_runs_tracked_gate_entrypoint_and_preserves_failures(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/compliance.yml").read_text()
        self.assertIn("path: gate-kit", workflow)
        self.assertIn("ref: v0.4.4", workflow)
        self.assertIn("ref: v0.6.1", workflow)
        self.assertIn("ref: v0.4.0", workflow)
        self.assertIn("python3 gate-kit/bin/compliance.py", workflow)
        self.assertIn("--root caller", workflow)
        self.assertIn("QA_KIT_DIR: ${{ github.workspace }}/qa-kit", workflow)
        self.assertIn("GATE_REPO: ${{ inputs.repo }}", workflow)
        self.assertIn("GATE_FULL: ${{ inputs.full }}", workflow)
        self.assertIn("default: ubuntu-latest", workflow)
        self.assertIn("runs-on: ${{ inputs.runner }}", workflow)
        self.assertIn("if: inputs.runner != 'beans-mac'", workflow)
        self.assertIn("if: inputs.runner == 'beans-mac'", workflow)
        self.assertIn("name: Verify preinstalled self-hosted Python", workflow)
        self.assertIn("set -o pipefail", workflow)
        self.assertIn('if [[ "$GATE_FULL" == "true" ]]', workflow)
        self.assertIn("gate_args+=(--full)", workflow)
        self.assertIn('"${gate_args[@]}"', workflow)
        self.assertNotIn("python3 qa-kit/bin/compliance.py", workflow)

    def test_qa_manifest_pin_documented_accurately_in_repo_docs(self):
        root = Path(__file__).resolve().parents[1]
        for doc in ("AGENTS.md", "README.md"):
            text = (root / doc).read_text()
            self.assertIn("v0.6.1", text, f"{doc} must document qa-kit v0.6.1 pin")
            self.assertNotIn("v0.4.3", text, f"{doc} must not reference the retired qa-kit pin")
            self.assertIn("v0.4.4", text, f"{doc} must keep the immutable gate-kit CLI pin")

    def test_beanfit_fixture_pin_documented_accurately_in_repo_docs(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/compliance.yml").read_text()
        beanfit = workflow.split("repository: stevekkall-beansgc/beanfit", 1)[1]
        self.assertIn("ref: v0.4.0", beanfit.split("path: beanfit", 1)[0])
        for doc in ("AGENTS.md", "README.md"):
            text = (root / doc).read_text()
            self.assertIn("v0.4.0", text, f"{doc} must document beanfit fixture v0.4.0 pin")
            self.assertNotIn("v0.1.1", text, f"{doc} must not reference the retired fixture pin")

    def test_readme_quickstart_and_release_pins_match_checkout(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text()
        workflow = (root / ".github/workflows/compliance.yml").read_text()

        self.assertIn("python3 examples/synthetic_quickstart.py", readme)
        for heading in (
                "## 1. The problem",
                "## 2. Run the synthetic demo",
                "## 3. Follow the implementation",
                "## 4. Failure-mode proof",
                "## 5. Supported scope",
                "## 6. Release pins in v0.4.20"):
            self.assertIn(heading, readme)
        for link in (
                "[`bin/compliance.py`](bin/compliance.py)",
                "[`.github/workflows/compliance.yml`](.github/workflows/compliance.yml)",
                "[`examples/synthetic_quickstart.py`](examples/synthetic_quickstart.py)"):
            self.assertIn(link, readme)
        self.assertNotIn("/Users/", readme)
        self.assertNotIn("~/beans", readme)

        for repository in ("stevekkall-beansgc/gate-kit",
                           "stevekkall-beansgc/qa-kit",
                           "stevekkall-beansgc/beanfit"):
            checkout = workflow.split(f"repository: {repository}", 1)[1]
            checkout = checkout.split("path:", 1)[0]
            match = re.search(r"\n\s+ref:\s*(\S+)", checkout)
            self.assertIsNotNone(match)
            self.assertIn(f"`{match.group(1)}`", readme)
        self.assertIn("v0.4.20", readme)
        self.assertIn("immutable `v0.4.4`", readme)
        self.assertIn("not a claim about release recency", readme)

    def test_caller_checkout_is_the_reviewed_commit(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/compliance.yml").read_text()
        caller = workflow.split("path: caller", 1)[0]
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", caller)

    def test_node_runtime_is_installed_before_compliance(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/compliance.yml").read_text()
        self.assertIn("uses: actions/setup-node@", workflow)
        self.assertIn('node-version: "22"', workflow)
        self.assertLess(workflow.index("uses: actions/setup-node@"),
                        workflow.index("name: Run compliance gate"))

    def test_node_runtime_covers_registered_javascript_profiles(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/compliance.yml").read_text()
        guard = workflow.split("uses: actions/setup-node@", 1)[0].rsplit("if:", 1)[-1].strip()
        self.assertEqual(
            guard, "${{ inputs.repo == 'agency' || inputs.repo == 'beanfit-app' || inputs.repo == 'bean-counter' }}")
        covered = {name for name in ("agency", "beanfit-app", "bean-counter")
                   if f"inputs.repo == '{name}'" in guard}
        self.assertEqual(covered, {"agency", "beanfit-app", "bean-counter"})
        for other in ("agents", "beanfit", "gate-kit", "qa-kit"):
            self.assertNotIn(f"inputs.repo == '{other}'", guard)


class TestSecurityPolicy(unittest.TestCase):
    def test_policy_is_private_reporting_linked_and_scoped(self):
        root = Path(__file__).resolve().parents[1]
        security = (root / "SECURITY.md").read_text()
        readme = (root / "README.md").read_text()
        self.assertIn("[`SECURITY.md`](SECURITY.md)", readme)
        self.assertIn(
            "https://github.com/stevekkall-beansgc/gate-kit/security/advisories/new",
            security,
        )
        self.assertIn("current `main` branch", security)
        self.assertIn("latest release", security)
        self.assertIn("Scope and limitations", security)
        self.assertIn("privately", security)


if __name__ == "__main__":
    unittest.main()
