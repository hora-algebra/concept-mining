#!/usr/bin/env python3
"""Ask several models, in parallel, to refactor the same Lean files.

A task (one line of a JSONL file) names the files to rewrite and what to do:

    {"id": "pcore-merge-01", "files": ["CFSG/Foo.lean", ...],
     "instruction": "Replace CFSG.Open.pCoreOf by CFSG.pCore ...",
     "context_files": ["CFSG/ThirdParty/.../PCore/Defs.lean"]}

For every task, model and attempt, the runner sends the files and the
instruction, and stores the reply (complete new file contents) with the token
counts and the price. The compile check and the size measurement are done
afterwards by judge.py, so that a model never grades itself.

    # cost estimate only, no API call
    python3 tools/trials/run_trials.py --tasks tasks.jsonl --root ~/Codes/upstream/cfsg \
        --models anthropic/claude-sonnet-5-5 openai/gpt-6.2-sol --attempts 3 --dry-run

    # real run, stops before spending more than the budget
    .venv/bin/python tools/trials/run_trials.py ... --budget-usd 5 --out out/trials

The budget is checked against the worst case of the next request before it
is sent, so the total never exceeds --budget-usd.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SYSTEM = """You refactor Lean 4 code in a large formal proof library (Mathlib-based).
Goal: make the given files shorter while keeping every public declaration that other
files use, with the same name and the same statement, and the same axioms.
You may introduce new definitions and lemmas. Do not use sorry, admit, native_decide,
or new axioms. Reply with the complete new contents of every file you change, each in
a block of the form
=== FILE: <path> ===
<contents>
=== END ===
and nothing else."""

CHARS_PER_TOKEN = 3.2  # Lean source is symbol-heavy; measured tokenizers vary


def load_prices():
    with open(os.path.join(HERE, "pricing.json")) as f:
        return json.load(f)["models"]


def build_prompt(task, root):
    parts = [f"Task: {task['instruction']}\n"]
    for label, key in (("Context (do not change)", "context_files"), ("File to refactor", "files")):
        for p in task.get(key, []):
            with open(os.path.join(root, p), encoding="utf-8") as f:
                parts.append(f"--- {label}: {p} ---\n{f.read()}\n")
    return "\n".join(parts)


def price(prices, spec, inp, cached, out, batch=False):
    p = prices[spec]
    i, o = (p["batch_input"], p["batch_output"]) if batch else (p["input"], p["output"])
    return (inp * i + cached * p["cached"] + out * o) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--root", required=True, help="checkout of AxiomMath/CFSG")
    ap.add_argument("--models", nargs="+", required=True, help="vendor/model as in pricing.json")
    ap.add_argument("--attempts", type=int, default=1)
    ap.add_argument("--max-output", type=int, default=32000)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--budget-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="out/trials")
    a = ap.parse_args()
    prices = load_prices()
    for m in a.models:
        if m not in prices:
            sys.exit(f"no price for {m} in pricing.json")
    with open(a.tasks) as f:
        tasks = [json.loads(l) for l in f if l.strip()]
    root = os.path.expanduser(a.root)
    prompts = {t["id"]: build_prompt(t, root) for t in tasks}

    # estimate: input from characters, output assumed equal to the refactored
    # files (bounded by --max-output); worst case uses --max-output
    rows, est_total, worst_total = [], 0.0, 0.0
    for t in tasks:
        tin = (len(SYSTEM) + len(prompts[t["id"]])) / CHARS_PER_TOKEN
        tout = min(a.max_output, sum(os.path.getsize(os.path.join(root, p)) for p in t["files"]) / CHARS_PER_TOKEN)
        for m in a.models:
            e = price(prices, m, tin, 0, tout) * a.attempts
            w = price(prices, m, tin, 0, a.max_output) * a.attempts
            rows.append((t["id"], m, int(tin), int(tout), e, w))
            est_total += e
            worst_total += w
    print(f"{len(tasks)} tasks x {len(a.models)} models x {a.attempts} attempts")
    print(f"estimated cost {est_total:.2f} USD (worst case {worst_total:.2f} USD, synchronous prices)")
    if a.dry_run:
        for r in rows:
            print(f"  {r[0]:<28} {r[1]:<30} in~{r[2]:>7} out~{r[3]:>6}  {r[4]:7.3f} USD (max {r[5]:.3f})")
        return
    if a.budget_usd <= 0:
        sys.exit("refusing to call any API without --budget-usd")

    from providers import make
    os.makedirs(a.out, exist_ok=True)
    spent = [0.0]
    lock = threading.Lock()
    clients = {}

    def job(t, m, k):
        tin = (len(SYSTEM) + len(prompts[t["id"]])) / CHARS_PER_TOKEN
        worst = price(prices, m, tin, 0, a.max_output)
        with lock:
            if spent[0] + worst > a.budget_usd:
                return {"task": t["id"], "model": m, "attempt": k, "skipped": "budget"}
            spent[0] += worst  # reserve, corrected below
            if m not in clients:
                clients[m] = make(m, a.effort)
        prov, model = clients[m]
        t0 = time.time()
        try:
            c = prov.complete(model, SYSTEM, prompts[t["id"]], a.max_output)
        except Exception as e:  # noqa: BLE001
            with lock:
                spent[0] -= worst
            return {"task": t["id"], "model": m, "attempt": k, "error": f"{type(e).__name__}: {e}"[:500]}
        cost = price(prices, m, c.input_tokens, c.cached_tokens, c.output_tokens)
        with lock:
            spent[0] += cost - worst
        name = f"{t['id']}__{m.replace('/', '_')}__{k}.txt"
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            f.write(c.text)
        return {"task": t["id"], "model": m, "attempt": k, "reply": name, "stop": c.stop,
                "input_tokens": c.input_tokens, "cached_tokens": c.cached_tokens,
                "output_tokens": c.output_tokens, "cost_usd": round(cost, 5),
                "seconds": round(time.time() - t0, 1), "served_by": c.raw_model}

    work = [(t, m, k) for t in tasks for m in a.models for k in range(a.attempts)]
    with open(os.path.join(a.out, "runs.jsonl"), "a") as log, cf.ThreadPoolExecutor(a.jobs) as ex:
        for res in ex.map(lambda w: job(*w), work):
            log.write(json.dumps(res) + "\n")
            log.flush()
            print(json.dumps(res))
    print(f"spent {spent[0]:.4f} USD")


if __name__ == "__main__":
    main()
