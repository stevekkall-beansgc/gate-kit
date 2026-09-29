#!/usr/bin/env python3
"""Compare local-command and CI-adapter evidence on the same qualified host.

This checks execution linkage, not GitHub check provenance or OS equivalence.
The trusted workflow must separately establish its actual check outcome.
"""
import argparse
import json
import re
import runpy
import sys
from pathlib import Path

_unique_object = runpy.run_path(str(Path(__file__).with_name("validation_adapter.py")))["_unique_object"]


def check_parity(local, ci, *, repo, head, bundle):
    for envelope, context in ((local, "local"), (ci, "ci")):
        if (not isinstance(envelope, dict) or envelope.get("gate") != "compliance"
                or envelope.get("mode") != "enrolled" or envelope.get("failures") != 0):
            raise ValueError("both execution surfaces must pass required compliance")
        controls = envelope.get("trusted_controls")
        if (not isinstance(controls, dict) or controls.get("bundle_sha256") != bundle
                or any(not isinstance(controls.get(key), str)
                       or not re.fullmatch(r"[0-9a-f]{40}", controls[key])
                       for key in ("commit", "adapter_commit", "executor_commit"))):
            raise ValueError("execution is not bound to the reviewed bundle")
        result = envelope.get("validation")
        if (not isinstance(result, dict) or result.get("schema") != "qa-kit.validation-result/v1"
                or result.get("repo") != repo or result.get("context") != context
                or result.get("status") != "pass" or result.get("selection_complete") is not True
                or result.get("bundle_sha256") != bundle or result.get("remaining_required") != []
                or result.get("required") != result.get("selected") or not result.get("required")):
            raise ValueError("execution coverage or context mismatch")
        candidate = result.get("candidate")
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("before"), dict)
                or candidate["before"].get("head") != head
                or candidate["before"].get("dirty") is not False
                or candidate.get("after") != candidate["before"]):
            raise ValueError("execution lacks unchanged exact candidate proof")
        sources = result.get("controls")
        qa = sources.get("qa") if isinstance(sources, dict) else None
        if (not isinstance(qa, dict) or qa.get("head") != controls["executor_commit"]
                or qa.get("dirty") is not False or qa.get("matches_head") is not True
                or not isinstance(qa.get("tracked_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", qa["tracked_sha256"])):
            raise ValueError("execution lacks exact executor source proof")
        tasks = result.get("tasks")
        if (not isinstance(tasks, list) or not tasks or any(
                not isinstance(task, dict) or task.get("status") != "pass"
                or task.get("exit_code") != 0 or task.get("timed_out") is not False
                or task.get("cancelled", False) is not False for task in tasks)):
            raise ValueError("execution lacks passing task outcomes")
    if local["trusted_controls"] != ci["trusted_controls"]:
        raise ValueError("control checkouts differ between execution surfaces")
    first, second = local["validation"], ci["validation"]
    for key in ("github_repository", "selection", "variant", "required", "selected",
                "candidate", "observed", "fixtures", "contract_sha256", "registry_sha256",
                "authorization_sha256", "bundle_sha256", "plan_sha256"):
        if key not in first or first[key] != second.get(key):
            raise ValueError("execution inputs or scope differ: " + key)
    if first["controls"]["qa"] != second["controls"]["qa"]:
        raise ValueError("executor checkout differs between execution surfaces")
    def outcomes(result):
        return [(task.get("task"), task.get("variant"), task.get("status"), task.get("exit_code"))
                for task in result["tasks"]]
    if outcomes(first) != outcomes(second):
        raise ValueError("task outcomes differ between execution surfaces")
    return {"parity": "pass", "repo": repo, "head": head,
            "selection": first["selection"], "variant": first["variant"],
            "bundle_sha256": bundle, "github_check_verified": False,
            "scope": "same-host local-command and CI-adapter execution"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("local", "ci", "repo", "head", "bundle"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        with open(args.local, "rb") as stream:
            local = json.load(stream, object_pairs_hook=_unique_object)
        with open(args.ci, "rb") as stream:
            ci = json.load(stream, object_pairs_hook=_unique_object)
        result = check_parity(local, ci, repo=args.repo, head=args.head, bundle=args.bundle)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"parity": "fail", "error": str(exc), "github_check_verified": False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
