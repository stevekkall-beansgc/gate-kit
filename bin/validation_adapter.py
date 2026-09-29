#!/usr/bin/env python3
"""Gate authority boundary for the QA-owned composable validation executor.

Enrolled CI supports hosted push/PR and two fixed, main-push Mac pilot routes.
Execution context is not proof of a successful GitHub check. Existing protected
canonical profiles remain on their separately qualified legacy checker.
"""
import argparse
import hashlib
import json
import os
import re
import runpy
import signal
import subprocess
import sys
from pathlib import Path

CONTRACT_VERSION = "1.0"
HERE = Path(__file__).resolve().parents[1]

# This is a closed control-source policy, never a caller-selected label. The
# inactive adapter cannot enroll or register these runners on its own.
MAC_ROUTES = {
    "stevekkall-beansgc/legume-labs": {
        "repo": "bean-labs",
        "runner_name": "beans-macbook-legume-labs-validation",
        "variant": "macos-arm64-py312"},
    "stevekkall-beansgc/beanfit-app": {
        "repo": "beanfit-app",
        "runner_name": "beans-macbook-beanfit-app-validation",
        "variant": "macos-arm64-node22-py312"},
}


class AdapterCancelled(Exception):
    """Avoid InterruptedError, which selectors retry as an interrupted syscall."""


def _git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    result = subprocess.run(["git", "-C", str(root), *args], env=env,
                            capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("cannot verify control checkout")
    return result.stdout


def verify_checkout(root, expected_head):
    """Bootstrap source verification before executing any shared control code."""
    root = Path(root).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head or ""):
        raise ValueError("invalid immutable control commit")
    if (Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root
            or _git(root, "rev-parse", "HEAD").decode().strip() != expected_head
            or _git(root, "status", "--porcelain=v1", "--untracked-files=all")):
        raise ValueError("control checkout must be clean at its pinned commit")
    for record in _git(root, "ls-files", "-v", "-z").split(b"\0"):
        if record and not record.startswith(b"H "):
            raise ValueError("hidden control index entries are forbidden")
    for record in _git(root, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        path = root / os.fsdecode(name)
        if (kind != b"blob" or mode not in (b"100644", b"100755")
                or path.is_symlink() or not path.is_file()
                or bool(path.stat().st_mode & 0o111) != (mode == b"100755")
                or _git(root, "hash-object", "--no-filters", "--", str(path)).strip() != oid):
            raise ValueError("physical control source differs from its Git commit")
    return root


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate control field")
        value[key] = item
    return value


def read_trusted_json(path, trusted_root, expected_digest):
    """Load only exact digest-pinned control bytes inside their trusted root."""
    path, root = Path(path).absolute(), Path(trusted_root).absolute()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest or ""):
        raise ValueError("invalid expected control digest")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("control outside trusted root") from exc
    if any(part in ("..", ".git") for part in relative.parts) or root.is_symlink() or not root.is_dir():
        raise ValueError("ambiguous trusted control path")
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise ValueError("symlink in trusted control path")
    # Digest equality alone cannot attest that an ignored file came from the
    # trusted Git commit. The root is physically verified before this loader.
    _git(root, "ls-files", "--error-unmatch", "--", str(relative))
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("trusted control digest mismatch")
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("unreadable trusted control") from exc
    if not isinstance(value, dict):
        raise ValueError("trusted control must be an object")
    return value


