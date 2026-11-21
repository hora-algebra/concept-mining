"""Price of every declaration: lines used only through it.

The price of a declaration is the number of lines inside declarations in its
subtree of the dominator tree of the final theorem, i.e. the lines that become
unneeded if its proof is replaced by one that uses none of them.

    python3 tools/strategy/dominator_prices.py --cache ~/.cache/concept-mining/proofmap \
        --out data/map/dominator_roots.tsv --min 3000
"""
import argparse, os, sys
from array import array
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from analyze_proofmap import load  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min", type=int, default=3000)
    a = ap.parse_args()
    meta, kinds, mods, kind, module, line, lines, idom, names, dep_off, deps = load(os.path.expanduser(a.cache))
    n, final = meta["points"], meta["final"]
    depth = array("i", [-1]) * n
    depth[final] = 0
    for p in range(n):
        chain, q = [], p
        while depth[q] < 0 and idom[q] >= 0 and q != final:
            chain.append(q)
            q = idom[q]
        base = depth[q] if depth[q] >= 0 else None
        for x in reversed(chain):
            if base is None:
                break
            base += 1
            depth[x] = base
    price = array("q", [0]) * n
    for p in sorted((p for p in range(n) if depth[p] >= 0), key=lambda p: -depth[p]):
        price[p] += lines[p]
        if p != final and idom[p] >= 0:
            price[idom[p]] += price[p]
    rows = [p for p in range(n) if depth[p] >= 1 and price[p] >= a.min]
    rows.sort(key=lambda p: -price[p])
    with open(a.out, "w") as w:
        w.write("price_lines\tdepth\tkind\tname\tmodule\timmediate_dominator\n")
        for p in rows:
            w.write(f"{price[p]}\t{depth[p]}\t{kinds[kind[p]]}\t{names[p]}\t{mods[module[p]]}\t{names[idom[p]]}\n")
    print(f"{len(rows)} declarations with price >= {a.min}; final theorem total {price[final]}")


if __name__ == "__main__":
    main()
