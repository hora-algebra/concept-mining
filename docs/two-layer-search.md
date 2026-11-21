# Two-layer search for global abstractions

Status: design memo with one small experiment. Nothing here has been run at
scale. The experiment is cheap and uses no model API.

## The problem

The loop in [contribute.md](contribute.md) improves the code one candidate at a
time. Every candidate comes from a local signal: definitions with the same
body, a hypothesis restated verbatim, lemmas with the same statement. Signals
like these find redundancy that is already visible in the text. They will not
find the abstractions that make human mathematics shorter, the ones that are
global and unexpected. A single notion can turn twenty arguments in three
areas into one argument. If no two of those twenty arguments look alike on the
page, a local signal will never point at that notion.

## Proposal: separate proposing from verifying

**(a) Proposal layer: many hypotheses, high diversity, cheap.** An AI is shown
global material instead of single files, and asked a question of this form:
*"which concept, if introduced, would unify what?"* Each answer is a
hypothesis. It names the concept, gives its mathematical meaning, says where it
would be used and estimates what would shrink. To get diversity rather than
twenty phrasings of the same idea:

- sample several models from different providers, at high temperature;
- give the same material through different viewpoints ("you are a group
  theorist", "you are a Mathlib maintainer", "find a structure that two
  distant folders both reprove", "find the hypothesis that keeps being
  re-derived");
- give different slices of material per call, so that the calls do not all
  start from the same evidence;
- remove duplicate hypotheses by embedding similarity before verifying.

**(b) Verification layer: few, expensive, decisive.** Each surviving hypothesis
becomes a candidate for the existing loop. An agent introduces the concept, and
`tools/verify.py` decides with Lean and the token count. Nothing from layer (a)
is trusted. A hypothesis that does not survive (b) costs only the attempt.

The two layers have opposite requirements. Layer (a) should be wide and
tolerant of nonsense. Layer (b) should be narrow and unforgiving. Mixing them,
by asking one agent to both imagine and prove, makes it timid. It proposes only
what it already knows how to finish.

## What the proposal layer borrows from `/simplify`

Claude Code's built-in `/simplify` command reviews a change from four angles
in parallel, one independent agent per angle, then deduplicates the findings
and applies the survivors. The angles transfer to proofs almost word for word:

| `/simplify` angle | Its wording (abridged) | Reading for a proof library |
|---|---|---|
| Reuse | flag code that re-implements something the codebase already has, and name the existing helper | a local notion or lemma that Mathlib or another region already has; replacing the notion removes its whole local API |
| Simplification | redundant or derivable state, copy-paste with slight variation, deep nesting, dead code | hypothesis lists threaded through chains of single-use lemmas; structures whose fields follow from a few others; arguments copied with small changes |
| Efficiency | wasted work, repeated computation | the same fact re-derived in many places; expensive tactic calls that a lemma would replace (build time, not size) |
| **Altitude** | fix the root cause at the right depth instead of patching a symptom; special cases layered on shared infrastructure mean the fix is not deep enough; prefer the more general change to the underlying mechanism, and name it | **a family of theorems proved case by case (per group, per type, per prime, per symmetric variant) that one theorem at the right level of generality would cover; name that theorem** |

Two features of `/simplify` matter more than the angles themselves:

- **One agent per angle, run in parallel, blind to each other.** Each agent
  looks for one kind of improvement, so no single agent drifts to the easiest
  kind. Diversity comes from the angles, not from sampling temperature.
- **A separate apply phase that may skip findings.** Proposals are cheap. The
  phase that edits keeps only findings that do not change behaviour and do not
  reach far outside the scope, and records why it skipped the others. For us
  "behaviour" means the protected statements, and the judge is Lean.

The proposal layer below follows this design. It runs one agent per angle
(reuse, simplification, altitude, and a cross-region angle), each shown the
global material and asked for hypotheses together with measured evidence.
Verification then applies them one at a time through `tools/verify.py`.
Altitude is the angle aimed at the global abstractions this memo is about.

## Material that improves the hypotheses

| Material | What it reveals | Status |
|---|---|---|
| Dependency graph and dominator regions (stage 1) | arguments that are used once and could be absorbed by a general statement | available |
| Repeated hypothesis bundles (`tools/candidates.py`) | contexts that keep being restated, often a missing structure | available |
| Definition copies, within and **across** regions (experiment below) | concepts that exist under several names, often already in Mathlib | available |
| Elaborated statement hashes after identifying copies (`tools/lean/ExportDecls.lean`) | lemmas that become identical once a concept is shared | available per built region |
| Proof-shape fingerprints across regions (tactic sequence and lemma multiset, up to renaming) | the same argument in two distant places, the strongest hint of a missing abstraction | to build |
| Matching against known human abstractions (Mathlib names and docstrings; textbook notions such as "TI subset", "Frobenius group", "signalizer functor") | whether a cluster is a known notion that the formalization re-derives | to build: embed local definitions and Mathlib declarations, report close pairs |

## The evaluation problem

Some concepts do not shrink anything when they are introduced. The definition
and its basic lemmas cost tokens. The savings come only after the concept has
reached most of the places that could use it, and those places may be spread
over several regions and several contributions. A judge that only accepts
immediate net savings will reject exactly the abstractions this memo is about.

Options, from most to least conservative:

1. **Introduce it with its uses.** A hypothesis is verified only together with
   enough rewrites to pay for itself. This needs no new rules. It makes such
   contributions large, and the time limit of one agent run caps them.
2. **Budgeted investment.** Allow a contribution that grows the code by at most
   a fixed amount if it declares a concept and a list of sites. Later
   contributions that use the concept are credited to it. If the concept has
   not paid back its cost after N follow-up contributions, it is reverted
   automatically. The ledger would need a `depends_on` column. The judge stays
   mechanical.
3. **Potential, not size.** Score a new concept by the number of statements
   whose elaborated form *would* coincide if the concept were used. This can be
   computed with the normalized hashes, before any proof is rewritten.
   It measures reach, not code removed, so it should rank candidates and
   should never be what gets a contribution accepted.

The recommended combination: (3) to choose which hypotheses get verified, (1)
as the default acceptance rule, and (2) only if (1) turns out to block
valuable concepts in practice.

## Small experiment: copies across regions

`tools/experiments/cross_region_defs.py` normalizes every `def` and `abbrev`
of CFSG outside the certificate data. It removes the name, renames binders
positionally and collapses whitespace. It then groups definitions whose
normalized text is identical and that occur in two or more top-level folders.
It reads source only (no build, no API) and takes a few minutes.

Result (`data/experiments/cross_region_defs.tsv`): 240,484 definitions in
194,223 files; **2,875 groups span two or more folders, covering 9,335
definitions**. The largest groups:

| Concept (normalized body) | Copies | Folders |
|---|---|---|
| conjugate of a subgroup, `H.map (MulAut.conj g).toMonoidHom` (same body, two argument orders) | 73 + 12 + 13 | 14, 9, 7 |
| centralizer of an element, `centralizer {g}` | 35 | 6 |
| inner automorphism group, `(MulAut.conj).range` | 26 | 7 |
| center of a subgroup as a subgroup of `G` | 16 | 9 |
| normalizer of a subgroup | 16 | 7 |
| `Bool → ZMod 2` | 19 | 9 |
| commutator `x⁻¹ y⁻¹ x y` | 9 | 8 |

What this shows:

- **The highest-reach concepts are cross-regional, and most of them already
  exist in Mathlib.** "Conjugate of a subgroup", "centralizer of an element",
  "normalizer" and "inner automorphisms" are standard Mathlib notions under
  other spellings. A proposal layer that matches local definitions against
  Mathlib would find these without a model.
- **One region cannot see them.** Inside FeitThompson each of these is at most
  a handful of copies. Across CFSG the conjugate of a subgroup has nearly a
  hundred. Choosing candidates per region systematically underrates such
  concepts. This is the evaluation problem in a mild form: a contribution
  confined to one region recovers only a small part of the value.
- **The textual signal saturates quickly.** These are renamings, not new
  mathematics. The unexpected abstractions the memo is after need the
  proof-shape fingerprints and the model-driven proposal layer. Copies are
  only the floor.

Next experiment, once permitted: give layer (a) the top 200 cross-region groups,
the hypothesis bundles of two regions (FeitThompson and LocalAnalysis), and the
dominator regions, and ask for unifying concepts. Then verify the 10 best by
potential in FeitThompson, the only region whose build is measured.

## First run (2026-11-21)

Four proposal agents ran in parallel, one per angle (altitude, reuse,
simplification, cross-region). Each was shown the global material and
measured its own evidence. Together they returned 19 hypotheses
(`data/search/hypotheses.jsonl`). Two angles independently proposed the same
best one. The cross-region agent sampled the members of its families and
rejected one family at the proposal stage: 0 of 7 `exists_frame` lemmas
share a statement.

| Hypothesis | Angle | Estimated lines | Result |
|---|---|---|---|
| Cumulative stages of chapter results (`StageK`): every Feit–Thompson chapter is proved under the single assumption "all earlier results hold" | altitude, simplification | 2,200 | **accepted**: 16,563 tokens, 1,663 lines, one patch, written by the unattended loop in 21 minutes |
| A shared basic group-theory layer across regions | cross-region | 85,000–130,000 | proposed |
| Transport along group isomorphisms (tactic or class) | cross-region | 20,000 | proposed |
| One conjugate-subgroup notion | cross-region | 7,500 | proposed |
| One structure for the minimal counterexample | altitude | 1,250 | proposed |
| Character-theory basics (inner product, induction, coherence) | altitude | 2,500 | proposed |
| Mathlib's transfer and focal subgroup theorems; textbook facts | reuse | 870 + 1,000 | proposed |
| Same last name across namespaces (`exists_frame`, ...) | cross-region | – | rejected: not one statement |

The accepted concept is architecture rather than new mathematics. It is
still the first single concept worth more than a thousand lines, and it came
from the altitude angle.

## Cost estimate (to be approved before running)

Prices as recorded in `tools/trials/pricing.json` (checked 2026-11-21, USD per
million input / output tokens). Assumptions: about 30k input and 3k output
tokens per proposal call.

| Step | Calls | Mid-tier models (2 / 10) | Top-tier models (8 / 40) |
|---|---|---|---|
| Layer (a): 4 viewpoints × 5 material slices × 2 models × 5 samples | 200 | about 18 USD | about 70 USD |
| Layer (b): 10 hypotheses × 1 agent run | 10 | not estimated (agent token use per run unmeasured) | not estimated |

The figures for layer (a) are arithmetic from the assumptions above. The cost
of layer (b) per agent run has not been measured. The first unattended run on
FeitThompson (in this pull request) used a local CLI subscription, not the
API, so it gives no API price.
