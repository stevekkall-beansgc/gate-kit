#!/usr/bin/env python3
"""synthetic_quickstart.py — drive the real compliance CLI, no workspace needed.

Builds a self-contained synthetic repo + qa-kit manifest in a temp directory
and runs the actual bin/compliance.py entrypoint against it as a subprocess.
Works on any machine with Python 3 and a shell: no BeanLabs workspace,
private repos, credentials, or network access required.

Scenarios demonstrated (the real gate's contract):
  1. healthy synthetic repo        -> green JSON verdict, exit 0
  2. broken AGENTS.md              -> FAIL verdict,   exit 1
  3. missing qa-kit manifest       -> fail-closed infrastructure failure

Usage:
    python3 examples/synthetic_quickstart.py

Exit code 0 only when every scenario does what the real gate must. The final
JSON verdict of each run is stdout's last line; the reusable workflow uses
the CLI exit status as its gate result.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_NAME = "synthetic"
UNIT_CMD = ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
AGENTS_GOOD = (
    "## Test commands\n"
    "Synthetic unit: `python3 -m unittest discover -s tests -v`\n"
)
AGENTS_BROKEN = "# synthetic\n\nThis room runs no compliance gate.\n"
README_TEXT = "# synthetic\n\nSynthetic repo for the quickstart. See AGENTS.md.\n"
SYNTH_TEST = (
    "import unittest\n\n"
    "class TestSyntheticSample(unittest.TestCase):\n"
    "    def test_smoke(self):\n"
    "        self.assertTrue(True)\n\n"
    "if __name__ == '__main__':\n"
    "    unittest.main()\n"
)


def build_synthetic_repo(root, broken=False):
    """Write a tiny repo the gate can check, optionally with broken docs."""
    root = Path(root)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text(AGENTS_BROKEN if broken else AGENTS_GOOD)
    (root / "README.md").write_text(README_TEXT)
    (root / "tests" / "test_synthetic.py").write_text(SYNTH_TEST)
    return root


def write_manifest(qa_dir, repo_root, name=REPO_NAME, unit_cmd=UNIT_CMD):
    """Write a minimal qa-kit manifest declaring one active synthetic repo."""
    qa_dir = Path(qa_dir)
    qa_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"repos": [{
        "name": name,
        "status": "active",
        "path": str(Path(repo_root).resolve()),
        "unit": {"cmd": list(unit_cmd)},
    }]}
    (qa_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return qa_dir / "manifest.json"


def run_gate(bin_py, qa_dir, repo_root, *extra_args, name=REPO_NAME):
    """Run the real bin/compliance.py as a subprocess against synthetic inputs."""
    env = dict(os.environ)
    env["QA_KIT_DIR"] = str(qa_dir)
    cmd = [sys.executable, str(bin_py), "--repo", name,
           "--root", str(repo_root), *extra_args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True,
                          timeout=180)


def last_verdict(output):
    """Parse the machine-readable JSON verdict on stdout's last line."""
    for line in reversed(output.splitlines()):
        if line.strip():
            return json.loads(line)
    raise ValueError("gate produced no output lines")


def _mark(name, problems, ok, extra=""):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name} {extra}".rstrip())
    if not ok:
        problems.append(f"{name}: expected {extra or 'green outcome'}")


def _scenario_gate(bin_py, qa_dir, repo_root, expect_pass):
    proc = run_gate(bin_py, qa_dir, repo_root)
    print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if not proc.stdout.strip():
        return False, {}
    verdict = last_verdict(proc.stdout)
    reported = verdict["repos"][0]["verdict"] if verdict.get("repos") else None
    ok = ((proc.returncode == 0 and verdict["failures"] == 0
           and reported == "PASS")
          if expect_pass else
          (proc.returncode == 1 and verdict["failures"] >= 1
           and reported == "FAIL"))
    return ok, verdict


def demo():
    problems = []
    bin_py = Path(__file__).resolve().parents[1] / "bin" / "compliance.py"
    if not bin_py.is_file():
        print(f"missing entrypoint: {bin_py}")
        return 1

    with tempfile.TemporaryDirectory(prefix="gate-kit-quickstart-") as tmp:
        base = Path(tmp)

        print("== scenario 1: healthy synthetic repo -> green verdict")
        repo = base / "repo"
        build_synthetic_repo(repo)
        write_manifest(base / "qa-kit", repo)
        ok, verdict = _scenario_gate(bin_py, base / "qa-kit", repo, True)
        _mark("scenario 1 (pass case)", problems, ok,
              extra="exit 0 and a green JSON verdict" if not ok else "")
        if ok:
            print("    green JSON verdict: "
                  f"failures={verdict['failures']}, "
                  f"verdict={verdict['repos'][0]['verdict']}")

        print("== scenario 2: broken AGENTS.md -> FAIL verdict")
        build_synthetic_repo(repo, broken=True)
        ok, verdict = _scenario_gate(bin_py, base / "qa-kit", repo, False)
        _mark("scenario 2 (fail case)", problems, ok,
              extra="exit 1 and a FAIL verdict" if not ok else "")
        if ok:
            print("    fail-closed JSON verdict: "
                  f"failures={verdict['failures']}, "
                  f"verdict={verdict['repos'][0]['verdict']}")

        print("== scenario 3: missing qa-kit manifest -> infrastructure failure")
        empty_qa = base / "qa-missing"
        empty_qa.mkdir()
        proc = run_gate(bin_py, empty_qa, repo)
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
        ok = (proc.returncode == 1
              and bool(proc.stdout.strip())
              and last_verdict(proc.stdout).get("failures") == 1
              and last_verdict(proc.stdout).get("repos") == []
              and "infrastructure" in last_verdict(proc.stdout))
        _mark("scenario 3 (infrastructure fail-closed)", problems, ok,
              extra="exit 1 and an infrastructure failure" if not ok else "")
        if ok:
            print("    fail-closed JSON verdict: infrastructure failure, exit 1")

        print("== summary")
        if problems:
            print("quickstart FAILED:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("All scenarios behaved as the real gate must:")
        print("  - PASS case: green JSON verdict on stdout's last line")
        print("  - FAIL case: broken docs produce a FAIL verdict and exit 1")
        print("  - fail-closed: a missing manifest is a hard failure, never a silent pass")
        return 0


if __name__ == "__main__":
    sys.exit(demo())
