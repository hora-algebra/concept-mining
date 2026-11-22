# How much could CFSG shrink? A map of upper bounds

Status: measured on AxiomMath/CFSG at `965a077` (32.3M lines inside 1.72M
declarations, certificate data folders excluded). All figures are upper
bounds under the stated assumption. None has been verified in Lean except
where marked.

## Summary

| Signal | What it assumes can be removed | Removable lines | Share | How real |
|---|---|---|---|---|
| Unreachable code (stage 1) | declarations the final theorem does not need | 1,897,095 | 5.4% | exact; deletion, not a concept |
| Same proof up to renaming | all but one copy | 258,792 | 0.8% | exact up to renaming; names declared in the same file are qualified by their namespace |
| Same proof shape (identifiers abstracted) | one general proof per family; one-line instance per member | 866,990 | 2.7% | an upper bound; the large families are mostly data tables |
| Same tactic outline (≥ 8 steps) | the same, at the level of the outline only | 727,782 | 2.3% | loose; same outline does not mean same mathematics |
| Same statement proved again elsewhere | the proof subtree that only the second proof needs | 671,460 | 1.9% | same statement text, with file-local names qualified; not checked by elaboration, so a few groups may differ in meaning through `variable` or `open` context |
| Same name pattern (case index in the name) | one general theorem per family | 2,197,975 | 6.8% | **mostly not real**: sampled families are numbered book statements or certificate text |
| Statements (text before `:=`) | everything a perfect bundling of hypotheses could remove | at most 4.2M | 13.1% | a ceiling, not an estimate |
| Data tables (≥ 60% literal tokens) | not removable by concepts; a matter of encoding | 624,333 | 1.9% | reported separately |

**The textual signals cap ideal abstraction at roughly 5–10% of CFSG.** The
same-shape, same-statement and genuine name families overlap. Together they
reach about 2.5–4M lines in the most generous reading. Unreachable code adds
5.4%, but that is deletion, not a concept. No signal that can be measured on
the text shows 50%.

Per region the picture is the same. Every large region (StandardType,
UniquenessCase, ComponentClassification, Quasithin, RankThree) scores 2–4% on
shape and 2–3% on duplicated statements. The single exception is
Quasithin.H13, at 6.8% on shape. The tables are
`data/map/skeletons/regions.tsv`, `data/map/theory_duplicates/regions.tsv`,
`data/map/name_families/regions.tsv` and `data/map/data_share.tsv`, and in
the page format `data/potential/blocks.tsv` (methods `same-shape` and `same-statement`, written by `tools/potential_rows.py`).

Repetition across the case division (the same argument written once per
sporadic group or per Lie type) is measured separately in
[group-repetition.md](group-repetition.md): at most about 0.3% of CFSG for
arguments, as a long tail of small families.

## Where the larger reductions are

Sampling the proposal layer's hypotheses (below) gives three kinds of
reduction that are larger than any single duplicate. None of them shows up as
textual similarity.

1. **A basic group-theory layer shared by all regions.** Short general facts
   about normalizers, centralizers and conjugation are re-proved in every
   region. 994 groups of identical statements span five or more files, for
   about 130,000 removable lines. `mem_normalizer_sup` is proved 259 times,
   `conj_injective` 119 times and `orderOf_conj_eq` 106 times. Some of these
   are already in Mathlib, for example
   `Subgroup.inf_normalizer_le_normalizer_sup`. The concept: a common
   vocabulary, mostly Mathlib's.
2. **Parallel vocabularies.** There are about 100 local definitions of the
   conjugate of a subgroup with 5,756 lemmas around them, four definitions of
   quasisimple and ten of component. The p-core alone has two versions with
   about 55,000 users each. Each copy brings its own API and bridges.
3. **Proof architecture.** Feit–Thompson passes the results of earlier
   chapters as explicit hypotheses: 2,239 hypothesis lines and an 803-line
   wiring file. It also defines "minimal simple group of odd order" nine
   times, with 473 conversion lines. The wiring hypothesis was verified in Lean:
   bundling the assumptions into cumulative stages saved 16,563 tokens (1,663
   lines) in one patch (see two-layer-search.md).

Even these together are on the order of 1–3% of CFSG.

## Why 50% is not visible, and where it would have to come from

The measurements point to one structural reason. **The upstream proof is long
because its mathematics is long, not because it repeats itself.** About 87% of
the lines are proof steps rather than statements. The proof steps of one
region rarely recur in another, even up to renaming every identifier. The
largest apparent families turn out to be certificate tables or the numbered
statements of a book, which are different theorems sharing a naming scheme.

A 10% or 50% reduction would therefore need what the textual signals cannot
see: shorter mathematics. That means a second-generation argument that
replaces a case analysis by a general theorem, much as the revision project of
Gorenstein, Lyons and Solomon replaced parts of the first-generation proof.
Finding such arguments is what the altitude angle of the proposal layer is
for. Its first run found architecture-level redundancy (bundled assumptions,
merged vocabularies), not shorter mathematics. Whether a model can propose the
latter is the open question of this project.

## Reproduce

```bash
python3 tools/skeletons.py --root ~/cfsg --out data/map/skeletons
```

```bash
python3 tools/name_families.py --decls out/skeleton_decls.tsv.gz --out data/map/name_families
```

```bash
python3 tools/theory_duplicates.py --decls out/skeleton_decls.tsv.gz --cache ~/.cache/concept-mining/proofmap --out data/map/theory_duplicates
```

```bash
python3 tools/data_share.py --root ~/cfsg --out data/map/data_share.tsv
```

The source scans take about half a minute each with 12 processes. The
proof-map join needs about 3 GB of memory.
