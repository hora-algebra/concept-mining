"""Statement signatures of every theorem and lemma under CFSG/ (certificate folders skipped).

For each theorem, the tokens before the top-level `:=` are reduced to
  strict  the ordered sequence of global identifiers (last component of dotted
          names), numerals and logical symbols; bound names, brackets, `∀`,
          `→`, commas and the declaration's own name are dropped, so binder
          style, universe annotations and hypothesis names do not matter;
  loose   the sorted multiset of global identifiers (numerals dropped), so
          statements that differ only in numbers or type names coincide.
Handles `public theorem` as well as the other modifiers.

    python3 tools/strategy/statement_signatures.py --root ~/cfsg --out out/statement_signatures.tsv
"""
import argparse, bisect, hashlib, os, re, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from size import TOKEN, strip_comments  # noqa: E402

MOD = r"(?:@\[[^\n]*\]\s*)?(?:(?:public|private|protected|noncomputable|nonrec|partial|unsafe)\s+)*"
DECL = re.compile(r"^" + MOD + r"(theorem|lemma)\s+([^\s:(\[{]+)", re.M)
NEXT = re.compile(r"^" + MOD + r"(theorem|lemma|def|abbrev|instance|structure|class|inductive|end|namespace|section|open|variable|universe|set_option|attribute|#)\b", re.M)
NS = re.compile(r"^(namespace\s+(\S+)|section\b[^\n]*|end\b[^\n]*)", re.M)
SKIP = set("theorem lemma Type Prop Sort fun λ by at with in let if then else match do have show from".split())
KEEP = set("= ≠ ≤ < ∧ ∨ ¬ ↔ ∃ ∣ ∈ ∉ ⊆ ≃* ≅ ⧸".split())
LOCALNAME = re.compile(r"[a-zA-Z]['₀-₉0-9]*|h\w*|u|v|w")
h8 = lambda s: hashlib.blake2b(s.encode(), digest_size=8).hexdigest()


def statement(text):
    toks = TOKEN.findall(text)
    out, depth = [], 0
    for t in toks[2:]:
        if t in "([{⦃⟨":
            depth += 1
        elif t in ")]}⦄⟩":
            depth -= 1
        elif t == ":=" and depth == 0:
            break
        out.append(t)
    return out


def signatures(st, own):
    bound = set()
    for i, t in enumerate(st):
        if t in ("(", "{", "⦃", "["):
            j, names = i + 1, []
            while j < len(st) and j < i + 10 and (st[j][0].isalpha() or st[j][0] == "_"):
                names.append(st[j])
                j += 1
            if j < len(st) and st[j] == ":":
                bound.update(names)
        if t in ("∀", "∃", "fun", "λ", "∃!"):
            for u in st[i + 1:i + 12]:
                if u in (",", ":", "=>", "↦"):
                    break
                if u[0].isalpha() or u[0] == "_":
                    bound.add(u)
    strict, loose = [], []
    for t in st:
        if t in KEEP or t[0].isdigit():
            strict.append(t)
            continue
        if not (t[0].isalpha() or t[0] == "_") or t in bound or t in SKIP or LOCALNAME.fullmatch(t):
            continue
        last = t.split(".")[-1]
        if last == own:
            continue
        strict.append(last)
        loose.append(last)
    return " ".join(strict), " ".join(sorted(loose))


def scan(path):
    out = []
    try:
        src = strip_comments(open(path, encoding="utf-8", errors="replace").read())
    except OSError:
        return out
    events = [(m.start(), m.group(0)) for m in NS.finditer(src)]
    starts = [m.start() for m in NEXT.finditer(src)]
    stack, k = [], 0
    for m in DECL.finditer(src):
        s = m.start()
        while k < len(events) and events[k][0] < s:
            ev = events[k][1]
            if ev.startswith("namespace"):
                stack.append(ev.split()[1])
            elif ev.startswith("section"):
                stack.append(None)
            elif stack:
                stack.pop()
            k += 1
        j = bisect.bisect_right(starts, s)
        text = src[s:starts[j] if j < len(starts) else len(src)]
        name = m.group(2)
        ns = ".".join(x for x in stack if x)
        full = name.removeprefix("_root_.") if (name.startswith("_root_.") or not ns) else f"{ns}.{name}"
        strict, loose = signatures(statement(text), full.split(".")[-1])
        out.append(f"{full}\t{path}\t{h8(strict)}\t{len(strict.split())}\t{h8(loose)}\t{len(loose.split())}\t{strict[:300]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="upstream checkout")
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    root = os.path.join(os.path.expanduser(a.root), "CFSG")
    paths = [os.path.join(dp, f) for dp, _, fn in os.walk(root) if "Certificates" not in dp for f in fn if f.endswith(".lean")]
    with Pool(a.jobs) as p, open(a.out, "w") as w:
        w.write("name\tfile\tstrict\tstrict_len\tloose\tloose_len\tstrict_text\n")
        for res in p.imap_unordered(scan, paths, chunksize=200):
            for r in res:
                w.write(r + "\n")
    print(f"{len(paths)} files")


if __name__ == "__main__":
    main()
