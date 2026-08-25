# AGENTS.md — gate-kit

Deterministic PR/push compliance gates for BeanLabs repos.

## Layout
- `.github/workflows/compliance.yml` — reusable workflow (called via
  per-repo `.github/workflows/gate.yml` stubs pinned to a version tag).
- `bin/compliance.py` — same gate locally:
  `python3 bin/compliance.py --repo <name> [--full] [--markdown]`

## Test commands
- Syntax pin: `python3 -m py_compile bin/compliance.py`
- Live check: run compliance against any active manifest repo and expect
  a JSON verdict line on stdout's last line.

## Guardrails
- Gate semantics are advisory by platform constraint (Free tier) but must
  NEVER silently pass on infrastructure errors.
- Check names are the API: never rename gates casually.
- Version tags only — callers pin @vX.Y.Z; main moves freely.

## Review rules
Binding contract: `../qa-kit/README.md`.
