# AGENTS.md — gate-kit

Deterministic PR/push compliance gates for BeanLabs repos.

## Layout
- `.github/workflows/compliance.yml` — reusable workflow (called via
  per-repo `.github/workflows/gate.yml` stubs pinned to a version tag).
- `bin/compliance.py` — same gate locally:
  `python3 bin/compliance.py --repo <name> [--root <checkout>] [--full] [--markdown]`

The eligible fleet is explicit: manifest rows with status `active` or
`unit-only`. CI passes the caller checkout with `--root caller`; missing
registry infrastructure, repo roots, or required entrypoints fail closed.

The reusable workflow executes the unchanged CLI from immutable `v0.4.4`
and the manifest from qa-kit `v0.3.8`. Workflow-only releases can keep the
released CLI pin when its contract is unchanged. Callers pin an immutable
workflow release; never publish a workflow that checks out `main`.

## Test commands
- Syntax pin: `python3 -m py_compile bin/compliance.py`
- Regression suite: `python3 -m unittest discover -s tests -v`
- Live check: run compliance against any active manifest repo and expect
  a JSON verdict line on stdout's last line.

## Guardrails
- Gate semantics are advisory by platform constraint (Free tier) but must
  NEVER silently pass on infrastructure errors.
- Check names are the API: never rename gates casually.
- Version tags only — callers pin @vX.Y.Z; main moves freely.

## Review rules
Binding contract: `../qa-kit/README.md`.