def validate_ci_context(environ, event, repository, expected_head, variant=None):
    """Validate runner/event identity before allowing an enrolled CI task."""
    if (not re.fullmatch(r"[0-9a-f]{40}", expected_head or "")
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or "")
            or not isinstance(event, dict)):
        raise ValueError("invalid enrolled source identity")
    runner = environ.get("RUNNER_ENVIRONMENT")
    if (environ.get("GITHUB_ACTIONS") != "true"
            or not re.fullmatch(r"[1-9][0-9]*", environ.get("GITHUB_RUN_ID", ""))
            or not re.fullmatch(r"[1-9][0-9]*", environ.get("GITHUB_RUN_ATTEMPT", ""))):
        raise ValueError("enrolled CI requires Actions execution metadata")
    event_repository = event.get("repository")
    if (not isinstance(event_repository, dict)
            or environ.get("GATE_REPOSITORY") != repository
            or environ.get("GATE_EVENT_REPOSITORY") != repository
            or environ.get("GATE_EXPECTED_SHA") != expected_head
            or event_repository.get("full_name") != repository):
        raise ValueError("enrolled repository or source mismatch")

    name, ref = environ.get("GATE_EVENT_NAME"), environ.get("GATE_REF", "")
    if runner == "self-hosted":
        route = MAC_ROUTES.get(repository)
        if (route is None or name != "push" or ref != "refs/heads/main"
                or environ.get("RUNNER_NAME") != route["runner_name"]
                or environ.get("RUNNER_OS") != "macOS" or environ.get("RUNNER_ARCH") != "ARM64"
                or variant != route["variant"]):
            raise ValueError("self-hosted CI is outside the qualified pilot route")
    elif runner != "github-hosted":
        raise ValueError("unsupported CI runner profile")
    if name == "push":
        if (not ref.startswith("refs/heads/") or len(ref) <= len("refs/heads/")
                or event.get("ref") != ref or event.get("after") != expected_head
                or environ.get("GATE_PUSH_AFTER") != expected_head):
            raise ValueError("untrusted enrolled push context")
    elif name == "pull_request":
        pr = event.get("pull_request")
        number = event.get("number")
        if (not isinstance(pr, dict) or type(number) is not int or number <= 0
                or ref != f"refs/pull/{number}/merge"
                or not isinstance(pr.get("head"), dict) or pr["head"].get("sha") != expected_head
                or not isinstance(pr.get("base"), dict)
                or not isinstance(pr["base"].get("repo"), dict)
                or pr["base"]["repo"].get("full_name") != repository):
            raise ValueError("untrusted enrolled pull-request context")
    else:
        raise ValueError("event not authorized for enrolled CI")
    return {"event": name, "repository": repository, "ref": ref,
            "expected_head": expected_head, "run_id": environ["GITHUB_RUN_ID"],
            "run_attempt": environ["GITHUB_RUN_ATTEMPT"],
            "runner_environment": runner, "runner_name": environ.get("RUNNER_NAME"),
            "runner_os": environ.get("RUNNER_OS"), "runner_arch": environ.get("RUNNER_ARCH"),
            "github_check_verified": False}


def invoke_executor(command, env, cwd, *, timeout=1800, cleanup_timeout=15):
    """Bound wrapper lifetime; QA still owns task deadlines and child cleanup."""
    process = None
    cancelled = False
    def forward(signum, frame):
        raise AdapterCancelled("adapter execution cancelled")
    old = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in old:
        signal.signal(sig, forward)
    try:
        process = subprocess.Popen(command, env=env, cwd=cwd, start_new_session=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except AdapterCancelled:
            cancelled = True
        except subprocess.TimeoutExpired as exc:
            raise ValueError("shared executor exceeded the adapter deadline") from exc
    finally:
        # Repeated cancellation must not interrupt bounded executor cleanup.
        for sig in old:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    stdout, stderr = process.communicate(timeout=cleanup_timeout)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    stdout, stderr = process.communicate(timeout=cleanup_timeout)
            elif process is not None and cancelled:
                stdout, stderr = process.communicate(timeout=cleanup_timeout)
        finally:
            for sig, handler in old.items():
                signal.signal(sig, handler)
    if process is None:
        raise ValueError("shared executor did not start")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), cancelled


def executor_environment(environ):
    """The shared interpreter needs runtime discovery, not operator authority."""
    return {key: value for key, value in environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "TZ"}}


def legacy_docs(root, repo, qa_root, adapter_root):
    """Retain the existing docs check until central equivalent tasks qualify."""
    manifest = json.loads((Path(qa_root) / "manifest.json").read_bytes(),
                          object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("repos"), list):
        raise ValueError("pinned manifest is missing its documentation contract")
    rows = [row for row in manifest["repos"] if isinstance(row, dict) and row.get("name") == repo]
    if len(rows) != 1 or rows[0].get("status") not in ("active", "unit-only"):
        raise ValueError("enrolled repo lacks a unique active documentation contract")
    unit = rows[0].get("unit")
    command = unit.get("cmd") if isinstance(unit, dict) else None
    if (not isinstance(command, list) or not command
            or any(not isinstance(arg, str) or not arg for arg in command)):
        raise ValueError("pinned documentation entrypoint is malformed")
    namespace = runpy.run_path(str(Path(adapter_root) / "bin/compliance.py"),
                              run_name="gate_legacy_docs")
    problems = namespace["docs_check"](Path(root), command)
    return {"name": "docs", "ok": not problems, "detail": "; ".join(problems),
            "scope": "existing README/AGENTS and manifest unit-command contract"}


