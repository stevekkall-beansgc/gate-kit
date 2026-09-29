#!/usr/bin/env python3
"""Assemble sanitized execution evidence; GitHub provenance is verified outside.

The trusted workflow uploads this four-file directory only after both execution
surfaces and their same-host comparison pass. No task output is copied here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy

SCHEMA = "gate-kit.actions-validation-provenance/v1"
RECEIPTS = ("local-envelope.json", "ci-envelope.json", "parity.json")


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate evidence field")
        value[key] = item
    return value


def load(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("evidence must be a regular file")
    value = json.loads(path.read_bytes(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("evidence must be an object")
    return value


def assemble(directory, policy_path, repo, runtime_root, environ=None):
    env = os.environ if environ is None else environ
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("evidence directory is missing or ambiguous")
    policy = load(policy_path)
    if policy.get("schema") != "gate-kit.validation-workflow-policy/v1":
        raise ValueError("unknown workflow policy")
    row = policy.get("repos", {}).get(repo)
    if not isinstance(row, dict):
        raise ValueError("repository is outside the fixed workflow policy")
    # The workflow's reviewed bootstrap verifies the independently pinned
    # runtime before loading any code from that second source checkout.
    bootstrap = runpy.run_path(str(Path(__file__).with_name("validation_adapter.py")))
    bootstrap["verify_checkout"](runtime_root, policy["adapter_commit"])
    runtime = runpy.run_path(str(Path(runtime_root) / "bin/validation_adapter.py"))
    local, ci, parity = [load(directory / name) for name in RECEIPTS]
    head = env.get("GATE_EXPECTED_SHA")
    compared = runpy.run_path(str(Path(runtime_root) / "bin/check_parity.py"))["check_parity"](
        local, ci, repo=repo, head=head, bundle=row["bundle_sha256"])
    if compared != parity:
        raise ValueError("parity receipt does not match the checked execution")
    expected = {"commit": policy["controls_commit"], "adapter_commit": policy["adapter_commit"],
                "executor_commit": policy["executor_commit"], "bundle_sha256": row["bundle_sha256"]}
    if local.get("trusted_controls") != expected or ci.get("trusted_controls") != expected:
        raise ValueError("execution differs from the fixed workflow controls")
    result = ci["validation"]
    if (result["github_repository"] != row["github_repository"]
            or result["variant"] != row["variant"] or result["selection"] != row["selection"]):
        raise ValueError("execution differs from the approved selection")
    context = runtime["validate_ci_context"](env, load(env["GITHUB_EVENT_PATH"]),
                                               row["github_repository"], head, row["variant"])
    if repo != runtime["MAC_ROUTES"].get(row["github_repository"], {}).get("repo"):
        raise ValueError("workflow alias is outside the fixed Mac route")
    if ci.get("execution_context") != context or env.get("GITHUB_JOB") != "compliance":
        raise ValueError("CI execution differs from this job")
    sources = result["controls"]
    if (sources.get("adapter", {}).get("head") != expected["adapter_commit"]
            or sources.get("qa", {}).get("head") != expected["executor_commit"]):
        raise ValueError("execution source identity mismatch")
    fixtures = row["fixtures"]
    if not isinstance(fixtures, dict) or set(result["fixtures"]) != set(fixtures):
        raise ValueError("execution fixture set mismatch")
    for name, commit in fixtures.items():
        identity = result["fixtures"][name]
        if (identity.get("before", {}).get("head") != commit
                or identity.get("before", {}).get("dirty") is not False
                or identity.get("after") != identity.get("before")):
            raise ValueError("execution fixture source mismatch")
    caller_ref = env.get("GITHUB_WORKFLOW_REF", "")
    job_ref = env.get("GATE_JOB_WORKFLOW_REF", "")
    job_sha = env.get("GATE_JOB_WORKFLOW_SHA", "")
    if (caller_ref != row["github_repository"] + "/.github/workflows/gate.yml@refs/heads/main"
            or env.get("GITHUB_WORKFLOW_SHA") != head
            or env.get("GATE_JOB_WORKFLOW_REPOSITORY") != "stevekkall-beansgc/gate-kit"
            or env.get("GATE_JOB_WORKFLOW_PATH") != ".github/workflows/validation.yml"
            or not re.fullmatch(r"stevekkall-beansgc/gate-kit/\.github/workflows/validation\.yml@(?:refs/tags/)?v[0-9]+\.[0-9]+\.[0-9]+", job_ref)
            or not re.fullmatch(r"[0-9a-f]{40}", job_sha)
            or not re.fullmatch(r"[1-9][0-9]*", env.get("GATE_JOB_CHECK_RUN_ID", ""))):
        raise ValueError("workflow identity metadata is absent or inconsistent")
    controls = dict(expected)
    controls["fixtures"] = fixtures
    for key in ("registry_sha256", "authorization_sha256", "contract_sha256"):
        if (not re.fullmatch(r"[0-9a-f]{64}", result.get(key, ""))
                or result[key] != row[key]):
            raise ValueError("execution control digest differs from the fixed policy")
        controls[key] = result[key]
    value = {"schema": SCHEMA, "repository": row["github_repository"], "repo": repo,
             "head_sha": head, "event": context["event"], "ref": context["ref"],
             "run_id": context["run_id"], "run_attempt": context["run_attempt"],
             "job_id": "compliance", "check_name": "compliance / compliance",
             "check_run_id": env["GATE_JOB_CHECK_RUN_ID"],
             "caller_workflow": {"ref": caller_ref, "sha": head, "path": ".github/workflows/gate.yml"},
             "reusable_workflow": {"ref": job_ref, "sha": job_sha, "path": ".github/workflows/validation.yml"},
             "runner": {"name": context["runner_name"], "os": context["runner_os"],
                        "arch": context["runner_arch"], "environment": context["runner_environment"]},
             "controls": controls, "selection": result["selection"], "variant": result["variant"],
             "receipt_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                for name in RECEIPTS}, "github_check_verified": False}
    output = directory / "gate-provenance.json"
    with output.open("x") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
    return value


def artifact_receipt(env):
    run_id, attempt = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", "")
    artifact_id, digest = env.get("GATE_ARTIFACT_ID", ""), env.get("GATE_ARTIFACT_DIGEST", "")
    if (any(not re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt, artifact_id))
            or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("uploader artifact identity is missing")
    return {"artifact_id": artifact_id, "artifact_digest": "sha256:" + digest,
            "artifact_name": f"gate-validation-{run_id}-{attempt}",
            "run_id": run_id, "run_attempt": attempt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-receipt", action="store_true")
    for name in ("directory", "policy", "repo", "runtime-root"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    try:
        if args.artifact_receipt:
            print("GATE_ARTIFACT_RECEIPT " + json.dumps(artifact_receipt(os.environ), sort_keys=True))
        else:
            if any(value is None for value in (args.directory, args.policy, args.repo, args.runtime_root)):
                raise ValueError("all evidence assembly inputs are required")
            assemble(args.directory, args.policy, args.repo, args.runtime_root)
            print(json.dumps({"evidence": "assembled", "github_check_verified": False}))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"evidence": "blocked", "error": str(exc), "github_check_verified": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
