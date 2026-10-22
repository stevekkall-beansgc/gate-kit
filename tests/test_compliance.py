"""Unit tests for gate-kit compliance.py — pure logic only, no network."""
import contextlib
import io
import json
import os
import subprocess
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

    def _command_output_cli(self, output, returncode):
        cli = Path(compliance.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            command = [sys.executable, "-c",
                       "import sys; from pathlib import Path; "
                       "Path('executed').write_text('ran'); "
                       f"sys.stdout.buffer.write({output!r}); sys.exit({returncode})"]
            repo = {"name": "synthetic", "status": "active", "path": str(root),
                    "setup": {"cmd": ["/usr/bin/true"]},
                    "unit": {"cmd": command}, "e2e": {"cmd": ["/usr/bin/true"]}}
            (root / "AGENTS.md").write_text("## Test commands\n" + " ".join(command))
            (root / "README.md").write_text("See AGENTS.md")
            (root / "manifest.json").write_text(json.dumps({"repos": [repo]}))
            process = subprocess.run(
                [sys.executable, "-B", str(cli), "--repo", "synthetic", "--full"],
                env={"QA_KIT_DIR": str(root), "HOME": str(home), "PATH": os.defpath,
                     "PYTHONUTF8": "1"}, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, int(bool(returncode)))
            self.assertNotIn("Traceback", process.stderr)
            verdict = json.loads(process.stdout.splitlines()[-1])
            self.assertEqual(verdict["gate"], "compliance")
            self.assertEqual(verdict["failures"], int(bool(returncode)))
            self.assertEqual(verdict["repos"][0]["verdict"], "FAIL" if returncode else "PASS")
            checks = verdict["repos"][0]["checks"]
            self.assertEqual([check["name"] for check in checks],
                             ["docs", "setup", "unit", "e2e"])
            self.assertTrue(all(check["ok"] for check in checks if check["name"] != "unit"))
            self.assertEqual(checks[2]["ok"], not returncode)
            self.assertEqual(checks[2]["detail"],
                             output.decode("utf-8", errors="replace") if returncode else None)
            self.assertEqual((root / "executed").read_text(), "ran")
            self.assertNotIn(str(root), process.stdout + process.stderr)

    def test_invalid_command_output_preserves_child_verdict(self):
        for returncode in (0, 3):
            with self.subTest(returncode=returncode):
                self._command_output_cli(b"synthetic-output-\xff", returncode)

    def test_utf8_command_output_control_preserves_child_verdict(self):
        for returncode in (0, 3):
            with self.subTest(returncode=returncode):
                self._command_output_cli("synthetic-output-Café".encode("utf-8"), returncode)

    def _document_bytes_cli(self, invalid_document=None):
        cli = Path(compliance.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            command = [sys.executable, "-c",
                       "from pathlib import Path; "
                       "p = Path('executed'); "
                       "p.write_text(p.read_text() + 'ran' if p.exists() else 'ran')"]
            repo = {"name": "synthetic", "status": "active", "path": str(root),
                    **{label: {"cmd": command} for label in ("setup", "unit", "e2e")}}
            (root / "AGENTS.md").write_bytes(
                ("## Test commands\n" + " ".join(command) + "\nCafé checks\n").encode("utf-8"))
            (root / "README.md").write_bytes("See AGENTS.md — Café\n".encode("utf-8"))
            if invalid_document:
                (root / invalid_document).write_bytes(b"synthetic-private-document\xff")
            (root / "manifest.json").write_text(json.dumps({"repos": [repo]}))
            process = subprocess.run(
                [sys.executable, "-B", str(cli), "--repo", "synthetic", "--full"],
                env={"QA_KIT_DIR": str(root), "HOME": str(home), "PATH": os.defpath,
                     "PYTHONUTF8": "1"}, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 1 if invalid_document else 0)
            self.assertNotIn("Traceback", process.stderr)
            verdict = json.loads(process.stdout.splitlines()[-1])
            self.assertEqual(verdict["gate"], "compliance")
            self.assertEqual(verdict["failures"], 1 if invalid_document else 0)
            self.assertEqual(verdict["repos"][0]["verdict"],
                             "FAIL" if invalid_document else "PASS")
            checks = verdict["repos"][0]["checks"]
            self.assertEqual([check["name"] for check in checks],
                             ["docs", "setup", "unit", "e2e"])
            self.assertEqual(checks[0]["ok"], not invalid_document)
            self.assertEqual(checks[0]["detail"],
                             f"cannot read {invalid_document}: invalid text encoding"
                             if invalid_document else "")
            self.assertTrue(all(check["ok"] for check in checks[1:]))
            self.assertEqual((root / "executed").read_text(), "ranranran")
            self.assertNotIn("synthetic-private-document", process.stdout + process.stderr)
            self.assertNotIn(str(root), process.stdout + process.stderr)

    def test_invalid_document_bytes_preserve_final_json(self):
        for document in ("AGENTS.md", "README.md"):
            with self.subTest(document=document):
                self._document_bytes_cli(document)

    def test_utf8_document_control_preserves_selected_commands(self):
        self._document_bytes_cli()

    def _executable_format_cli(self, valid):
        cli = Path(compliance.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            entrypoint = root / "synthetic-entrypoint"
            entrypoint.write_text(("#!/bin/sh\n" if valid else "") +
                                  "printf ran >> executed\n")
            entrypoint.chmod(0o700)
            (root / "README.md").write_text("See AGENTS.md")
            for label in ("setup", "unit", "e2e"):
                with self.subTest(label=label):
                    marker = root / "executed"
                    marker.unlink(missing_ok=True)
                    repo = {"name": "synthetic", "status": "active", "path": str(root),
                            **{tier: {"cmd": ["/usr/bin/true"]}
                               for tier in ("setup", "unit", "e2e")}}
                    repo[label] = {"cmd": [str(entrypoint)]}
                    (root / "AGENTS.md").write_text(
                        "## Test commands\n" + " ".join(repo["unit"]["cmd"]))
                    (root / "manifest.json").write_text(json.dumps({"repos": [repo]}))
                    process = subprocess.run(
                        [sys.executable, "-B", str(cli), "--repo", "synthetic", "--full"],
                        env={"QA_KIT_DIR": str(root), "HOME": str(home), "PATH": os.defpath},
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(process.returncode, 0 if valid else 1)
                    self.assertNotIn("Traceback", process.stderr)
                    verdict = json.loads(process.stdout.splitlines()[-1])
                    self.assertEqual(verdict["gate"], "compliance")
                    self.assertEqual(verdict["failures"], 0 if valid else 1)
                    self.assertEqual(verdict["repos"][0]["verdict"], "PASS" if valid else "FAIL")
                    checks = verdict["repos"][0]["checks"]
                    self.assertEqual([check["name"] for check in checks],
                                     ["docs", "setup", "unit", "e2e"])
                    for check in checks:
                        self.assertEqual(check["ok"], valid or check["name"] != label)
                        if check["name"] == label:
                            self.assertEqual(check["detail"],
                                             None if valid else "entrypoint launch failed")
                    self.assertEqual(marker.read_text() if marker.exists() else "", "ran" if valid else "")
                    self.assertNotIn(str(root), process.stdout + process.stderr)

    def test_invalid_executable_format_preserves_final_json(self):
        self._executable_format_cli(valid=False)

    def test_valid_executable_format_control_reaches_selected_tier(self):
        self._executable_format_cli(valid=True)

    def test_permission_denied_entrypoint_preserves_final_json(self):
        cli = Path(compliance.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            entrypoint = root / "denied-entrypoint"
            entrypoint.write_text("#!/bin/sh\nprintf ran >> denied-executed\n")
            entrypoint.chmod(0o600)
            (root / "README.md").write_text("See AGENTS.md")
            for label in ("setup", "unit", "e2e"):
                with self.subTest(label=label):
                    repo = {"name": "synthetic", "status": "active", "path": str(root),
                            "setup": {"cmd": ["/usr/bin/true"]},
                            "unit": {"cmd": ["/usr/bin/true"]},
                            "e2e": {"cmd": ["/usr/bin/true"]}}
                    repo[label] = {"cmd": [str(entrypoint)]}
                    (root / "AGENTS.md").write_text(
                        "## Test commands\n" + " ".join(repo["unit"]["cmd"]))
                    (root / "manifest.json").write_text(json.dumps({"repos": [repo]}))
                    process = subprocess.run(
                        [sys.executable, "-B", str(cli), "--repo", "synthetic", "--full"],
                        env={"QA_KIT_DIR": str(root), "HOME": str(home), "PATH": os.defpath},
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(process.returncode, 1)
                    self.assertNotIn("Traceback", process.stderr)
                    self.assertFalse((root / "denied-executed").exists())
                    verdict = json.loads(process.stdout.splitlines()[-1])
                    self.assertEqual(verdict["gate"], "compliance")
                    self.assertEqual(verdict["failures"], 1)
                    self.assertEqual(verdict["repos"][0]["verdict"], "FAIL")
                    checks = {check["name"]: check for check in verdict["repos"][0]["checks"]}
                    self.assertFalse(checks[label]["ok"])
                    self.assertEqual(checks[label]["detail"], "entrypoint permission denied")
                    self.assertTrue(all(check["ok"] for name, check in checks.items()
                                        if name != label))
                    self.assertNotIn(str(root), process.stdout + process.stderr)

    def test_executable_entrypoint_control_reaches_each_tier(self):
        cli = Path(compliance.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            entrypoint = root / "valid-entrypoint"
            entrypoint.write_text("#!/bin/sh\nprintf ran >> executed\n")
            entrypoint.chmod(0o700)
            command = [str(entrypoint)]
            repo = {"name": "synthetic", "status": "active", "path": str(root),
                    **{label: {"cmd": command} for label in ("setup", "unit", "e2e")}}
            (root / "README.md").write_text("See AGENTS.md")
            (root / "AGENTS.md").write_text("## Test commands\n" + " ".join(command))
            (root / "manifest.json").write_text(json.dumps({"repos": [repo]}))
            process = subprocess.run(
                [sys.executable, "-B", str(cli), "--repo", "synthetic", "--full"],
                env={"QA_KIT_DIR": str(root), "HOME": str(home), "PATH": os.defpath},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            verdict = json.loads(process.stdout.splitlines()[-1])
            self.assertEqual(verdict["failures"], 0)
            self.assertEqual(verdict["repos"][0]["verdict"], "PASS")
            self.assertEqual([check["name"] for check in verdict["repos"][0]["checks"]],
                             ["docs", "setup", "unit", "e2e"])
            self.assertTrue(all(check["ok"] for check in verdict["repos"][0]["checks"]))
            self.assertEqual((root / "executed").read_text(), "ranranran")

    def test_container_status_refuses_with_json_before_any_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            for status in ([], {}):
                with self.subTest(status=status):
                    manifest.write_text(json.dumps({"repos": [
                        {"name": "valid", "status": "active", "path": str(root),
                         "unit": {"cmd": ["true"]}},
                        {"name": "malformed", "status": status, "path": str(root),
                         "unit": {"cmd": ["true"]}}
                    ]}))
                    with mock.patch.object(compliance, "sh") as run_command:
                        result, output = self._run(["--repo", "valid"], manifest)
                    run_command.assert_not_called()
                    self.assertEqual(result, 1)
                    verdict = json.loads(output.splitlines()[-1])
                    self.assertEqual(verdict["gate"], "compliance")
                    self.assertEqual(verdict["failures"], 1)
                    self.assertEqual(verdict["repos"], [])
                    self.assertIn(f"malformed: unknown status {status!r}",
                                  verdict["infrastructure"])

    def test_invalid_manifest_env_refuses_before_any_selected_commands(self):
        invalid = ({"BAD=NAME": "synthetic"},
                   {"BAD\0NAME": "synthetic"},
                   {"VALID": "synthetic\0value"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            for label in ("setup", "unit", "e2e"):
                for values in invalid:
                    with self.subTest(label=label, values=values):
                        malformed = {"name": "malformed", "status": "active",
                                     "path": str(root), "unit": {"cmd": ["true"]}}
                        malformed[label] = {"cmd": ["true"], "env": values}
                        manifest.write_text(json.dumps({"repos": [
                            {"name": "selected", "status": "active", "path": str(root),
                             "unit": {"cmd": ["true"]}}, malformed
                        ]}))
                        with mock.patch.object(compliance, "sh", return_value={
                                "ok": True, "secs": 0.0, "tail": ""}) as run_command:
                            result, output = self._run(["--repo", "selected"], manifest)
                        run_command.assert_not_called()
                        self.assertEqual(result, 1)
                        verdict = json.loads(output.splitlines()[-1])
                        self.assertEqual(verdict["failures"], 1)
                        self.assertEqual(verdict["repos"], [])
                        self.assertIn(f"malformed: {label}.env contains invalid environment names or NUL bytes",
                                      verdict["infrastructure"])
                        self.assertNotIn("synthetic", output)

    def test_nul_command_refuses_with_json_before_any_commands(self):
        cli = Path(compliance.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            valid = [sys.executable, "-c",
                     "from pathlib import Path; Path('executed').touch()"]
            (root / "README.md").write_text("See AGENTS.md")
            for label in ("setup", "unit", "e2e"):
                for position in ("executable", "argument"):
                    for selected in ("malformed", "valid"):
                        with self.subTest(label=label, position=position, selected=selected):
                            marker.unlink(missing_ok=True)
                            malformed = {"name": "malformed", "status": "active",
                                         "path": str(root), "setup": {"cmd": valid},
                                         "unit": {"cmd": valid}, "e2e": {"cmd": valid}}
                            cmd = (["synthetic\0executable"] if position == "executable"
                                   else [*valid, "synthetic\0argument"])
                            malformed[label] = {"cmd": cmd}
                            (root / "AGENTS.md").write_text(
                                "## Test commands\n" + " ".join(malformed["unit"]["cmd"]) +
                                "\n" + " ".join(valid))
                            (root / "manifest.json").write_text(json.dumps({"repos": [
                                malformed, {"name": "valid", "status": "unit-only",
                                            "path": str(root), "unit": {"cmd": valid}}
                            ]}))
                            process = subprocess.run(
                                [sys.executable, "-B", str(cli), "--repo", selected, "--full"],
                                env={"QA_KIT_DIR": str(root), "PATH": os.defpath},
                                capture_output=True, text=True, timeout=10)
                            self.assertEqual(process.returncode, 1)
                            self.assertNotIn("Traceback", process.stderr)
                            self.assertFalse(marker.exists(), "commands ran before refusal")
                            verdict = json.loads(process.stdout.splitlines()[-1])
                            self.assertEqual(verdict["gate"], "compliance")
                            self.assertEqual(verdict["failures"], 1)
                            self.assertEqual(verdict["repos"], [])
                            self.assertIn(
                                f"malformed: {label}.cmd must be a non-empty command list without NUL bytes",
                                verdict["infrastructure"])
                            self.assertNotIn("synthetic", process.stdout + process.stderr)

    def test_valid_literal_command_arguments_reach_real_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments = ["alpha=beta", "semi;colon", "two words", "quote'\"value"]
            script = ("import json, sys; from pathlib import Path; "
                      "Path('arguments.json').write_text(json.dumps(sys.argv[1:]))")
            cmd = [sys.executable, "-c", script, *arguments]
            (root / "AGENTS.md").write_text("## Test commands\n" + " ".join(cmd))
            (root / "README.md").write_text("See AGENTS.md")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"repos": [{
                "name": "valid", "status": "active", "path": str(root),
                "unit": {"cmd": cmd}
            }]}))
            result, stdout = self._run(["--repo", "valid"], manifest)
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.splitlines()[-1])["repos"][0]["verdict"], "PASS")
            self.assertEqual(json.loads((root / "arguments.json").read_text()), arguments)

    def test_valid_env_values_and_override_reach_real_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "observed.json"
            script = ("import json, os; from pathlib import Path; "
                      "Path('observed.json').write_text(json.dumps({"
                      "k: os.environ[k] for k in ('EQUALS', 'EMPTY', 'OVERRIDE')}))")
            cmd = [sys.executable, "-c", script]
            (root / "AGENTS.md").write_text("## Test commands\n" + " ".join(cmd))
            (root / "README.md").write_text("See AGENTS.md")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"repos": [{
                "name": "selected", "status": "active", "path": str(root),
                "unit": {"cmd": cmd, "env": {"EQUALS": "alpha=beta", "EMPTY": "",
                                               "OVERRIDE": "/synthetic/explicit"}}
            }]}))
            with mock.patch.dict(compliance.os.environ, {"OVERRIDE": "/synthetic/inherited"}):
                result, stdout = self._run(["--repo", "selected"], manifest)
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.splitlines()[-1])["repos"][0]["verdict"], "PASS")
            self.assertEqual(json.loads(output.read_text()), {
                "EQUALS": str(root.resolve() / "alpha=beta"), "EMPTY": str(root.resolve()),
                "OVERRIDE": "/synthetic/explicit"})

    def test_symlink_loop_root_refuses_with_json_before_any_commands(self):
        cli = Path(compliance.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            loop = home / "loop"
            loop.symlink_to("loop")
            marker = root / "executed"
            cmd = [sys.executable, "-c",
                   "from pathlib import Path; Path('executed').touch()"]
            (root / "AGENTS.md").write_text("## Test commands\n" + " ".join(cmd))
            (root / "README.md").write_text("See AGENTS.md")
            env = {"QA_KIT_DIR": str(root), "HOME": str(home), "PATH": os.defpath}
            for mode in ("manifest-all", "manifest-selected", "override"):
                with self.subTest(mode=mode):
                    marker.unlink(missing_ok=True)
                    (root / "manifest.json").write_text(json.dumps({"repos": [
                        {"name": "valid", "status": "active", "path": str(root),
                         "unit": {"cmd": cmd}},
                        {"name": "blocked", "status": "unit-only", "path": "~/loop",
                         "unit": {"cmd": cmd}}
                    ]}))
                    args = [] if mode == "manifest-all" else ["--repo", "blocked"]
                    if mode == "override":
                        args += ["--root", str(loop)]
                    process = subprocess.run([sys.executable, "-B", str(cli), *args],
                                             env=env, capture_output=True, text=True,
                                             timeout=10)
                    self.assertEqual(process.returncode, 1)
                    self.assertNotIn("Traceback", process.stderr)
                    self.assertFalse(marker.exists(), "commands ran before root refusal")
                    verdict = json.loads(process.stdout.splitlines()[-1])
                    self.assertEqual(verdict["gate"], "compliance")
                    self.assertEqual(verdict["failures"], 1)
                    self.assertEqual(verdict["repos"], [])
                    self.assertEqual(verdict["infrastructure"],
                                     ["blocked: cannot resolve repo root"])
                    self.assertNotIn(str(home), process.stdout + process.stderr)

    def test_valid_tilde_symlink_root_reaches_real_command(self):
        cli = Path(compliance.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            target = home / "target"
            target.mkdir()
            (home / "alias").symlink_to("target", target_is_directory=True)
            marker = target / "executed"
            cmd = [sys.executable, "-c",
                   "from pathlib import Path; Path('executed').touch()"]
            (target / "AGENTS.md").write_text("## Test commands\n" + " ".join(cmd))
            (target / "README.md").write_text("See AGENTS.md")
            (root / "manifest.json").write_text(json.dumps({"repos": [{
                "name": "valid", "status": "active", "path": "~/alias",
                "unit": {"cmd": cmd}
            }]}))
            for args in ([], ["--repo", "valid", "--root", "~/alias"]):
                with self.subTest(args=args):
                    marker.unlink(missing_ok=True)
                    process = subprocess.run(
                        [sys.executable, "-B", str(cli), *args],
                        env={"QA_KIT_DIR": str(root), "HOME": str(home), "PATH": os.defpath},
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertTrue(marker.exists())
                    verdict = json.loads(process.stdout.splitlines()[-1])
                    self.assertEqual(verdict["failures"], 0)
                    self.assertEqual(verdict["repos"][0]["verdict"], "PASS")

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
        self.assertIn("ref: ${{ inputs.repo == 'agency' && 'v0.7.0' || inputs.repo == 'bean-counter' && 'v0.6.1' || 'v0.6.6' }}", workflow)
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
        for doc in ("AGENTS.md", "README-REFERENCE.md"):
            text = (root / doc).read_text()
            self.assertIn("v0.6.6", text, f"{doc} must document qa-kit v0.6.6 pin")
            self.assertNotIn("v0.4.3", text, f"{doc} must not reference the retired qa-kit pin")
            self.assertIn("v0.4.4", text, f"{doc} must keep the immutable gate-kit CLI pin")

    def test_beanfit_fixture_pin_documented_accurately_in_repo_docs(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/compliance.yml").read_text()
        beanfit = workflow.split("repository: stevekkall-beansgc/beanfit", 1)[1]
        self.assertIn("ref: v0.4.0", beanfit.split("path: beanfit", 1)[0])
        for doc in ("AGENTS.md", "README-REFERENCE.md"):
            text = (root / doc).read_text()
            self.assertIn("v0.4.0", text, f"{doc} must document beanfit fixture v0.4.0 pin")
            self.assertNotIn("v0.1.1", text, f"{doc} must not reference the retired fixture pin")

    def test_readme_quickstart_and_release_pins_match_checkout(self):
        root = Path(__file__).resolve().parents[1]
        entry = (root / "README.md").read_text()
        self.assertIn("README-REFERENCE.md#6-release-pins-in-v0424", entry)
        self.assertIn("python3 examples/synthetic_quickstart.py", entry)
        self.assertIn("they execute locally with the user's", entry)
        readme = entry + "\n" + (root / "README-REFERENCE.md").read_text()
        workflow = (root / ".github/workflows/compliance.yml").read_text()

        self.assertIn("python3 examples/synthetic_quickstart.py", readme)
        for heading in (
                "## 1. The problem",
                "## 2. Run the synthetic demo",
                "## 3. Follow the implementation",
                "## 4. Failure-mode proof",
                "## 5. Supported scope",
                "## 6. Release pins in v0.4.24"):
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
            if repository == "stevekkall-beansgc/qa-kit":
                self.assertIn("ref: ${{ inputs.repo == 'agency' && 'v0.7.0' || inputs.repo == 'bean-counter' && 'v0.6.1' || 'v0.6.6' }}", checkout)
                for ref in ("v0.7.0", "v0.6.1", "v0.6.6"):
                    self.assertIn(f"`{ref}`", readme)
            else:
                self.assertIn(f"`{match.group(1)}`", readme)
        self.assertIn("The earlier `v0.4.20` workflow used QA manifest `v0.6.1`", readme)
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
        self.assertIn("[SECURITY.md](SECURITY.md)", readme)
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
