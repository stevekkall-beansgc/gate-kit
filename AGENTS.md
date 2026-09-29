# AGENTS.md — gate-kit

Deterministic PR/push compliance gates for Legume Labs repos.

## Layout
- `.github/workflows/compliance.yml` — reusable workflow (called via
  per-repo `.github/workflows/gate.yml` stubs pinned to a version tag).
- `bin/compliance.py` — same gate locally:
  `python3 bin/compliance.py --repo <name> [--root <checkout>] [--full] [--markdown]`
- `bin/validation_adapter.py` — additive bridge to QA's common executor for
  explicitly enrolled validation; see `VALIDATION-ADAPTER.md`.

The eligible fleet is explicit: manifest rows with status `active` or
`unit-only`. CI passes the caller checkout with `--root caller`; missing
registry infrastructure, repo roots, or required entrypoints fail closed.

The reusable workflow executes the unchanged CLI from immutable `v0.4.4`
and the manifest from qa-kit `v0.6.6`, with the BeanFit CLI fixture pinned
to immutable `v0.4.0`. The explicitly qualified Agency legacy cohort alone uses
qa-kit `v0.7.0` for its conditional public executor-fixture bootstrap; it remains
unenrolled and retains all manifest-owned unit/full commands and runner guards.
Workflow-only releases can keep the
released CLI pin when its contract is unchanged. Callers pin an immutable
workflow release; never publish a workflow that checks out `main`.

The optional `runner` workflow input defaults to `ubuntu-latest`. A caller may
select a repository-scoped self-hosted runner label only from a trusted event;
pull-request callers must retain the hosted default. The `beans-mac` path must
use the Mac's preinstalled `python3`; do not invoke `actions/setup-python` there
because its macOS packages require GitHub's non-portable hosted-toolcache path.

## Test commands
- Syntax pin: `python3 -m py_compile bin/compliance.py`
- Regression suite: `python3 -m unittest discover -s tests -v`
- Shared-executor integration: with the pinned QA fixture prepared,
  `bash scripts/test_validation_e2e.sh` (runs
  `python3 -B -m unittest discover -s integration -v`). Prepare it with
  `bash setup/qa-validation/bootstrap.sh`. A missing fixture fails;
  `.qa-fixtures/qa-kit` is separate from production control checkouts.
- Live check: run compliance against any active manifest repo and expect
  a JSON verdict line on stdout's last line.

## Guardrails
- Gate semantics are advisory by platform constraint (Free tier) but must
  NEVER silently pass on infrastructure errors.
- Check names are the API: never rename gates casually.
- Version tags only — callers pin @vX.Y.Z; main moves freely.
- Enrollment requires an exact trusted control commit and bundle digest. The
  new bridge preserves the existing docs check and rejects partial coverage as
  full compliance. Initial enrolled CI is hosted push/PR only; protected agents
  and BeanMind retain their separately qualified profiles. The existing reusable
  workflow retains its legacy checker/fixture pins and old QA manifest for every
  cohort except the explicitly qualified Agency bootstrap described above.
- The inactive Mac pilot adapter supports only reviewed main pushes for the
  two fixed pilot repositories, with exact new repo-scoped runner names,
  macOS/ARM64 runtime variants, full central CI selection and source/event guards.
  It grants no PR/fork or registration authority. A separately published workflow,
  bundle and per-repo registration are required before adoption.

## Review rules
Binding contract: `../qa-kit/README.md`.

## Beanstalk compliance profile

The `agents` caller selects one of two closed profiles. GitHub-hosted
`macos-15` still stages the exact event commit into a new canonical directory,
refusing existing targets and symlink ancestors. Self-hosted `beans-mac` accepts
only push events for `stevekkall-beansgc/Beanstalk` on `main` or `release/*`.
It uses preinstalled Homebrew Python and CommandLineTools Git; never accept an
Xcode license or change system settings. Local workspaces/temp directories must
be disjoint from the existing canonical checkout. Before any checkout step the
workflow verifies the local event/context and installs only a temporary wrapper.

The local wrapper never copies, checks out, resets or cleans canonical source.
It holds an exclusive nonblocking flock on
`/Users/stephenkall/beans/catalog/agents/.git/beanstalk-canonical-tests.lock`
through all compliance setup/tests and the final source recheck. Root's other
canonical test workflows must honor the same persistent inode; never unlink it.
Symlink/hardlink locks, conflicts, wrong HEAD, dirty/hidden index entries, or any
physical tracked file differing from its exact HEAD Git blob fail closed.
Canonical and separate caller source must match the exact push SHA; source is
verified again even when the checker fails. No persistent recovery marker or
runtime authority is created. All writers must cooperate with this advisory lock.

Both profiles verify the released checker before changing only its 900-second
timeout to 14400 seconds; the job allows 270 minutes. Manifest docs/setup/unit/full
commands, exit failures, check identity and other repository profiles remain
unchanged. Local tests generate no accepted cache or model/scheduler effect.

Bean Counter uses the manifest-owned pinned Rust/Python setup and local SQLite unit/e2e commands from qa-kit v0.6.6. Its hosted gate prepares Node.js 22 for frozen contract checks. No local runner, database service or customer credentials are required.
