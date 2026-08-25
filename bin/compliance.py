#!/usr/bin/env python3
"""compliance.py — deterministic PR/push compliance gate for BeanLabs repos.

Runs, for one repo (or every active manifest row):
  1. docs standard   (README + AGENTS.md, sections match manifest entrypoints)
  2. unit entrypoint (exact command from qa-kit manifest)
  3. e2e entrypoint  (--full only; app-tier flows)

Output: human table + machine-readable JSON verdict on stdout's last line
(consumed by the sticky-comment/report step of the gate workflow and by the
hub's compliance receipt).

Exit code: number of failed checks capped at 1... i.e. 0 = green, 1 = any fail.
Advisory Phase 1: GitHub Free cannot block merges on private repos; this
gate's red ❌ becomes binding via `ag release --require-pr-green` (Phase 2).
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

QA_KIT = Path(__file__).resolve().parent.parent
MANIFEST = QA_KIT / "manifest.json"


def expand(p):
    return Path(p).expanduser()


def sh(cmd, cwd):
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True,
                           text=True, timeout=900)
        ok = p.returncode == 0
        tail = ((p.stdout or "") + "\n" + (p.stderr or ""))[-800:]
    except FileNotFoundError as e:
        ok, tail = False, f"entrypoint missing: {e}"
    except subprocess.TimeoutExpired:
        ok, tail = False, "timeout 900s"
    return {"ok": ok, "secs": round(time.monotonic() - t0, 1), "tail": tail.strip()}


def docs_check(root, unit_cmd):
    problems = []
    ag, rd = root / "AGENTS.md", root / "README.md"
    if not ag.exists():
        return ["missing AGENTS.md"]
    text = ag.read_text()
    if "## Test commands" not in text:
        problems.append("AGENTS.md lacks '## Test commands'")
    if unit_cmd and " ".join(unit_cmd) not in text.replace("`", ""):
        problems.append("AGENTS.md does not state manifest unit cmd")
    if not rd.exists():
        problems.append("missing README.md")
    elif "AGENTS.md" not in rd.read_text():
        problems.append("README does not reference AGENTS.md")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None, help="repo name from manifest (default: all active)")
    ap.add_argument("--full", action="store_true", help="include e2e tier")
    ap.add_argument("--markdown", action="store_true", help="emit markdown summary block")
    args = ap.parse_args()

    man = json.loads(MANIFEST.read_text())
    repos = [r for r in man["repos"]
             if r.get("status") in ("active", "unit-only")
             and (args.repo is None or r["name"] == args.repo)]
    if args.repo and not repos:
        print(f"unknown or non-active repo: {args.repo}", file=sys.stderr)
        return 2

    report = []
    failures = 0
    for repo in repos:
        root = expand(repo["path"])
        unit_cmd = (repo.get("unit") or {}).get("cmd") or []
        checks = []

        problems = docs_check(root, unit_cmd)
        checks.append({"name": "docs", "ok": not problems,
                       "detail": "; ".join(problems)})

        if unit_cmd:
            r = sh(unit_cmd, root)
            checks.append({"name": "unit", "ok": r["ok"], "secs": r["secs"],
                           "detail": None if r["ok"] else r["tail"][-400:]})
        else:
            checks.append({"name": "unit", "ok": False, "detail": "no unit entrypoint registered"})

        e2e = repo.get("e2e") or {}
        if args.full and e2e.get("cmd"):
            r = sh(e2e["cmd"], root)
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

    last_line = json.dumps({"gate": "compliance", "failures": failures,
                            "repos": report}, separators=(",", ":"))
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
