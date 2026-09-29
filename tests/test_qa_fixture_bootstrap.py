"""Offline qualification of owned exact public-QA fixture preparation."""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qa_fixture_bootstrap", ROOT / "setup/qa-validation/bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class TestPublicFixtureBootstrap(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / ".qa-fixtures/qa-kit"
        (self.fixture / "bin").mkdir(parents=True)
        (self.fixture / "bin/validation.py").write_text("# synthetic reviewed executor\n")
        bootstrap.git(self.fixture, "init", "-q")
        bootstrap.git(self.fixture, "add", ".")
        bootstrap.git(self.fixture, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                      "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic source")
        self.pin = {"schema": "gate-kit.qa-executor-fixture/v1", "repository": bootstrap.PUBLIC_REPOSITORY,
                    "commit": bootstrap.git(self.fixture, "rev-parse", "HEAD"),
                    "executor_sha256": hashlib.sha256((self.fixture / "bin/validation.py").read_bytes()).hexdigest()}
        (self.root / "setup/qa-validation").mkdir(parents=True)
        (self.root / "setup/qa-validation/fixture.json").write_text(json.dumps(self.pin))

    def test_existing_exact_fixture_is_verified_without_replacing_it(self):
        before = (self.fixture / "bin/validation.py").read_bytes()
        self.assertEqual(bootstrap.bootstrap(self.root), self.fixture.resolve())
        self.assertEqual((self.fixture / "bin/validation.py").read_bytes(), before)

    def test_hidden_source_change_is_refused_without_reset(self):
        bootstrap.git(self.fixture, "update-index", "--assume-unchanged", "bin/validation.py")
        (self.fixture / "bin/validation.py").write_text("unreviewed replacement\n")
        self.assertEqual(bootstrap.git(self.fixture, "status", "--porcelain"), "")
        with self.assertRaises(ValueError):
            bootstrap.bootstrap(self.root)
        self.assertEqual((self.fixture / "bin/validation.py").read_text(), "unreviewed replacement\n")

    def test_wrong_commit_or_executor_digest_is_refused(self):
        for key, value in (("commit", "a" * 40), ("executor_sha256", "a" * 64)):
            pin = {**self.pin, key: value}
            with self.assertRaises(ValueError):
                bootstrap.verify(self.fixture, pin)

    def test_symlink_parent_is_refused(self):
        other = self.root / "other"
        other.mkdir()
        (other / ".qa-fixtures").symlink_to(self.root / ".qa-fixtures")
        (other / "setup/qa-validation").mkdir(parents=True)
        (other / "setup/qa-validation/fixture.json").write_text(json.dumps(self.pin))
        with self.assertRaises(ValueError):
            bootstrap.bootstrap(other)

    def test_published_pin_and_owned_e2e_have_no_missing_fixture_fallback(self):
        pin = bootstrap.load_pin(ROOT)
        self.assertEqual(pin["commit"], "cf3cebee5a4f975260c330aa585b7cd3d5b63a79")
        command = (ROOT / "scripts/test_validation_e2e.sh").read_text()
        self.assertIn("exec python3 -B -m unittest discover -s integration -v", command)
        self.assertNotIn("|| true", command)
        result = subprocess.run(["bash", "-n", str(ROOT / "setup/qa-validation/bootstrap.sh"),
                                 str(ROOT / "scripts/test_validation_e2e.sh")], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
