#!/usr/bin/env python3
"""Mechanical pass/fail and shrinkage for the replies collected by run_trials.py.

A reply passes when, after writing its files into the checkout,

  1. `lake build` succeeds for every module in the task's "check_modules"
     (the modules that import the changed files, up to the pilot's top);
  2. for every declaration in the task's "protected" list, `#check @name`
     and `#print axioms name` print exactly what they printed before;
  3. the new files contain no `sorry`, `admit`, `native_decide` or `axiom`.

Shrinkage is measured on the changed files in Lean tokens (tools/size.py; the
measure formatting cannot change), code lines and bytes. The original files are restored after every reply, so
replies are judged one at a time.

    python3 tools/trials/judge.py --root ~/Codes/upstream/cfsg --tasks tasks.jsonl --runs out/trials
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from size import tokens  # noqa: E402

BLOCK = re.compile(r"^=== FILE: (?P<path>\S+) ===\n(?P<body>.*?)^=== END ===", re.M | re.S)
FORBIDDEN = re.compile(r"\b(sorry|admit|native_decide)\b|^\s*axiom\s", re.M)
COMMENT = re.compile(r"/-.*?-/|--[^\n]*", re.S)


def code_lines(src: str) -> int:
    return sum(1 for l in COMMENT.sub("", src).splitlines() if l.strip())


def probe(root: str, names: list[str], timeout: int) -> str:
    if not names:
        return ""
    body = "\n".join(f"#check @{n}\n#print axioms {n}" for n in names)
    with tempfile.NamedTemporaryFile("w", suffix=".lean", dir=root, delete=False) as f:
        f.write(PROBE_HEADER + body + "\n")
        path = f.name
    try:
        r = subprocess.run(["lake", "env", "lean", path], cwd=root, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    finally:
        os.unlink(path)


PROBE_HEADER = ""  # set per task from its "probe_imports"


def main() -> None:
    global PROBE_HEADER
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    tasks = {}
    with open(a.tasks) as f:
        for l in f:
            if l.strip():
                t = json.loads(l)
                tasks[t["id"]] = t
    runs = [json.loads(l) for l in open(os.path.join(a.runs, "runs.jsonl")) if l.strip()]
    baseline: dict[str, str] = {}
    out = open(os.path.join(a.runs, "judged.jsonl"), "a")
    for run in runs:
        if "reply" not in run:
            continue
        t = tasks[run["task"]]
        PROBE_HEADER = "".join(f"import {m}\n" for m in t.get("probe_imports", []))
        if t["id"] not in baseline:
            baseline[t["id"]] = probe(root, t.get("protected", []), a.timeout)
        reply = open(os.path.join(a.runs, run["reply"]), encoding="utf-8").read()
        files = {m["path"]: m["body"] for m in BLOCK.finditer(reply)}
        res = dict(run, passed=False)
        if not files:
            res["reason"] = "no files in reply"
        elif any(FORBIDDEN.search(b) for b in files.values()):
            res["reason"] = "forbidden construct"
        elif not all(p in t["files"] or p.startswith(t.get("new_file_prefix", "\0")) for p in files):
            res["reason"] = "touched a file outside the task"
        else:
            saved = {}
            try:
                before_lines = before_bytes = after_lines = after_bytes = before_tok = after_tok = 0
                for p, body in files.items():
                    full = os.path.join(root, p)
                    old = open(full, encoding="utf-8").read() if os.path.exists(full) else ""
                    saved[full] = old if os.path.exists(full) else None
                    before_lines += code_lines(old)
                    before_tok += tokens(old)
                    before_bytes += len(old.encode())
                    after_lines += code_lines(body)
                    after_tok += tokens(body)
                    after_bytes += len(body.encode())
                    with open(full, "w", encoding="utf-8") as f:
                        f.write(body)
                b = subprocess.run(["lake", "build", *t["check_modules"]], cwd=root,
                                   capture_output=True, text=True, timeout=a.timeout)
                if b.returncode != 0:
                    res["reason"] = "build failed"
                    res["log_tail"] = (b.stdout + b.stderr)[-2000:]
                elif probe(root, t.get("protected", []), a.timeout) != baseline[t["id"]]:
                    res["reason"] = "protected statement or axioms changed"
                else:
                    res["passed"] = True
                res.update(code_lines_before=before_lines, code_lines_after=after_lines,
                           bytes_before=before_bytes, bytes_after=after_bytes,
                           shrink_lines=before_lines - after_lines, shrink_tokens=before_tok - after_tok)
                if res["passed"] and res["shrink_lines"] > 0:
                    res["usd_per_100_lines"] = round(100 * run["cost_usd"] / res["shrink_lines"], 4)
            except subprocess.TimeoutExpired:
                res["reason"] = "timeout"
            finally:
                for full, old in saved.items():
                    if old is None:
                        os.unlink(full)
                    else:
                        with open(full, "w", encoding="utf-8") as f:
                            f.write(old)
        out.write(json.dumps(res) + "\n")
        out.flush()
        print(json.dumps({k: res.get(k) for k in ("task", "model", "attempt", "passed", "reason", "shrink_lines", "cost_usd", "usd_per_100_lines")}))


if __name__ == "__main__":
    main()
