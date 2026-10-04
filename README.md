# Gate Kit

Use one repeatable documentation and test contract locally and in CI.
Gate Kit reads QA Kit's manifest, checks the selected repository's contributor
instructions, runs its declared commands and returns a JSON verdict.

Missing configuration and failed commands are failures, not silent passes.
The gate is advisory on the Free-tier CI platform; it is not security
certification or a deployment system.

## The gate at a glance

![Trusted manifest and checkout inputs must exist. Missing inputs produce an infrastructure failure; available inputs select documentation and owned checks and produce a JSON verdict.](assets/readme-flow.svg)

The same checker reports local or configured CI outcomes. Missing infrastructure is a failure, not a silent pass.
[Full-size diagram](assets/readme-flow.svg) · [Editable source](assets/readme-flow.mmd).

## Try the synthetic demo

With Python 3 installed, run this from the source checkout:

```sh
python3 examples/synthetic_quickstart.py
```

The demo calls the real checker against temporary synthetic repositories.
It requires no private workspace, credentials or network. It checks a healthy
repository, a missing documentation contract and a missing manifest. Expect
the healthy case to pass and both failure cases to fail; the final non-empty
stdout line is JSON.

## Use with a repository

Only run trusted manifests and commands: they execute locally with the user's
permissions. With a prepared QA Kit manifest, the CLI form is:

```sh
python3 bin/compliance.py --repo <name> --root <checkout> [--full] [--markdown]
```

Default mode runs documentation, setup and unit checks. `--full` adds a
registered end-to-end command. The
[detailed guide](README-REFERENCE.md#5-supported-scope) explains selection,
timeouts, coverage and exit codes.

## Follow the implementation

- [Checker](bin/compliance.py): manifest → docs → declared commands → verdict.
- [Synthetic example](examples/synthetic_quickstart.py): real subprocess pass
  and failure cases.
- [Reusable workflow](.github/workflows/compliance.yml): fixed source pins,
  caller checkout and runner boundaries.
- [Checker tests](tests/test_compliance.py) and
  [demo tests](tests/test_synthetic_quickstart.py): offline regression evidence.

## Verify and contribute

```sh
python3 -m unittest discover -s tests -q
```

[CONTRIBUTING.md](CONTRIBUTING.md) covers full setup and verification, including
the pinned QA fixture required for shared-executor integration. With those
prerequisites, Task 3 and Python 3.12, `task validate` runs the existing checks.

## Compatibility and limits

Workflow releases and checker releases are separate. The
[release-pin guide](README-REFERENCE.md#6-release-pins-in-v0424) records their
fixed refs; a newer workflow tag does not imply a newer checker.
[The adapter contract](VALIDATION-ADAPTER.md) explains opt-in validation.
Installing an adapter does not enroll or activate a repository.

The synthetic demo does not audit repository history, dependencies, live
services or production security. See [SECURITY.md](SECURITY.md) for private
reports and [AGENTS.md](AGENTS.md) for operating rules.
