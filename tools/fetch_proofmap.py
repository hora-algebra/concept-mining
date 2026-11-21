#!/usr/bin/env python3
"""Download the declaration-level dependency data behind the CFSG proof map.

The site https://cfsg.axiommath.ai/proof-map loads, for every declaration of
the formalization, its kind, module, source line, length, and the lists of
declarations it uses and is used by. This script mirrors those files into a
local cache directory (never into this repository).

    python3 tools/fetch_proofmap.py --out ~/.cache/concept-mining/proofmap

Files fetched (about 70 MB in total):
    lean_meta.json            summary, folders, milestones
    lean/d/<k>.json.gz        rows for declarations 2048*k .. 2048*k+2047
    lean/n/<k>.json.gz        fully qualified names for the same range

The download is resumable: existing non-empty files are skipped.
Standard library only.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
import urllib.request

DEFAULT_BASE = "https://dbf6f4n718kwe.cloudfront.net/cfsg-site-v6/data/"
USER_AGENT = "concept-mining-fetch/0.1 (+https://github.com/hora-algebra/concept-mining)"


def get(url: str, dest: str, retries: int = 4) -> int:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return 0
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return len(data)
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise RuntimeError(f"{url}: {e}") from e
            time.sleep(2 ** attempt)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="cache directory")
    ap.add_argument("--base", default=DEFAULT_BASE, help="data base URL")
    ap.add_argument("--jobs", type=int, default=4, help="parallel downloads (keep small)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N chunks (for testing)")
    a = ap.parse_args()
    out = os.path.expanduser(a.out)

    get(a.base + "lean_meta.json", os.path.join(out, "lean_meta.json"))
    with open(os.path.join(out, "lean_meta.json")) as f:
        meta = json.load(f)
    n_chunks = (meta["points"] + meta["chunk"] - 1) // meta["chunk"]
    if a.limit is not None:
        n_chunks = min(n_chunks, a.limit)
    jobs = [(a.base + f"lean/{t}/{k}.json.gz", os.path.join(out, "lean", t, f"{k}.json.gz"))
            for k in range(n_chunks) for t in ("d", "n")]
    total, done = 0, 0
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for nbytes in ex.map(lambda j: get(*j), jobs):
            total += nbytes
            done += 1
            if done % 200 == 0:
                print(f"{done}/{len(jobs)} files, {total / 1e6:.1f} MB new", file=sys.stderr)
    print(f"commit {meta['commit']}: {meta['points']} declarations in {n_chunks} chunks -> {out}")


if __name__ == "__main__":
    main()
