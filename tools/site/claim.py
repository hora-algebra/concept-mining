#!/usr/bin/env python3
"""Claims on candidates, so that two agents do not work on the same thing.

A claim is a lease stored as the Git ref refs/claims/<key>, pointing at an
empty commit whose message is JSON:

    {"schema": "concept-mining-claim/v1", "key": "C02", "owner": "<unique id>",
     "login": "<GitHub login>", "agent": "<model or human>",
     "acquired_at": <unix time>, "expires_at": <unix time>}

Every write is a compare-and-swap (git push --force-with-lease), so exactly one
claimant wins. A claim past expires_at is free to take over. Claims only avoid
duplicated work; correctness never depends on them.

    python3 tools/site/claim.py acquire C02 --owner "$(hostname)-$RANDOM" --login octocat --agent anthropic/claude-sonnet-5-5 --ttl 3h
    python3 tools/site/claim.py renew   C02 --owner ... --ttl 3h
    python3 tools/site/claim.py release C02 --owner ...
    python3 tools/site/claim.py list [--json]

Exit status: 0 on success, 3 if someone else holds a live claim, 1 on errors.
Standard library only; needs git and push access to the remote (default origin).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SKEW = 60


def git(*args: str, input: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], input=input, capture_output=True, text=True, check=check)


def ttl_seconds(s: str) -> int:
    m = re.fullmatch(r"(\d+)([smhd]?)", s)
    if not m:
        raise SystemExit(f"bad --ttl {s!r}; use e.g. 90m or 3h")
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def remote_claims(remote: str) -> dict[str, tuple[str, dict]]:
    """key -> (oid, lease) for every claim ref on the remote."""
    r = git("ls-remote", remote, "refs/claims/*")
    out = {}
    refs = [l.split("\t") for l in r.stdout.splitlines() if l.strip()]
    if refs:
        git("fetch", "--quiet", remote, *[f"+{ref}:refs/remotes/{remote}-claims/{ref.split('/')[-1]}" for _, ref in refs])
    for oid, ref in refs:
        key = ref.split("/")[-1]
        msg = git("log", "-1", "--format=%B", oid, check=False).stdout
        try:
            lease = json.loads(msg)
        except json.JSONDecodeError:
            lease = {"key": key, "owner": "?", "expires_at": 0, "error": "unreadable lease"}
        out[key] = (oid, lease)
    return out


def make_lease(key: str, a: argparse.Namespace, acquired: int | None = None) -> str:
    now = int(time.time())
    lease = {"schema": "concept-mining-claim/v1", "key": key, "owner": a.owner, "login": a.login or "",
             "agent": a.agent or "", "acquired_at": acquired or now, "expires_at": now + ttl_seconds(a.ttl)}
    msg = json.dumps(lease, ensure_ascii=False)
    env_args = ["-c", "user.name=concept-mining-claim", "-c", "user.email=claims@invalid"]
    oid = subprocess.run(["git", *env_args, "commit-tree", EMPTY_TREE, "-m", msg],
                         capture_output=True, text=True, check=True).stdout.strip()
    return oid


def cas(remote: str, key: str, old: str, new: str) -> bool:
    ref = f"refs/claims/{key}"
    src = f"{new}:{ref}" if new else f":{ref}"
    r = git("push", "--quiet", f"--force-with-lease={ref}:{old}", remote, src, check=False)
    return r.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["acquire", "renew", "release", "list"])
    ap.add_argument("key", nargs="?")
    ap.add_argument("--owner", help="globally unique id of this worker, e.g. <hostname>-<uuid>")
    ap.add_argument("--login", help="GitHub login of the contributor")
    ap.add_argument("--agent", help="model or tool doing the work, or 'human'")
    ap.add_argument("--ttl", default="3h")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    now = time.time()
    claims = remote_claims(a.remote)
    if a.cmd == "list":
        live = [dict(l, oid=o, live=l.get("expires_at", 0) > now - SKEW) for o, l in claims.values()]
        if a.json:
            print(json.dumps(live, ensure_ascii=False, indent=1))
        else:
            for l in live:
                left = int(l.get("expires_at", 0) - now) // 60
                print(f"{l.get('key')}\t{l.get('login') or l.get('owner')}\t{l.get('agent', '')}\t"
                      f"{'expires in ' + str(left) + ' min' if l['live'] else 'expired'}")
        return
    if not a.key or not KEY_RE.match(a.key) or not a.owner:
        raise SystemExit("need a key (letters, digits, . _ -) and --owner")
    cur = claims.get(a.key)
    if a.cmd == "acquire":
        if cur and cur[1].get("expires_at", 0) > now - SKEW and cur[1].get("owner") != a.owner:
            print(f"held by {cur[1].get('login') or cur[1].get('owner')} until {int(cur[1]['expires_at'])}")
            sys.exit(3)
        ok = cas(a.remote, a.key, cur[0] if cur else "", make_lease(a.key, a))
    elif a.cmd == "renew":
        if not cur or cur[1].get("owner") != a.owner:
            print("not held by this owner"); sys.exit(3)
        ok = cas(a.remote, a.key, cur[0], make_lease(a.key, a, cur[1].get("acquired_at")))
    else:
        if not cur:
            return
        if cur[1].get("owner") != a.owner:
            print("not held by this owner"); sys.exit(3)
        ok = cas(a.remote, a.key, cur[0], "")
    if not ok:
        print("lost the race: the claim changed while we were writing; list again and decide afresh")
        sys.exit(3)
    print(f"{a.cmd} {a.key}: ok")


if __name__ == "__main__":
    main()
