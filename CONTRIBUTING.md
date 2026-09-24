# Contributing to gate-kit

This guide is self-contained: it uses only this public repository, Python's standard library, and optional public tooling. It does not depend on a private guide, workspace, registry, credential, or service.

## Prerequisites

Install:

- Git;
- Python 3.12, the version CI verifies on Ubuntu; and
- a POSIX shell.

Docker is optional and is only needed to reproduce the workflow security scan locally. The unit tests and synthetic demo do not need Docker, repository dependencies, credentials, or network access.

Confirm the setup before changing files:

```sh
git --version
python3 --version
```

## Set up the checkout

From the parent directory of your clone:

```sh
git clone https://github.com/stevekkall-beansgc/gate-kit.git
cd gate-kit
git status --short --branch
```

There is no package-install step. `bin/compliance.py`, the tests, and the synthetic demo use Python's standard library.

## Run the tests

Run the same public checks as `test.yml`, from the repository root:

```sh
python3 -m py_compile bin/compliance.py
python3 scripts/check_stdlib.py bin/
python3 -m unittest discover -s tests -v
```

Every command must exit `0`. The syntax check is silent on success, the standard-library check prints an `OK` summary, and unittest ends with `OK`.

## Run the synthetic demo

```sh
python3 examples/synthetic_quickstart.py
```

The command must exit `0` and print all three expected cases: a green pass, a documentation failure, and a missing-manifest infrastructure failure. The final JSON verdict for each gate invocation is the last non-empty stdout line.

## Review workflow security findings

Pull requests and pushes to `main` run `.github/workflows/workflow-security.yml`. It scans only gate-kit's checked-in `.github/workflows` directory. The job is deliberately report-only: findings do not fail the existing test or compliance CI.

The scan uses immutable upstream pins:

| Component | Immutable pin |
| --- | --- |
| `actions/checkout` | `08c6903cd8c0fde910a37f88322edcfb5dd907a8` (`v5.0.0`) |
| zizmor `1.28.0` container | `ghcr.io/zizmorcore/zizmor:1.28.0@sha256:8e6b3e4fb74d1aa5d23e83ea369f386c66eced0d1fb944d32cd8b2aac100b00d` |

The workflow runs the pinned container directly with `--network none`, mounts only `$GITHUB_WORKSPACE` at `/workspace:ro`, and passes no GitHub token or secret. It scans only gate-kit's checked-in `.github/workflows` directory with `--persona=regular --no-online-audits --no-exit-codes --color=never`. The job's `continue-on-error` keeps findings report-only, but the Docker command is not error-suppressed: scanner setup or internal errors remain visible in the step result and must be investigated rather than treated as a clean scan.

The root `zizmor.yml` applies `hash-pin` to `*` and permits `ref-pin` only for the exact reusable-workflow identity `stevekkall-beansgc/gate-kit/.github/workflows/compliance.yml`. The internal gate uses that identity at `@v0.4.11`. This own annotated tag is never moved, and the separate release gate proves the referenced workflow SHA before release. The exception does not relax third-party actions, which remain pinned to full 40-character commit SHAs.

Severity policy for review:

- **High:** fix before merge or record a specific, reviewable acceptance rationale.
- **Medium:** fix in the change or record a follow-up and rationale.
- **Low, informational, or unknown:** fix when practical or record a follow-up; do not silently suppress it.
- **Confidence:** review confidence separately from severity and explain any false-positive decision using the reported workflow context.

Every reported finding must be fixed, documented as a false positive with evidence, or assigned a concrete follow-up. The initial report-only policy is not approval to ignore findings.

To reproduce the same local inputs with the pinned container, run from the repository root:

```sh
docker run --rm \
  --network none \
  --volume "$PWD:/workspace:ro" \
  --workdir /workspace \
  ghcr.io/zizmorcore/zizmor:1.28.0@sha256:8e6b3e4fb74d1aa5d23e83ea369f386c66eced0d1fb944d32cd8b2aac100b00d \
  --persona=regular \
  --no-online-audits \
  --no-exit-codes \
  --color=never \
  -- \
  .github/workflows
```

This is a static, local-workflow check. A successful run does not certify caller repositories, reusable workflow behavior at runtime, repository settings, secrets, dependencies, action internals, commit history, or production security.

## Review a change

Before opening or updating a pull request:

1. Keep the change focused and preserve fail-closed behavior, check names, release pins, and the final JSON verdict contract.
2. Update the affected README, `AGENTS.md`, security policy, or workflow documentation when behavior or commands change.
3. Run the syntax check, standard-library check, unit suite, and synthetic demo from the repository root.
4. If a GitHub Actions workflow changed, review the report-only zizmor result and resolve or document every finding.
5. Inspect the exact patch and worktree state:

   ```sh
   git diff --check
   git diff --stat
   git diff
   git status --short
   ```

6. In the pull request, state what changed and why, list the commands and results, describe security and compatibility impact, and link any public follow-up. Never include credentials, private paths, customer data, or private-service links.

Tests must cover changed behavior and failure propagation. Keep third-party actions pinned to full 40-character commits; the only reusable-workflow ref-pin exception is the documented internal gate-kit identity above. Pin any separately downloaded tool version or image digest.
