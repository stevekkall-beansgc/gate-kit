# gate-kit

Deterministic compliance + PR gates for BeanLabs repos.

- `.github/workflows/compliance.yml` — reusable workflow: docs standard +
  unit entrypoint (+ optional e2e) per caller, using gate-kit's entrypoint
  and `qa-kit`'s manifest.
- `bin/compliance.py` — same gate runnable locally:
  `python3 bin/compliance.py --repo <name> [--root <checkout>] [--full] [--markdown]`

The manifest's `active` and `unit-only` rows are the eligible fleet. With no
`--repo`, the gate evaluates every eligible row; CI callers pass their
manifest name and `--root caller` so the checked-out caller is tested rather
than the developer-machine path recorded in the registry. Missing manifests,
invalid active rows, repo roots, or required unit commands fail the gate.

The workflow's `gate-kit` checkout is pinned to the immutable `v0.4.4` release
tag; its QA manifest is pinned to `qa-kit v0.6.0`; and the BeanFit CLI fixture
used by beanfit-app E2E is pinned to immutable `v0.4.0`. Caller stubs must use an immutable semver gate-kit tag as well; do not
publish or enable a workflow that checks out `main`.

The optional `runner` input defaults to `ubuntu-latest`. Trusted push or manual
callers may select a repository-scoped self-hosted runner label; untrusted pull
request workflows must keep the hosted default. The `beans-mac` runner uses its
preinstalled `python3`; hosted runners continue to receive the pinned Python
3.13 toolchain from `actions/setup-python`.

## Synthetic quickstart (no workspace required)

`python3 examples/synthetic_quickstart.py` builds a synthetic repo and qa-kit
manifest in a temp directory, then exercises the real `bin/compliance.py` CLI
as a subprocess — no BeanLabs workspace, private repos, credentials, or network
needed. It demonstrates all three paths of the gate contract:

1. a healthy synthetic repo emitting a green JSON verdict (exit 0);
2. a broken `AGENTS.md` producing a `FAIL` verdict (exit 1);
3. a missing qa-kit manifest failing closed as an infrastructure failure.

Each run's machine-readable verdict is the JSON object on stdout's last line.
The reusable workflow preserves the CLI output and uses its exit status as the
gate result.

The caller checkout is pinned to the reviewed pull-request head SHA or the exact
push SHA, so the tested source is explicit rather than an implicit merge ref.

For Agency only, the workflow prepares Node.js 22 before the manifest-owned
setup. Agency then installs its locked Clawstr dependencies with lifecycle
scripts disabled. This enables clean-checkout offline/loopback tests, not a
public probe, real-key access, model call, or scheduled activity.

**Agents:** see [AGENTS.md](AGENTS.md). Contract: see
`~/beans/platform/qa-kit/README.md`.
