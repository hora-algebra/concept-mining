# concept-mining

**Refactor all of formalized mathematics, and mine the concepts that matter.**

Large formal proofs are now being produced faster than anyone can read them.
They are correct, but they are not yet *understood*: the same argument appears
many times in different clothes, and the concepts that would unify them are
never named.

This project treats a formal proof library as a codebase and refactors it.
When introducing a definition or a lemma makes the whole library shorter while
the final theorem stays the same, that definition or lemma is doing real work.
We use this as a measurable proxy for a mathematical question:

> Which concepts are the important ones?

## First target: the classification of finite simple groups

We start from the Lean 4 formalization of the classification of finite simple
groups released by Axiom in October 2026
([AxiomMath/CFSG](https://github.com/AxiomMath/CFSG), Apache-2.0, about 43
million lines). It is large, machine-written, and follows the first-generation
proof, so it is a natural place to look for repeated arguments and missing
abstractions.

## How we measure

- The statement of the final theorem is fixed. Every change must still compile
  against it, with the same axioms.
- The score of a refactoring is how much it shrinks the library.
- A concept is ranked by the shrinkage it buys, not by how familiar it is.

The exact size measure (source lines, tokens, or size of the elaborated proof
terms) is an open design question. See [Open questions](#open-questions).

## Roadmap

| Stage | Goal | Compute |
|---|---|---|
| 1. Map | Extract the dependency graph of declarations and count how each one is used | laptop |
| 2. Mine | List candidates: near-duplicate proofs, heavily reused lemmas, repeated hypotheses bundles | laptop |
| 3. Pilot | Refactor one small, self-contained part and measure the shrinkage | laptop / one server |
| 4. Scale | Apply the abstractions that worked across the library | shared build cache |

Status: **stage 1 done**. The dependency graph of all 2.2 million
declarations has been extracted without a build; see
[Stage 1: Map](docs/stage1-map.md) for the layout of the formalization, the
most used declarations, and candidate ranges for stages 2 and 3, and
[Compute plan and model trials](docs/compute-and-trials.md) for what runs on
a laptop and how refactorings will be tried with several model providers.

## How to contribute

- **Mathematicians.** Look at a candidate from stage 2 and say what the common
  idea is called, or should be called. No Lean needed.
- **Lean users.** Pick a candidate, carry out the refactoring on a branch, and
  open a pull request. CI reports the change in size.
- **Compute.** A full build takes about a day on a strong Linux machine. We
  want a shared build cache so that contributors rebuild only what they touch.
  If you can host builds or cache storage, please open an issue.

## Related work

- [Lean Refactor](https://arxiv.org/abs/2605.20244),
  [Proof-Refactor](https://arxiv.org/abs/2606.03743),
  [LeanPolish](https://arxiv.org/abs/2609.38384): tools that shorten or
  modularize individual machine-written Lean proofs. We expect to use such
  tools; our aim is different, namely abstractions shared across a whole
  theory.
- [Mathlib](https://github.com/leanprover-community/mathlib4): continuous
  human-led refactoring of a formal library
  ([Growing Mathlib](https://arxiv.org/abs/2508.21593)).

## Open questions

- Which size measure best reflects mathematical understanding?
- How do we stop the score from rewarding unreadable compression?
- Which part of the classification is the best pilot?
- What should be proposed upstream, to AxiomMath/CFSG or to Mathlib?

## License

Apache-2.0, matching the upstream formalization.