def run_enrolled(*, root, repo, qa_root, controls_root, controls_commit,
                 registry, bundle, expected_bundle, authorization, variant,
                 expected_head, context, output, fixtures=(), selection=None,
                 environ=None, event=None, adapter_root=HERE):
    """Invoke the exact shared executor; never implement task semantics here."""
    if context not in ("local", "ci"):
        raise ValueError("Gate supports local comparison or CI, not release authority")
    if repo in ("agents", "beanmind"):
        raise ValueError("protected legacy profiles are not enrolled by this adapter")
    controls_root = verify_checkout(controls_root, controls_commit)
    bundle_path = controls_root / bundle
    control = read_trusted_json(bundle_path, controls_root, expected_bundle)
    if control.get("schema") != "qa-kit.validation-bundle/v1":
        raise ValueError("unsupported bundle schema")
    registry_path, auth_path = controls_root / registry, controls_root / authorization
    central = read_trusted_json(registry_path, controls_root, control.get("registry_sha256"))
    read_trusted_json(auth_path, controls_root, control.get("authorization_sha256"))
    if (central.get("schema") != "qa-kit.validation-registry/v1"
            or not isinstance(central.get("repos"), dict) or repo not in central["repos"]):
        raise ValueError("explicit parity execution requires a centrally enrolled repository")
    policy = central["repos"][repo]
    if not isinstance(policy, dict):
        raise ValueError("malformed explicit enrollment")
    required = policy.get("required_selections")
    if not isinstance(required, dict) or not isinstance(required.get("ci"), str):
        raise ValueError("central required CI selection is missing")
    selected = selection or required["ci"]
    if context == "ci" and selected != required["ci"]:
        raise ValueError("caller cannot reduce required CI selection")
    if not isinstance(policy.get("selections"), dict) or selected not in policy["selections"]:
        raise ValueError("required selection is not registered")
    required_cells = policy["selections"][selected]
    if (not isinstance(required_cells, list) or not required_cells
            or any(not isinstance(cell, str) or cell.count("@") != 1 for cell in required_cells)):
        raise ValueError("malformed required selection")
    ci_context = None
    if context == "ci":
        authority = os.environ if environ is None else environ
        if (authority.get("RUNNER_ENVIRONMENT") == "self-hosted"
                and repo != MAC_ROUTES.get(policy.get("github_repository"), {}).get("repo")):
            raise ValueError("Mac pilot alias differs from the reviewed repository")
        ci_context = validate_ci_context(authority, event,
                                         policy.get("github_repository"), expected_head, variant)
    qa_root = verify_checkout(qa_root, control.get("qa_commit"))
    if not isinstance(control.get("adapters"), dict):
        raise ValueError("trusted adapter identities are missing")
    # Local comparisons use the same pinned Gate implementation as CI.
    adapter_root = verify_checkout(adapter_root, control["adapters"].get("ci"))
    verify_checkout(root, expected_head)
    docs = legacy_docs(root, repo, qa_root, adapter_root)
    executor = qa_root / "bin/validation.py"
    if executor.is_symlink() or not executor.is_file():
        raise ValueError("pinned shared executor is missing")
    output = Path(output).absolute()
    if output.exists() or any(output.resolve().is_relative_to(Path(path).resolve())
                              for path in (root, qa_root, controls_root, adapter_root)):
        raise ValueError("result must be a new artifact outside source checkouts")
    command = [sys.executable, "-I", str(executor), "--root", str(root), "--repo", repo,
               "--registry", str(registry_path), "--bundle", str(bundle_path),
               "--expected-bundle", expected_bundle, "--authorization", str(auth_path),
               "--selection", selected, "--variant", variant,
               "--expected-head", expected_head, "--context", context,
               "--adapter-root", str(adapter_root), "--output", str(output)]
    for fixture in fixtures:
        command += ["--fixture", fixture]
    # The isolated Python interpreter loads only the pinned executor's code;
    # common task execution owns its separately sanitized environment.
    child_env = executor_environment(os.environ)
    process, cancelled = invoke_executor(command, child_env, qa_root)
    if not output.is_file() or output.is_symlink():
        raise ValueError("shared executor did not produce a result artifact")
    result = json.loads(output.read_bytes(), object_pairs_hook=_unique_object)
    if (not isinstance(result, dict) or result.get("schema") != "qa-kit.validation-result/v1"
            or result.get("repo") != repo or result.get("selection") != selected
            or result.get("variant") != variant or result.get("context") != context
            or result.get("bundle_sha256") != expected_bundle
            or result.get("github_repository") != policy.get("github_repository")
            or result.get("required") != required_cells):
        raise ValueError("shared result identity mismatch")
    verify_checkout(controls_root, controls_commit)
    verify_checkout(qa_root, control["qa_commit"])
    verify_checkout(adapter_root, control["adapters"]["ci"])
    # A passing variant cell cannot turn incomplete required coverage green.
    passed = not cancelled and process.returncode == 0 and result.get("status") == "pass"
    complete = result.get("selection_complete") is True
    if passed:
        candidate = result.get("candidate")
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("before"), dict)
                or candidate["before"].get("head") != expected_head
                or candidate["before"].get("dirty") is not False
                or candidate.get("after") != candidate["before"]):
            raise ValueError("passing result lacks exact candidate proof")
        cells = [cell for cell in required_cells if cell.split("@")[1] == variant]
        remaining = [cell for cell in required_cells if cell not in cells]
        if (result.get("selected") != cells or result.get("remaining_required") != remaining
                or complete != (not remaining)):
            raise ValueError("passing result coverage mismatch")
        tasks = result.get("tasks")
        if (not isinstance(tasks, list) or not tasks
                or any(not isinstance(task, dict) or task.get("status") != "pass"
                       or task.get("variant") != variant for task in tasks)
                or any(not any(task.get("task") == cell.split("@")[0] for task in tasks)
                       for cell in cells)):
            raise ValueError("passing result lacks required task outcomes")
    accepted = passed and complete and docs["ok"]
    return {"gate": "compliance", "adapter_contract": CONTRACT_VERSION,
            "mode": "enrolled", "failures": 0 if accepted else 1,
            "repos": [{"repo": repo, "checks": [docs, {
                "name": "validation", "ok": passed and complete,
                "detail": "centrally required selection"}],
                "verdict": "PASS" if accepted else "FAIL"}],
            "validation": result, "execution_context": ci_context,
            "trusted_controls": {"commit": controls_commit,
                                 "adapter_commit": control["adapters"]["ci"],
                                 "executor_commit": control["qa_commit"],
                                 "bundle_sha256": expected_bundle},
            "github_check_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "repo", "qa-root", "controls-root", "controls-commit",
                 "registry", "bundle", "expected-bundle", "authorization",
                 "variant", "expected-head", "context", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--selection")
    parser.add_argument("--fixture", action="append", default=[])
    args = parser.parse_args()
    event = None
    try:
        if args.context == "ci":
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
        result = run_enrolled(root=args.root, repo=args.repo, qa_root=args.qa_root,
                              controls_root=args.controls_root, controls_commit=args.controls_commit,
                              registry=args.registry, bundle=args.bundle,
                              expected_bundle=args.expected_bundle, authorization=args.authorization,
                              variant=args.variant, expected_head=args.expected_head,
                              context=args.context, output=args.output, fixtures=args.fixture,
                              selection=args.selection, event=event)
    except (OSError, ValueError, TypeError, KeyError, AdapterCancelled, subprocess.SubprocessError) as exc:
        result = {"gate": "compliance", "failures": 1, "mode": "enrolled",
                  "status": "blocked", "error": str(exc), "github_check_verified": False}
    print(json.dumps(result, separators=(",", ":")))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
