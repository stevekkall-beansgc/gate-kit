# gate-kit

Deterministic, fail-closed compliance and PR/push gates for repositories that publish a `qa-kit` manifest.

This is a five-minute reading route: what problem it solves, how to run it, where the implementation lives, how failure is demonstrated, and which parts of the fleet it supports.

## 1. The problem

A repository needs one repeatable answer to two questions: are its contributor instructions and test entrypoints coherent, and did the declared setup, unit, and optional end-to-end checks actually pass? Running those commands differently in each CI job makes results drift.

`gate-kit` gives local runs and CI the same small contract:

- load and validate the `qa-kit` manifest;
- check the repository's documentation contract;
- run the declared setup and unit commands, and run e2e only when requested;
- preserve command failures and produce a machine-readable JSON verdict.

The gate is advisory on the repository's Free-tier CI platform, but infrastructure errors never become silent passes.

## 2. Run the synthetic demo

From the repository root, with Python 3 installed:

```sh
python3 examples/synthetic_quickstart.py
```

The script creates a temporary synthetic repository and manifest, then invokes the real [`bin/compliance.py`](bin/compliance.py) as a subprocess. It needs no existing workspace, credentials, private repository, or network access.

The run proves three outcomes:

| Scenario | Expected result | Contract demonstrated |
| --- | --- | --- |
| Healthy synthetic repository | Exit `0`; green `PASS` verdict | A valid manifest, docs, and unit command succeed. |
| Missing required documentation contract in `AGENTS.md` | Exit `1`; `FAIL` verdict | A documentation mismatch is a real gate failure. |
| Missing `qa-kit` manifest | Exit `1`; infrastructure failure | Missing infrastructure fails closed instead of passing. |

The final non-empty stdout line is JSON. The reusable workflow also keeps the CLI's exit status as the gate result.

For a real checkout with a `qa-kit` manifest, the local form is:

```sh
python3 bin/compliance.py --repo <name> --root <checkout> [--full] [--markdown]
```

The synthetic demo supplies its temporary manifest through `QA_KIT_DIR`, so that command is not needed to run the demo.

## 3. Follow the implementation

Read these links in order:

1. [`bin/compliance.py`](bin/compliance.py) — the local and CI checker. Its main path is `load_manifest` → `manifest_problems` → `docs_check` → declared commands → JSON verdict.
2. [`examples/synthetic_quickstart.py`](examples/synthetic_quickstart.py) — a small end-to-end harness that builds all three proof cases and calls the real CLI.
3. [`.github/workflows/compliance.yml`](.github/workflows/compliance.yml) — the reusable workflow: caller checkout, fixed dependency checkouts, runner setup, command routing, and failure propagation.
4. [`tests/test_compliance.py`](tests/test_compliance.py) and [`tests/test_synthetic_quickstart.py`](tests/test_synthetic_quickstart.py) — offline contract and regression coverage.

[`CONTRIBUTING.md`](CONTRIBUTING.md) is the self-contained public route for setup, tests, the synthetic demo, workflow security review, and change review. [`AGENTS.md`](AGENTS.md) remains the compact test and guardrail reference. For private vulnerability reports, see [`SECURITY.md`](SECURITY.md).

## 4. Failure-mode proof

The quickstart is intentionally more than a happy-path example. A broken `AGENTS.md` produces a failed docs check, and a missing manifest produces a nonzero infrastructure verdict. The regression tests also cover a missing checkout root, a caller-root override, a real subprocess timeout, and preservation of the expected exit status.

The checker treats all of these as failures:

- a missing, unreadable, or malformed manifest;
- an unknown status, an active row without a path or unit entrypoint, or a manifest with no eligible rows;
- an unknown or non-active repository selected with `--repo`;
- a missing repository root, missing command, command error, or 900-second command timeout;
- an infrastructure problem while loading or selecting the manifest.

A failed check increments the failure count. The process returns `1` when any check fails and `0` only when every selected check passes.

## 5. Supported scope

The manifest is the source of eligibility and commands:

- `active` and `unit-only` rows are eligible; `planned` rows are not.
- `unit` is required for every eligible row. `setup` and `e2e` are optional.
- The default mode runs `docs`, `setup`, and `unit`; `--full` adds `e2e` when it is registered.
- Without `--repo`, all eligible rows are selected. With `--repo`, `--root` may point the selected check at a caller checkout; `--root` without `--repo` is an infrastructure failure.
- The output is human-readable plus a final JSON object containing the gate name, failure count, selected coverage, and per-repository checks.

The reusable workflow defaults to `ubuntu-latest`. A trusted push caller may select the repository-scoped `beans-mac` runner; pull requests in the checked-in caller stay hosted. The `beans-mac` path uses its preinstalled Python and enforces its separate canonical-checkout guard.

This repository is a compliance gate, not a dependency scanner, history auditor, credential manager, deployment system, or security certification. The report-only zizmor job runs the pinned `ghcr.io/zizmorcore/zizmor:1.28.0@sha256:8e6b3e4fb74d1aa5d23e83ea369f386c66eced0d1fb944d32cd8b2aac100b00d` container directly with `--network none`, mounts only the checkout read-only, passes no GitHub token or secret, and scans only gate-kit's own checked-in workflow definitions. It does not inspect or certify caller repositories. The synthetic demo proves the local gate contract; it does not establish any claim about a repository's history, dependencies, production security, or external services.

## 6. Release pins in v0.4.20

The workflow release and the checker release are separate contracts. The reusable workflow released with `v0.4.20` intentionally checks out the following fixed release refs:

| Purpose | Repository | Pin | Checked-out path |
| --- | --- | --- | --- |
| Compliance checker | `gate-kit` | `v0.4.4` | `gate-kit` |
| QA manifest | `qa-kit` | `v0.6.1` | `qa-kit` |
| BeanFit CLI fixture used by `beanfit-app` e2e | `BeanFit` | `v0.4.0` | `beanfit` |

For ordinary callers, the workflow then runs the pinned checker as `python3 gate-kit/bin/compliance.py`, points `QA_KIT_DIR` at the checked-out `qa-kit` manifest, and passes `--root caller` for the reviewed caller checkout. It does not run a moving `main` checkout of the checker. For the `agents` profile, the workflow verifies the pinned checker source and changes only its command timeout literals from 900 to 14400 seconds before running the adapted copy; check names, commands, and failure semantics remain the same.

`v0.4.20` therefore identifies the reusable workflow release, not a claim that the checker is also `v0.4.20`. Keeping the immutable `v0.4.4` checker pin is intentional when its contract is unchanged. The three refs above are release-specific compatibility pins, not a claim about release recency. Caller stubs pin a separate immutable reusable-workflow tag; this README does not change those pins.

## Repository checks

Run the public, offline verification route with:

```sh
python3 examples/synthetic_quickstart.py
python3 -m unittest discover -s tests -q
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the exact syntax and standard-library checks, review steps, pinned report-only workflow scan, severity policy, and explicit security-scope limitations.
