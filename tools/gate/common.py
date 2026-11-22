"""Shared definitions of the contribution gate (standard library only).

A contribution pull request adds exactly one file,

    lean/patches/<target>/<name>.patch

a `git format-patch` mbox that rewrites Lean sources under CFSG/<target>/ of
the pinned upstream commit (lean/UPSTREAM). Everything else about the pull
request (ledger rows, points, labels, the merge) is produced by the gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATCH_PATH = re.compile(
    r"^lean/patches/(?P<target>[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*)/(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,120})\.patch$")
MAX_PATCH_BYTES = 30_000_000   # large dead-code deletions; the patch stays in git history
MIN_TOKENS = 50
MAX_OPEN_PER_AUTHOR = 5       # open, non-draft contribution pull requests of one author without write access
MAX_REVIEW_ROUNDS = 5         # AI review rounds (new heads reviewed) per pull request
STATUS_CONTEXT = "concept-mining/gate"
COMMENT_MARKER = "<!--concept-mining-gate-->"
META_PREFIX = "<!--concept-mining-verdict:v2 "
TARGET_MARKER = re.compile(r"<!--concept-mining-target:v1 (\{.*?\})-->", re.S)

# Files whose change must invalidate every verdict computed before it: the
# rules, the measuring tools and the baselines. A verdict records the
# fingerprint it was computed under; the gate merges only when main still has
# the same fingerprint.
GATE_FILES = [
    "lean/UPSTREAM",
    "tools/lean_lex.py",
    "tools/size.py",
    "tools/apply_patches.sh",
    "tools/site/scoring.py",
]
GATE_DIRS = ["tools/gate", "docs/review/rubrics"]


def candidate_of(name: str) -> str:
    """`0005-copies-foo.patch` or `0005-copies-foo` -> `copies-foo`."""
    base = name[:-6] if name.endswith(".patch") else name
    return re.sub(r"^\d+-", "", base)


def module_prefix(target: str) -> str:
    return "CFSG." + target.replace("/", ".")


def baseline_path(target: str, root: str = ROOT) -> str:
    return os.path.join(root, "data", "protected", target + ".json")


def supported_targets(root: str = ROOT) -> list[str]:
    out = []
    base = os.path.join(root, "data", "protected")
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.endswith(".json"):
                out.append(os.path.relpath(os.path.join(d, f[:-5]), base).replace(os.sep, "/"))
    return sorted(out)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def overlapping_targets(targets: list[str]) -> list[str]:
    """Pairs of open targets of which one contains the other (each Lean file
    must belong to at most one target)."""
    out = []
    for a in targets:
        for b in targets:
            if a != b and b.startswith(a + "/"):
                out.append(f"{a} contains {b}")
    return out


def series(target: str, root: str = ROOT) -> list[str]:
    """The target's patches on this checkout, in the order they are applied."""
    d = os.path.join(root, "lean", "patches", target)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.endswith(".patch") and os.path.isfile(os.path.join(d, f)))


def fingerprint(target: str, root: str = ROOT) -> str:
    """What a verdict for `target` depends on, besides the pull request itself:
    the gate's own files, the target's baseline, and main's patches and
    baselines of every open target."""
    h = hashlib.sha256()
    files = list(GATE_FILES) + [os.path.relpath(baseline_path(target, root), root),
                                os.path.join("data", "protected", target + ".txt")]
    for d in GATE_DIRS:
        for dd, _, fs in os.walk(os.path.join(root, d)):
            for f in fs:
                if f.startswith("test_") or "__pycache__" in dd:
                    continue
                files.append(os.path.relpath(os.path.join(dd, f), root))
    for p in sorted(set(files)):
        full = os.path.join(root, p)
        h.update(p.encode() + b"\0")
        h.update((_sha(_read(full)) if os.path.exists(full) else "absent").encode() + b"\n")
    # every target's patches: a target is checked against main as a whole
    # (the targets it imports carry their own patches), and the set of open
    # targets decides what counts as outside
    for t in supported_targets(root):
        for name in series(t, root):
            data = _read(os.path.join(root, "lean", "patches", t, name))
            h.update(f"patch {t}/{name} {_sha(data)}\n".encode())
        h.update(f"target {t} {_sha(_read(baseline_path(t, root)))}\n".encode())
    return h.hexdigest()


def parse_marker(body: str | None) -> dict:
    """The target marker of a pull request body (untrusted; display only)."""
    m = TARGET_MARKER.search(body or "")
    if not m:
        return {}
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return {}
    if not isinstance(d, dict):
        return {}
    clean = {}
    for k in ("candidate", "target", "agent"):
        v = d.get(k)
        if isinstance(v, str):
            clean[k] = re.sub(r"[^\w./:+-]", "", v)[:80]
    return clean


def read_meta(comment_body: str) -> dict | None:
    """The verdict record in one of the gate's comments, or None."""
    i = comment_body.rfind(META_PREFIX)
    if i < 0:
        return None
    j = comment_body.find("-->", i)
    if j < 0:
        return None
    try:
        return json.loads(comment_body[i + len(META_PREFIX):j])
    except ValueError:
        return None


def write_meta(meta: dict) -> str:
    # `--` cannot appear inside an HTML comment; the JSON never needs it
    text = json.dumps(meta, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return META_PREFIX + text.replace("--", "-\\u002d") + "-->"
