#!/usr/bin/env python3
"""Standalone smoke test for the ZERO-SETUP launcher (P0 · 一键启动).

    .venv/Scripts/python.exe scripts/check_launch.py

This is OUR validation, NOT scripts/verify.py (owned by another agent).
It guards the P-21 regression: `python -m loom` must never dump a raw
traceback. It simulates a headless / double-click run of the CLI via
subprocess and asserts:

  (a) `python -m loom --help`        -> exit 0, stdout has "usage"/"loom",
                                        NO "Traceback".
  (b) `python -m loom` (stdin off)   -> exit code 2, NO "Traceback".
  (c) `python -m loom audit x.json`  -> non-zero OR friendly, NO "Traceback",
                                        stdout/stderr has "找不到" or "IR".

A clear PASS/FAIL summary is printed per check.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable  # run with the same (venv) interpreter that launched us


def run(args, **kw):
    return subprocess.run(
        [PY, "-m", "loom", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        **kw,
    )


def check(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if detail:
        print(f"        {detail}")
    return cond


def main() -> int:
    ok = True

    # (a) --help
    r = run(["--help"])
    out = (r.stdout or "") + (r.stderr or "")
    c = (
        r.returncode == 0
        and ("usage" in out.lower() or "loom" in out.lower())
        and "Traceback" not in out
    )
    ok &= check(
        "(a) python -m loom --help -> exit 0, has usage/loom, no Traceback",
        c,
        f"rc={r.returncode} traceback={'Traceback' in out}",
    )

    # (b) bare invocation, stdin closed (simulate double-click / headless)
    r = run([], stdin=subprocess.DEVNULL)
    out = (r.stdout or "") + (r.stderr or "")
    c = r.returncode == 2 and "Traceback" not in out
    ok &= check(
        "(b) python -m loom (stdin closed) -> exit 2, no Traceback",
        c,
        f"rc={r.returncode} traceback={'Traceback' in out}",
    )

    # (c) audit a missing file -> friendly, no Traceback, "找不到"/"IR"
    r = run(["audit", "no_such_file.json"])
    out = (r.stdout or "") + (r.stderr or "")
    c = (
        r.returncode != 0
        and "Traceback" not in out
        and ("找不到" in out or "IR" in out)
    )
    ok &= check(
        "(c) python -m loom audit no_such_file.json -> friendly, no Traceback, 找不到/IR",
        c,
        f"rc={r.returncode} traceback={'Traceback' in out}",
    )

    print()
    print("RESULT:", "ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
