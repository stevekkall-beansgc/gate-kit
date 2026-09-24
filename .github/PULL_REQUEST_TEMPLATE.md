## What & why
Explain what changes, why now, and who benefits.

## Evidence
- [ ] `python3 -m py_compile bin/compliance.py`
- [ ] `python3 scripts/check_stdlib.py bin/`
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `python3 examples/synthetic_quickstart.py`
- [ ] `git diff --check`
- [ ] No secrets, credentials, private paths, or customer data committed
- [ ] README, `AGENTS.md`, `CONTRIBUTING.md`, and `SECURITY.md` reflect behavior changes

## Security and compatibility
For workflow changes, disposition every zizmor finding. Note any migration, pin, or fail-closed contract change.
