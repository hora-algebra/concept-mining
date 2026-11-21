"""Families of expensive declarations with the same statement up to numbers and type names,
and exact statement twins.

Reads the signatures of statement_signatures.py and the price of each
declaration (dominator_prices.py). A *family* is a set of theorems with the
same loose signature whose dominator subtrees are disjoint; one general
theorem would keep one proof, so the bound is the total price minus the
largest. A *twin* is a pair with the same strict signature where neither
declaration reaches the other: one proof could become an application of the
other.

    python3 tools/strategy/schema_families.py --cache ~/.cache/concept-mining/proofmap \
        --sigs out/statement_signatures.tsv --out out/schema
"""
import argparse, collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from analyze_proofmap import load  # noqa: E402
from array import array


def prices(cache):
    meta, kinds, mods, kind, module, line, lines, idom, names, dep_off, deps = load(os.path.expanduser(cache))
    n, final = meta["points"], meta["final"]
    depth = array("i", [-1]) * n
    depth[final] = 0
    for p in range(n):
        chain, q = [], p
        while depth[q] < 0 and idom[q] >= 0 and q != final:
            chain.append(q)
            q = idom[q]
        if depth[q] < 0:
            continue
        b = depth[q]
        for x in reversed(chain):
            b += 1
            depth[x] = b
    price = array("q", [0]) * n
    for p in sorted((p for p in range(n) if depth[p] >= 0), key=lambda p: -depth[p]):
        price[p] += lines[p]
        if p != final and idom[p] >= 0:
            price[idom[p]] += price[p]
    return dict(n=n, final=final, names=names, idom=idom, depth=depth, price=price, dep_off=dep_off, deps=deps)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--sigs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min", type=int, default=50, help="smallest price of a family member")
    ap.add_argument("--twin-min", type=int, default=2000, help="smallest price of a twin")
    a = ap.parse_args()
    G = prices(a.cache)
    names, idom, depth, price, final = G["names"], G["idom"], G["depth"], G["price"], G["final"]
    idx = {names[p]: p for p in range(G["n"])}

    def inside(p, q):
        x = idom[p]
        while x >= 0 and x != final:
            if x == q:
                return True
            x = idom[x]
        return False

    def reaches(p, q, limit=300000):
        do, dp = G["dep_off"], G["deps"]
        seen, st = {p}, [p]
        while st and len(seen) < limit:
            x = st.pop()
            for j in range(do[x], do[x + 1]):
                y = dp[j]
                if y == q:
                    return True
                if y not in seen:
                    seen.add(y)
                    st.append(y)
        return None if st else False

    loose, strict, text = collections.defaultdict(list), collections.defaultdict(list), {}
    with open(a.sigs) as f:
        next(f)
        for l in f:
            nm, _, sh, sl, lh, ll, st = l.rstrip("\n").split("\t", 6)
            p = idx.get(nm)
            if p is None or depth[p] < 1:
                continue
            text[p] = st
            if int(ll) >= 5 and price[p] >= a.min:
                loose[lh].append(p)
            if int(sl) >= 5:
                strict[sh].append(p)
    os.makedirs(a.out, exist_ok=True)
    fams = []
    for m in loose.values():
        if len(m) < 2:
            continue
        ms = set(m)
        top = [p for p in m if not any(inside(p, q) for q in ms if q != p)]
        if len(top) < 2:
            continue
        s = sorted((price[p] for p in top), reverse=True)
        best = max(top, key=lambda p: price[p])
        fams.append((sum(s) - s[0], sum(s), len(top), names[best], " ; ".join(names[p] for p in top[:12]), text[best][:200]))
    fams.sort(reverse=True)
    with open(os.path.join(a.out, "families.tsv"), "w") as w:
        w.write("removable_lines\ttotal_price\tmembers\tlargest\tmembers_sample\tstatement\n")
        for r in fams:
            w.write("\t".join(map(str, r)) + "\n")
    twins = []
    for m in strict.values():
        for p in m:
            if price[p] < a.twin_min:
                continue
            for q in m:
                if q == p or inside(q, p) or inside(p, q):
                    continue
                if reaches(p, q) is False and reaches(q, p) is False:
                    twins.append((price[p], names[p], names[q], price[q], text[p][:200]))
    twins.sort(reverse=True)
    with open(os.path.join(a.out, "twins.tsv"), "w") as w:
        w.write("price\tdeclaration\ttwin\ttwin_price\tstatement\n")
        for r in twins:
            w.write("\t".join(map(str, r)) + "\n")
    print(f"{len(fams)} families, bound {sum(r[0] for r in fams)} lines; {len(twins)} twin pairs")


if __name__ == "__main__":
    main()
