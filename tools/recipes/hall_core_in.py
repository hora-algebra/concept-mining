"""Concept: the Hall core of a subgroup M, as a subgroup of the ambient group.

Five files defined the same `(hallCore M).map M.subtype` under different names
(hallCoreIn, Prep03/06/09.hallCoreIn, Prep05.hallCoreOf). This keeps one
definition next to `hallCore` and points every use at it.
"""
import os, re, sys
root = os.path.expanduser(sys.argv[1])
FT = os.path.join(root, "CFSG/FeitThompson")

def edit(rel, f):
    p = os.path.join(FT, rel)
    s = open(p, encoding="utf-8").read()
    t = f(s)
    if t != s:
        open(p, "w", encoding="utf-8").write(t)

CANON = '''
/-- The Hall core of a subgroup `M`, seen as a subgroup of the ambient group. -/
@[expose]
def hallCoreIn (M : Subgroup G) : Subgroup G := (hallCore M).map M.subtype

theorem hallCoreIn_eq (M : Subgroup G) : hallCoreIn M = (hallCore M).map M.subtype := (rfl)

theorem hallCoreIn_le (M : Subgroup G) : hallCoreIn M ≤ M := Subgroup.map_subtype_le _

end CFSG.FeitThompson
'''
edit("Definitions/NormalSylowHallCore.lean", lambda s: s if "def hallCoreIn" in s else s.rstrip()[:-len("end CFSG.FeitThompson")].rstrip() + "\n" + CANON)

# remove the copies and their two basic lemmas
DROP = [
    r"@\[expose\]\ndef hallCoreIn \(M : Subgroup G\) : Subgroup G := [^\n]*\n\n?",
    r"@\[expose\]\ndef hallCoreOf \(M : Subgroup G\) : Subgroup G := [^\n]*\n\n?",
    r"theorem hallCore(In|Of)_(eq|def) \(M : Subgroup G\) :\s+hallCore(In|Of) M = [^\n]*:= \(rfl\)\n\n?",
    r"theorem hallCore(In|Of)_le \(M : Subgroup G\) : hallCore(In|Of) M ≤ M := Subgroup.map_subtype_le _\n\n?",
]
for rel in ["Statements/FittingOverlapKappaStatements.lean", "Statements/TauThirteenTypeIStatements.lean",
            "Statements/SignalizerTypeStatements.lean", "Statements/TypeIIIIVExclusionStatements.lean",
            "Statements/KappaCandidateStatements.lean"]:
    def f(s):
        for d in DROP:
            s = re.sub(d, "", s)
        return s
    edit(rel, f)

RENAME = [
    (r"\bPrep05\.hallCoreOf_(eq|le)\b", r"hallCoreIn_\1"),
    (r"\bPrep0[369]\.hallCoreIn_(eq|le)\b", r"hallCoreIn_\1"),
    (r"\b(Prep0[369]\.)?hallCoreIn_def\b", "hallCoreIn_eq"),
    (r"\bhallCoreOf_(eq|le)\b", r"hallCoreIn_\1"),
    (r"\bPrep05\.hallCoreOf\b", "hallCoreIn"),
    (r"\bPrep0[369]\.hallCoreIn\b", "hallCoreIn"),
    (r"\bhallCoreOf\b", "hallCoreIn"),
]
for d, _, fs in os.walk(FT):
    for fn in fs:
        if fn.endswith(".lean"):
            rel = os.path.relpath(os.path.join(d, fn), FT)
            def f(s):
                for a, b in RENAME:
                    s = re.sub(a, b, s)
                return s
            edit(rel, f)

# --- second pass: names that no longer exist in the Prep namespaces, and
# bridges between copies that have become `hallCoreIn M = hallCoreIn M`
GONE = {"hallCoreIn", "hallCoreIn_eq", "hallCoreIn_le"}

def fix_open(s):
    def repl(m):
        items = [x for x in m.group(2).split() if x not in GONE]
        return f"{m.group(1)}({' '.join(items)})" if items else ""
    s = re.sub(r"(open (?:_root_\.)?(?:CFSG\.FeitThompson\.)?Prep0\d\s*)\(([^)]*)\)", repl, s)
    return re.sub(r"\nopen\s*\n", "\n", s)

HEAD = re.compile(r"^(?P<ind>[ \t]*)(?P<kw>(?:private )?theorem|have) (?P<name>[\w'.₀-₉]+)")
STMT = re.compile(r"^(?:\s*(?:\{[^{}]*\}|\[[^\[\]]*\]|\([^()]*\)))*\s*:\s*(?:∀ \w+ : Subgroup \w+, )?"
                  r"(?:_root_\.)?(?:CFSG\.FeitThompson\.)?hallCoreIn (?P<a>[\w₀-₉]+) = (?:_root_\.)?(?:CFSG\.FeitThompson\.)?hallCoreIn (?P=a)\s*:=")

def drop_trivial(s):
    """Remove theorems and `have`s stating `hallCoreIn M = hallCoreIn M`."""
    lines = s.split("\n")
    out, names, i = [], [], 0
    while i < len(lines):
        m = HEAD.match(lines[i])
        if m:
            rest = "\n".join(lines[i:i + 4])[m.end():]
            if STMT.match(rest):
                ind = len(m.group("ind").expandtabs())
                j = i + 1
                while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind):
                    j += 1
                while j > i + 1 and not lines[j - 1].strip():
                    j -= 1
                if m.group("kw") == "have":
                    # a local fact: drop its uses up to the end of the declaration
                    k = j
                    while k < len(lines) and not (lines[k][:1].strip()):
                        k += 1
                    seg = drop_uses("\n".join(lines[j:k]), m.group("name"))
                    lines[j:k] = seg.split("\n")
                else:
                    names.append(m.group("name"))
                i = j
                if i < len(lines) and not lines[i].strip() and out and not out[-1].strip():
                    i += 1
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), names

