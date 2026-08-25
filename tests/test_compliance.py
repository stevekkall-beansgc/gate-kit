"""Unit tests for gate-kit compliance.py — pure logic only, no network."""
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
