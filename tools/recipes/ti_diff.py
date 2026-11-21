"""Concept: the cyclic TI difference set of (W, W1, W2) is a TI subset of G with
stabilizer W.

Many statements assumed the two halves of this property as separate
hypotheses, each restating the difference set three or four times. This adds
one predicate `IsTIDiff W W1 W2` next to `IsCyclicTIPair` (which contains it)
and replaces every such pair of hypotheses by one hypothesis.
"""
import os, re, sys
root = os.path.expanduser(sys.argv[1])
dry = "--dry" in sys.argv
FT = os.path.join(root, "CFSG/FeitThompson")

DEF = '''/-- The cyclic TI difference set of `W1, W2` in `W` is a TI subset of `G` whose
stabilizer under conjugation is `W`. -/
structure IsTIDiff (W W1 W2 : Subgroup G) : Prop where
  setOf_conj_eq_self : {g : G | (fun x => g⁻¹ * x * g) '' cyclicTIDiff W W1 W2
    = cyclicTIDiff W W1 W2} = (W : Set G)
  inter_eq_empty : ∀ g ∉ W,
    (fun x => g⁻¹ * x * g) '' cyclicTIDiff W W1 W2 ∩ cyclicTIDiff W W1 W2 = ∅

'''

B0 = r"[^()]"
BAL = r"\((?:[^()]|\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\))*\)"
ARG = rf"(?:{BAL}|[\w₀-₉'.]+)"
STAB = re.compile(rf"\{{g : G \| \(fun x => g⁻¹ \* x \* g\) '' cyclicTIDiff (?P<A>{ARG}) (?P<B>{ARG}) (?P<C>{ARG}) "
                  rf"= cyclicTIDiff (?P=A) (?P=B) (?P=C)\}} = \(\((?P<A2>.+) : Subgroup G\) : Set G\)$")
DISJ = re.compile(rf"∀ g ∉ (?P<A>.+), \(fun x => g⁻¹ \* x \* g\) '' cyclicTIDiff (?P<A1>{ARG}) (?P<B>{ARG}) (?P<C>{ARG}) "
                  rf"∩ cyclicTIDiff (?P=A1) (?P=B) (?P=C) = ∅$")


def strip_parens(x):
    x = x.strip()
    while x.startswith("(") and x.endswith(")") and re.fullmatch(BAL, x):
        x = x[1:-1].strip()
    return x


def binder_at(s, i):
    """The binder starting with '(' at i: (end, name, type) or None."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                inner = s[i + 1:j]
                m = re.match(r"\s*([\w₀-₉']+)\s*:\s*", inner)
                if not m:
                    return None
                return j + 1, m.group(1), re.sub(r"\s+", " ", inner[m.end():]).strip()
    return None


def decl_end(s, i):
    m = re.compile(r"\n(?=\S)").search(s, i)
    while m and s[m.end():m.end() + 1] in (")",):
        m = re.compile(r"\n(?=\S)").search(s, m.end())
    return m.start() if m else len(s)


def convert(s):
    out, pos, count = [], 0, 0
    for m in re.finditer(r"\((?P<n>[\w₀-₉']+) : \{g : G \| \(fun x => g⁻¹ \* x \* g\) ''", s):
        if m.start() < pos:
            continue
        b1 = binder_at(s, m.start())
        if not b1:
            continue
        e1, n1, t1 = b1
        ms = STAB.match(t1)
        if not ms:
            continue
        k = e1
        while k < len(s) and s[k] in " \n":
            k += 1
        if s[k:k + 1] != "(":
            continue
        b2 = binder_at(s, k)
        if not b2:
            continue
        e2, n2, t2 = b2
        md = DISJ.match(t2)
        A, B, C = ms.group("A"), ms.group("B"), ms.group("C")
        if not md or (md.group("A1"), md.group("B"), md.group("C")) != (A, B, C):
            continue
        if strip_parens(ms.group("A2")) != strip_parens(A) or strip_parens(md.group("A")) != strip_parens(A):
            continue
        # the declaration this binder belongs to
        start = s.rfind("\n", 0, m.start()) + 1
        head = max(s.rfind("\ntheorem ", 0, m.start()), s.rfind("\nlemma ", 0, m.start()),
                   s.rfind("\nprivate theorem ", 0, m.start()), s.rfind("\ndef ", 0, m.start()),
                   s.rfind("\nnoncomputable def ", 0, m.start()))
        end = decl_end(s, e2)
        body = s[e2:end]
        new = "hTI" if not re.search(r"\bhTI\b", s[head:end]) else "hTIdiff"
        ind = s[start:m.start()]
        one = f"({new} : IsTIDiff {A} {B} {C})"
        if len(ind) + len(one) > 100:
            one = f"({new} : IsTIDiff {A}\n{ind}  {B} {C})"
        nb = re.sub(rf"(?<![\w.']){re.escape(n1)}\s+{re.escape(n2)}(?![\w'])", new, body)
        nb = re.sub(rf"(?<![\w.']){re.escape(n1)}(?![\w'])", f"{new}.1", nb)
        nb = re.sub(rf"(?<![\w.']){re.escape(n2)}(?![\w'])", f"{new}.2", nb)
        out.append(s[pos:m.start()] + one + nb)
        pos = end
        count += 1
    out.append(s[pos:])
    return "".join(out), count


total = 0
for d, _, fs in os.walk(FT):
    for fn in fs:
        if fn.endswith(".lean"):
            p = os.path.join(d, fn)
            s = open(p, encoding="utf-8").read()
            t, c = convert(s)
            if c:
                total += c
                print(c, os.path.relpath(p, FT))
                if not dry:
                    open(p, "w", encoding="utf-8").write(t)
if not dry:
    p = os.path.join(FT, "Representations/OddCyclicFactorOrders.lean")
    s = open(p, encoding="utf-8").read()
    if "structure IsTIDiff" not in s:
        s = s.replace("structure IsCyclicTIPair", DEF + "structure IsCyclicTIPair", 1)
        open(p, "w", encoding="utf-8").write(s)
print("converted", total)
