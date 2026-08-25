# gate-kit

Deterministic compliance + PR gates for BeanLabs repos.

- `.github/workflows/compliance.yml` — reusable workflow: docs standard +
  unit entrypoint (+ optional e2e) per repo, driven by `qa-kit`'s manifest.
- `bin/compliance.py` — same gate runnable locally:
  `python3 bin/compliance.py --repo <name> [--full] [--markdown]`

**Agents:** see [AGENTS.md](AGENTS.md). Contract: see
`~/beans/platform/qa-kit/README.md`.
