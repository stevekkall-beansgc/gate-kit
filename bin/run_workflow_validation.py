#!/usr/bin/env python3
"""Run the fixed reviewed local/CI pair; QA remains the sole task executor."""
import json
import hashlib
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parents[1]
RUNTIME_COMMIT = "6cdd0a5f3bad63b61972ee84943d824e1f98c944"
EXECUTOR_COMMIT = "cf3cebee5a4f975260c330aa585b7cd3d5b63a79"
ROW_FIELDS = {"github_repository", "variant", "selection", "fixtures", "bundle_sha256",
              "registry_sha256", "authorization_sha256", "contract_sha256"}


def verify_workflow_source(root, expected_head):
    """Verify own checkout without importing any sibling/control module."""
    root = Path(root).absolute()
    if (not re.fullmatch(r"[0-9a-f]{40}", expected_head or "")
            or ".." in root.parts or any(path.is_symlink() for path in (root, *root.parents))):
        raise ValueError("invalid immutable workflow source")
    admin = root / ".git"
    if admin.is_symlink() or not admin.is_dir():
        raise ValueError("workflow must have its own regular Git administration")
    index = admin / "index"
    if index.is_symlink() or not index.is_file():
        raise ValueError("workflow index must be a regular file")
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "TZ"}}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")

    def git(*args):
        result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                                 "-C", str(root), *args], env=env, capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError("cannot verify immutable workflow source")
        return result.stdout

    if (Path(os.fsdecode(git("rev-parse", "--show-toplevel")).strip()).resolve() != root.resolve()
            or git("rev-parse", "HEAD").decode().strip() != expected_head
            or git("status", "--porcelain=v1", "--untracked-files=all")
            or git("diff-index", "--cached", "--name-only", expected_head)):
        raise ValueError("workflow checkout must be clean at its pinned commit")
    if any(record and not record.startswith(b"H ")
           for record in git("ls-files", "-v", "-z").split(b"\0")):
        raise ValueError("hidden workflow index entries are forbidden")
    for record in git("ls-tree", "-r", "-z", expected_head).split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, blob = metadata.split()
        path = root
        relative = Path(os.fsdecode(name))
        if relative.is_absolute() or any(part in ("..", ".git") for part in relative.parts):
            raise ValueError("ambiguous tracked workflow source")
        for part in relative.parts:
            path /= part
            if path.is_symlink():
                raise ValueError("symlink in tracked workflow source")
        if (kind != b"blob" or mode not in (b"100644", b"100755") or not path.is_file()
                or bool(path.stat().st_mode & 0o111) != (mode == b"100755")):
            raise ValueError("unsupported tracked workflow source")
        data = path.read_bytes()
        physical = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest().encode()
        if physical != blob:
            raise ValueError("physical workflow source differs from its commit")
    return root


