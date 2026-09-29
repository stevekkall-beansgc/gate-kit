#!/usr/bin/env python3
"""Trusted Mac pilot guard, run before candidate checkout or task execution."""
import json
import os
from pathlib import Path
import runpy


def main():
    try:
        controls = runpy.run_path(str(Path(__file__).with_name("validation_adapter.py")))
        repository = os.environ.get("GATE_REPOSITORY", "")
        route = controls["MAC_ROUTES"].get(repository)
        if (route is None or os.environ.get("GATE_REPO") != route["repo"]
                or os.environ.get("RUNNER_ENVIRONMENT") != "self-hosted"):
            raise ValueError("unsupported Mac pilot workflow identity")
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes(),
                           object_pairs_hook=controls["_unique_object"])
        result = controls["validate_ci_context"](os.environ, event, repository,
                                                   os.environ.get("GATE_EXPECTED_SHA"), route["variant"])
        result.update({"guard": "pass", "variant": route["variant"], "repo": route["repo"]})
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"guard": "fail", "error": str(exc), "github_check_verified": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
