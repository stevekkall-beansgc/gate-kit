#!/usr/bin/env python3
"""compliance.py — deterministic PR/push compliance gate for BeanLabs repos.

Runs, for one repo (or every active manifest row):
  1. docs standard   (README + AGENTS.md, sections match manifest entrypoints)
  2. unit entrypoint (exact command from qa-kit manifest)
  3. e2e entrypoint  (--full only; app-tier flows)

Output: human table + machine-readable JSON verdict on stdout's last line
(consumed by the sticky-comment/report step of the gate workflow and by the
hub's compliance receipt).

The reusable workflow supplies --root for its caller checkout because the
manifest paths describe the local fleet layout, not the runner workspace.
Missing registry infrastructure or malformed active rows fail closed.

Exit code: number of failed checks capped at 1... i.e. 0 = green, 1 = any fail.
Advisory Phase 1: GitHub Free cannot block merges on private repos; this
gate's red ❌ becomes binding via `ag release --require-pr-green` (Phase 2).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# qa-kit lives beside gate-kit in ~/beans/platform; CI overrides via env.
QA_KIT = Path(os.environ.get("QA_KIT_DIR",
                             Path(__file__).resolve().parents[2] / "qa-kit"))
MANIFEST = QA_KIT / "manifest.json"
ACTIVE_STATUSES = ("active", "unit-only")
KNOWN_STATUSES = set(ACTIVE_STATUSES) | {"planned"}


def expand(p):
    return Path(p).expanduser()


def sh(cmd, cwd, env=None):
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True,
                           text=True, timeout=900)
        ok = p.returncode == 0
        tail = ((p.stdout or "") + "\n" + (p.stderr or ""))[-800:]
    except FileNotFoundError as e:
        ok, tail = False, f"entrypoint missing (or working directory missing): {e}"
    except subprocess.TimeoutExpired:
        ok, tail = False, "timeout 900s"
    return {"ok": ok, "secs": round(time.monotonic() - t0, 1), "tail": tail.strip()}


def docs_check(root, unit_cmd):
    problems = []
    ag, rd = root / "AGENTS.md", root / "README.md"
    if not root.is_dir():
        return ["missing repo root"]
    if not ag.is_file():
        return ["missing AGENTS.md"]
    try:
        text = ag.read_text()
    except OSError as e:
        return [f"cannot read AGENTS.md: {e}"]
    if "## Test commands" not in text:
        problems.append("AGENTS.md lacks '## Test commands'")
    if unit_cmd and " ".join(unit_cmd) not in text.replace("`", ""):
        problems.append("AGENTS.md does not state manifest unit cmd")
    if not rd.is_file():
        problems.append("missing README.md")
    else:
        try:
            readme = rd.read_text()
        except OSError as e:
            problems.append(f"cannot read README.md: {e}")
        else:
            if "AGENTS.md" not in readme:
                problems.append("README does not reference AGENTS.md")
    return problems


def load_manifest():
    if not MANIFEST.is_file():
        raise RuntimeError(f"missing qa-kit manifest: {MANIFEST}")
    try:
        manifest = json.loads(MANIFEST.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise RuntimeError(f"cannot read qa-kit manifest {MANIFEST}: {e}") from e
    if not isinstance(manifest, dict) or not isinstance(manifest.get("repos"), list):
        raise RuntimeError("qa-kit manifest must contain a repos list")
    return manifest


def _valid_cmd(cmd):
    return (isinstance(cmd, list) and bool(cmd)
            and all(isinstance(part, str) and bool(part) for part in cmd))


def _spec_problems(repo_name, label, spec, required=False):
    problems = []
    if spec is None:
        if required:
            problems.append(f"{repo_name}: missing {label} entrypoint")
        return problems
    if not isinstance(spec, dict):
        return [f"{repo_name}: {label} must be an object"]
    cmd = spec.get("cmd")
    if cmd is None:
        if required:
            problems.append(f"{repo_name}: missing {label} entrypoint")
    elif not _valid_cmd(cmd):
        problems.append(f"{repo_name}: {label}.cmd must be a non-empty command list")
    env = spec.get("env")
    if env is not None and (not isinstance(env, dict)
                            or any(not isinstance(k, str) or not isinstance(v, str)
                                   for k, v in env.items())):
        problems.append(f"{repo_name}: {label}.env must map strings to strings")
    return problems


def manifest_problems(manifest):
    problems = []
    seen = set()
    for index, repo in enumerate(manifest["repos"]):
        if not isinstance(repo, dict):
            problems.append(f"repos[{index}] must be an object")
            continue
        name = repo.get("name")
        status = repo.get("status")
        if not isinstance(name, str) or not name:
            problems.append(f"repos[{index}] missing name")
            name = f"repos[{index}]"
        elif name in seen:
            problems.append(f"duplicate repo name: {name}")
        seen.add(name)
        if status not in KNOWN_STATUSES:
            problems.append(f"{name}: unknown status {status!r}")
        if status not in ACTIVE_STATUSES:
            continue
        if not isinstance(repo.get("path"), str) or not repo["path"]:
            problems.append(f"{name}: missing repo path")
        problems.extend(_spec_problems(name, "unit", repo.get("unit"), required=True))
        for label in ("setup", "e2e"):
            problems.extend(_spec_problems(name, label, repo.get(label)))
    if not any(isinstance(repo, dict) and repo.get("status") in ACTIVE_STATUSES
               for repo in manifest["repos"]):
        problems.append("manifest has no active/unit-only repos")
    return problems


def command_env(root, spec):
    values = spec.get("env") if isinstance(spec, dict) else None
    if not values:
        return None
    env = dict(os.environ)
    for key, value in values.items():
        env[key] = str(root / value) if not value.startswith("/") else value
    return env


def emit_infrastructure_failure(problems, coverage=None):
    print("\n[FAIL] infrastructure")
    for problem in problems:
        print(f"  ❌ {problem}")
    payload = {"gate": "compliance", "failures": 1, "repos": [],
               "infrastructure": problems}
    if coverage is not None:
        payload["coverage"] = coverage
    print(json.dumps(payload, separators=(",", ":")))
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None,
                    help="repo name from manifest (default: all active/unit-only)")
    ap.add_argument("--root", default=None,
                    help="checkout root for --repo (used by reusable CI workflow)")
    ap.add_argument("--full", action="store_true", help="include e2e tier")
    ap.add_argument("--markdown", action="store_true", help="emit markdown summary block")
    args = ap.parse_args()

    if args.root and not args.repo:
        return emit_infrastructure_failure(["--root requires --repo"])
    try:
        man = load_manifest()
    except RuntimeError as e:
        return emit_infrastructure_failure([str(e)])
    problems = manifest_problems(man)
    if problems:
        return emit_infrastructure_failure(problems)

    eligible = [r for r in man["repos"] if r.get("status") in ACTIVE_STATUSES]
    repos = [r for r in eligible if args.repo is None or r["name"] == args.repo]
    if args.repo and not repos:
        return emit_infrastructure_failure(
            [f"unknown or non-active repo: {args.repo}"],
            {"eligible": len(eligible), "selected": 0,
             "statuses": list(ACTIVE_STATUSES)})

    coverage = {"eligible": len(eligible), "selected": len(repos),
                "statuses": list(ACTIVE_STATUSES),
                "mode": "repo" if args.repo else "all"}

    report = []
    failures = 0
    for repo in repos:
        root = (expand(args.root) if args.root else expand(repo["path"])).resolve()
        unit_cmd = (repo.get("unit") or {}).get("cmd") or []
        checks = []

        problems = docs_check(root, unit_cmd)
        checks.append({"name": "docs", "ok": not problems,
                       "detail": "; ".join(problems)})

        setup = repo.get("setup")
        if isinstance(setup, dict) and setup.get("cmd"):
            r = sh(setup["cmd"], root, command_env(root, setup))
            checks.append({"name": "setup", "ok": r["ok"], "secs": r["secs"],
                           "detail": None if r["ok"] else r["tail"][-400:]})

        if unit_cmd:
            r = sh(unit_cmd, root, command_env(root, repo["unit"]))
            checks.append({"name": "unit", "ok": r["ok"], "secs": r["secs"],
                           "detail": None if r["ok"] else r["tail"][-400:]})
        else:
            checks.append({"name": "unit", "ok": False, "detail": "no unit entrypoint registered"})

        e2e = repo.get("e2e") or {}
        if args.full and e2e.get("cmd"):
            r = sh(e2e["cmd"], root, command_env(root, e2e))
            checks.append({"name": "e2e", "ok": r["ok"], "secs": r["secs"],
                           "detail": None if r["ok"] else r["tail"][-400:]})

        fails = [c for c in checks if not c["ok"]]
        failures += len(fails)
        report.append({"repo": repo["name"], "checks": checks,
                       "verdict": "PASS" if not fails else "FAIL"})

    for r in report:
        print(f"\n[{r['verdict']}] {r['repo']}")
        for c in r["checks"]:
            mark = "✅" if c["ok"] else "❌"
            extra = f" ({c['secs']}s)" if "secs" in c else ""
            print(f"  {mark} {c['name']}{extra}" + (f" — {c['detail']}" if c.get("detail") else ""))
        print(f"  verdict: {r['verdict']}")
    print(f"\ncoverage: {coverage['selected']}/{coverage['eligible']} "
          "active/unit-only repos selected")

    last_line = json.dumps({"gate": "compliance", "failures": failures,
                            "repos": report, "coverage": coverage},
                           separators=(",", ":"))
    if args.markdown:
        print("\n<!--GATE-COMPLIANCE-->\n**compliance gate**\n")
        for r in report:
            icon = "✅" if r["verdict"] == "PASS" else "❌"
            lines = [f"- {icon} **{r['repo']}**"]
            lines += [f"  - {'✅' if c['ok'] else '❌'} {c['name']}"
                      + (f": {c['detail'][:200]}" if c.get("detail") and not c["ok"] else "")
                      for c in r["checks"]]
            print("\n".join(lines))
        print(f"\n`failures: {failures}` · advisory gate (Free tier) — binding at release via `ag release`\n<!--/GATE-COMPLIANCE-->")
    print(last_line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
