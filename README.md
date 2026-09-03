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
tag, and its QA manifest is pinned to `qa-kit v0.3.7`. Caller stubs must use an immutable semver gate-kit tag as well; do not
publish or enable a workflow that checks out `main`.

For Agency only, the workflow prepares Node.js 22 before the manifest-owned
setup. Agency then installs its locked Clawstr dependencies with lifecycle
scripts disabled. This enables clean-checkout offline/loopback tests, not a
public probe, real-key access, model call, or scheduled activity.

**Agents:** see [AGENTS.md](AGENTS.md). Contract: see
`~/beans/platform/qa-kit/README.md`.