def run_pair(workspace, runner_temp, environ=None, workflow_root=HERE):
    env = os.environ if environ is None else environ
    workspace, runner_temp = [Path(value).resolve() for value in (workspace, runner_temp)]
    workflow_root = Path(workflow_root).absolute()
    verify_workflow_source(workflow_root, env.get("GATE_JOB_WORKFLOW_SHA"))
    bootstrap = runpy.run_path(str(workflow_root / "bin/validation_adapter.py"))
    policy_path = workflow_root / ".github/validation-policy.json"
    policy = json.loads(policy_path.read_bytes(), object_pairs_hook=bootstrap["_unique_object"])
    if (not isinstance(policy, dict) or set(policy) != {"schema", "controls_commit", "adapter_commit", "executor_commit", "repos"}
            or policy["schema"] != "gate-kit.validation-workflow-policy/v1"
            or policy["adapter_commit"] != RUNTIME_COMMIT or policy["executor_commit"] != EXECUTOR_COMMIT
            or not isinstance(policy["repos"], dict)):
        raise ValueError("workflow source has an unsupported fixed policy")
    repo = env.get("GATE_REPO")
    row = policy["repos"].get(repo)
    if not isinstance(row, dict) or set(row) != ROW_FIELDS:
        raise ValueError("repository has no complete fixed workflow policy")
    evidence = runpy.run_path(str(workflow_root / "bin/assemble_evidence.py"))
    evidence["workflow_identity"](env, row, env.get("GATE_EXPECTED_SHA"))
    runtime_root, qa_root, controls_root, caller = [workspace / name for name in
                                                   ("gate-runtime", "qa-executor", "qa-controls", "caller")]
    bootstrap["verify_checkout"](runtime_root, RUNTIME_COMMIT)
    runtime = runpy.run_path(str(runtime_root / "bin/validation_adapter.py"))
    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_bytes(), object_pairs_hook=bootstrap["_unique_object"])
    runtime["validate_ci_context"](env, event, row["github_repository"], env.get("GATE_EXPECTED_SHA"), row["variant"])
    if repo != runtime["MAC_ROUTES"].get(row["github_repository"], {}).get("repo"):
        raise ValueError("workflow alias is outside the fixed route")
    # Every root/fixture/control is checked again by the exact Gate bridge.
    directory = runner_temp / "gate-validation-evidence"
    directory.mkdir(mode=0o700)
    allowed = {"PATH", "LANG", "LC_ALL", "TZ", "GITHUB_EVENT_PATH", "GITHUB_ACTIONS", "GITHUB_RUN_ID",
               "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_WORKFLOW_REF", "GITHUB_WORKFLOW_SHA",
               "RUNNER_ENVIRONMENT", "RUNNER_OS", "RUNNER_ARCH", "RUNNER_NAME"}
    child_env = {key: value for key, value in env.items() if key in allowed or key.startswith("GATE_")}
    command = [sys.executable, "-I", str(runtime_root / "bin/validation_adapter.py"),
               "--root", str(caller), "--repo", repo, "--qa-root", str(qa_root),
               "--controls-root", str(controls_root), "--controls-commit", policy["controls_commit"],
               "--registry", "validation/registry.json", "--bundle", f"validation/bundles/{repo}.json",
               "--authorization", f"validation/authorizations/{repo}.json", "--expected-bundle", row["bundle_sha256"],
               "--variant", row["variant"], "--expected-head", env["GATE_EXPECTED_SHA"],
               "--selection", row["selection"]]
    if set(row["fixtures"]) - {"beanfit"}:
        raise ValueError("workflow has an unsupported fixture route")
    if row["fixtures"]:
        command += ["--fixture", "beanfit=" + str(workspace / "beanfit-fixture")]
    envelopes = {}
    with tempfile.TemporaryDirectory(prefix="gate-shared-results-", dir=runner_temp) as temporary:
        for context in ("local", "ci"):
            invocation = command + ["--context", context, "--output", str(Path(temporary) / (context + ".json"))]
            process, cancelled = runtime["invoke_executor"](invocation, child_env, workspace,
                                                             timeout=2000, cleanup_timeout=35)
            if cancelled or process.returncode != 0:
                raise ValueError("required " + context + " execution did not pass")
            value = json.loads(process.stdout.splitlines()[-1], object_pairs_hook=bootstrap["_unique_object"])
            envelopes[context] = value
            with (directory / (context + "-envelope.json")).open("x") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.write("\n")
    parity = runpy.run_path(str(runtime_root / "bin/check_parity.py"))["check_parity"](
        envelopes["local"], envelopes["ci"], repo=repo, head=env["GATE_EXPECTED_SHA"], bundle=row["bundle_sha256"])
    with (directory / "parity.json").open("x") as stream:
        json.dump(parity, stream, sort_keys=True)
        stream.write("\n")
    evidence["assemble"](directory, policy_path, repo, runtime_root, env)
    return directory


if __name__ == "__main__":
    try:
        result = run_pair(os.environ["GITHUB_WORKSPACE"], os.environ["RUNNER_TEMP"])
        print(json.dumps({"workflow_validation": "pass", "evidence_directory": str(result),
                          "github_check_verified": False}))
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        print(json.dumps({"workflow_validation": "blocked", "error": str(exc), "github_check_verified": False}))
        raise SystemExit(1)