LIST = re.compile(r"(?P<tac>rw|rwa|simp only|simp|simpa|erw|nth_rw \d+)(?P<sp> ?)\[(?P<body>[^\[\]]*)\]")


def remove_items(body, bad):
    """Remove the list items for which bad(item) holds, keeping the layout."""
    parts = re.split(r"(,\s*)", body)  # items at even positions, separators at odd
    items, seps = parts[0::2], parts[1::2]
    keep = [k for k, x in enumerate(items) if not bad(x.strip(), [y.strip() for y in items[:k]])]
    if len(keep) == len(items):
        return body
    out = ""
    for n, k in enumerate(keep):
        lead = re.match(r"\s*", items[k]).group(0) if n == 0 else ""
        out += (lead + items[k].strip() if n == 0 else items[k].strip())
        if n + 1 < len(keep):
            out += seps[k] if k < len(seps) else ", "
    return out


def edit_lists(s, bad):
    def lst(m):
        body = remove_items(m.group("body"), bad)
        if body == m.group("body"):
            return m.group(0)
        if body.strip():
            return f"{m.group('tac')}{m.group('sp')}[{body}]"
        if m.group("tac") == "rwa":
            return "\0RWA\0"
        return {"simpa": "simpa", "simp": "simp"}.get(m.group("tac"), "\0DROP\0")
    s = LIST.sub(lst, s)
    s = re.sub(r"\0RWA\0 at ([\w₀-₉']+)", r"exact \1", s)
    s = s.replace("\0RWA\0", "assumption")
    s = re.sub(r"^[ \t]*\0DROP\0[^\n]*\n", "", s, flags=re.M)
    s = re.sub(r"\0DROP\0( at [^\n;)]*)?; ", "", s)
    s = re.sub(r"\0DROP\0( at [^\n;)]*)?(?=\s*[)\],])", "rfl", s)
    return re.sub(r"\0DROP\0( at [^\n;)]*)?", "skip", s)


def drop_uses(s, name):
    item = re.compile(rf"(?:← ?)?{re.escape(name)}(?: [\w₀-₉]+)?")
    s = edit_lists(s, lambda x, prev: bool(item.fullmatch(x)))
    return re.sub(rf"\(?{re.escape(name)} [\w₀-₉]+\)?(?:\.symm)? ▸ ", "", s)


def dedup_lists(s):
    """`rw [hallCoreIn_eq, hallCoreIn_eq]` came from two different lemmas."""
    norm = lambda x: x.replace("CFSG.FeitThompson.", "")
    return edit_lists(s, lambda x, prev: bool(prev) and norm(x).startswith("hallCoreIn_")
                      and norm(prev[-1]) == norm(x))


files = []
for d, _, fs in os.walk(FT):
    for fn in fs:
        if fn.endswith(".lean"):
            files.append(os.path.relpath(os.path.join(d, fn), FT))
dropped = set()
for rel in files:
    def f(s):
        s = fix_open(s)
        s, names = drop_trivial(s)
        dropped.update(nm.rsplit(".", 1)[-1] for nm in names)
        return s
    edit(rel, f)
# bridges removed by an earlier run of this recipe (keeps it idempotent)
dropped |= {"hallCoreIn_eq_hallCoreOf", "hallCoreOf_eq_hallCoreIn", "prep03_hallCoreIn_eq",
            "prep06_hallCoreIn_eq_hallCoreOf", "prep06_hallCoreIn_eq_hallCoreOf'", "prep09_hallCoreIn_eq"}
dropped -= GONE
for rel in files:
    def f(s):
        for nm in dropped:
            s = drop_uses(s, nm)
        return s
    edit(rel, f)

# places where two copies were rewritten separately and one rewrite is now
# redundant, found by building
FIXUPS = [
    ("Representations/TypeThreeFourCorePrimeGroup.lean",
     "rw [hKF, ← hHCF, hHg, hallCoreIn_eq, hallCoreIn_eq]", "rw [hKF, ← hHCF, hHg, hallCoreIn_eq]"),
    ("Representations/TypeThreeFourCorePrimeGroup.lean",
     "  · rw [show hallCoreIn M = Hg from by rw [hHg, hallCoreIn_eq, hallCoreIn_eq], ha]", "  · rw [ha]"),
    ("Representations/TypeIINonfrobeniusCrossedColumnData.lean",
     "CFSG.FeitThompson.Prep09.centIn_def, hallCoreIn_eq,\n    CFSG.FeitThompson.hallCoreIn_eq]",
     "CFSG.FeitThompson.Prep09.centIn_def, hallCoreIn_eq]"),
    ("Representations/FrobeniusCoherentImageOtherTypeIBlocks.lean",
     "    Prep09.centIn, centralizer_coe_zpowers]\n  rfl\n", "    Prep09.centIn, centralizer_coe_zpowers]\n"),
]
for rel, a, b in FIXUPS:
    edit(rel, lambda s: s.replace(a, b, 1))
# a bullet whose only rewrite disappeared
for rel in files:
    edit(rel, lambda s: re.sub(r"(·) skip\n\s+", r"\1 ", s))
for rel, a, b in []:
    edit(rel, lambda s: s.replace(a, b, 1))
