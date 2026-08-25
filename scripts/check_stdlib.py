#!/usr/bin/env python3
"""check_stdlib.py — enforce the BeanLabs stdlib-only contract.

Usage: check_stdlib.py DIR [DIR...]

Fails (exit 1) if any *.py under DIRs imports a module whose top-level package
is neither (a) Python stdlib (sys.stdlib_module_names) nor (b) first-party —
i.e., resolvable as a sibling module/package of the importing file or at the
repo root. Future/relative imports are exempt. Prints each violation as
file:line: module.
"""
import ast
import sys
from pathlib import Path

STDLIB = set(sys.stdlib_module_names)


def imports_of(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or node.module is None:  # relative / future
                continue
            yield node.module.split(".")[0], node.lineno


def main(dirs) -> int:
    bad = []
    files = [p for d in dirs for p in Path(d).rglob("*.py")
             if "__pycache__" not in p.parts]
    # first-party = any module stem / package dir name anywhere in scanned tree
    local = set()
    for d in dirs:
        d = Path(d)
        local |= {p.stem for p in d.rglob("*.py")}
        local |= {p.name for p in d.rglob("*")
                  if p.is_dir() and "__pycache__" not in p.parts
                  and (p / "__init__.py").exists()}
    for f in files:
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for mod, lineno in imports_of(tree):
            if mod not in STDLIB and mod not in local:
                bad.append(f"{f}:{lineno}: {mod}")
    if bad:
        print("stdlib-only VIOLATIONS:")
        print("\n".join(sorted(bad)))
        return 1
    print(f"stdlib-only OK ({len(files)} files scanned)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
