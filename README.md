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

The workflow's `gate-kit` checkout uses `main` only while this unreleased
repair is staged. Before release, change that ref to the new gate-kit version
tag (for example, `v0.4`) and repoint caller stubs from `@v0.3` to the same
tag in one release handoff. Do not publish a tag while the workflow still
checks out `main`.

**Agents:** see [AGENTS.md](AGENTS.md). Contract: see
`~/beans/platform/qa-kit/README.md`.
