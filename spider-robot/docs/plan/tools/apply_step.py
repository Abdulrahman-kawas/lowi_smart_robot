#!/usr/bin/env python3
"""Writes the files of one step of 04_EXECUTION_PLAN.md and verifies each by SHA-256.

Usage, from the repository root:  python3 spider-robot/docs/plan/tools/apply_step.py S07
"""
import hashlib
import pathlib
import re
import sys

PLAN = pathlib.Path("spider-robot/docs/plan/04_EXECUTION_PLAN.md")
FENCE = "`" * 5
BEGIN = re.compile(r"^<!-- BEGIN-FILE path=(\S+) mode=(new|replace|patch) sha256=([0-9a-f]{64}) -->$")


def fail(message):
    print(f"STOP: {message}")
    sys.exit(1)


def read_block(lines, i):
    """lines[i] must open a fence. Returns (text, index after the closing fence)."""
    if not lines[i].startswith(FENCE):
        fail(f"expected a code fence at plan line {i + 1}")
    end = lines.index(FENCE, i + 1)
    body = lines[i + 1:end]
    return ("\n".join(body) + "\n") if body else "", end + 1


def main():
    if len(sys.argv) != 2:
        fail("give one step id, for example S07")
    step = sys.argv[1]
    lines = PLAN.read_text("utf-8").split("\n")
    start_mark, end_mark = f"<!-- BEGIN-STEP {step} -->", f"<!-- END-STEP {step} -->"
    if start_mark not in lines or end_mark not in lines:
        fail(f"step {step} is not in the plan")
    i, end = lines.index(start_mark), lines.index(end_mark)
    count = 0
    while i < end:
        match = BEGIN.match(lines[i])
        if not match:
            i += 1
            continue
        path, mode, sha = match.groups()
        target = pathlib.Path(path)
        i += 1
        if mode in ("new", "replace"):
            text, i = read_block(lines, i)
        else:
            if not target.exists():
                fail(f"{path} does not exist, but this step changes it")
            text = target.read_text("utf-8")
            while lines[i] == "<!-- SEARCH -->":
                search, i = read_block(lines, i + 1)
                if lines[i] != "<!-- REPLACE -->":
                    fail(f"expected REPLACE at plan line {i + 1}")
                replace, i = read_block(lines, i + 1)
                found = text.count(search)
                if found != 1:
                    fail(f"{path}: search text occurs {found} times, expected 1:\n{search[:300]}")
                text = text.replace(search, replace)
        if lines[i] != "<!-- END-FILE -->":
            fail(f"expected END-FILE at plan line {i + 1}")
        i += 1
        got = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if got != sha:
            fail(f"{path}: result does not match the plan (sha256 {got})")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, "utf-8")
        print(f"OK {mode:7} {path}")
        count += 1
    print(f"{step}: {count} files written and verified")


if __name__ == "__main__":
    main()
