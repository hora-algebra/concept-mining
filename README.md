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

Size is counted in Lean tokens outside comments, so that joining lines or
shortening names earns nothing ([Contribute](docs/contribute.md)). How to
credit abstractions that pay off only after they spread is discussed in
[Two-layer search](docs/two-layer-search.md).

## Roadmap

| Stage | Goal | Compute |
|---|---|---|
| 1. Map | Extract the dependency graph of declarations and count how each one is used | laptop |
| 2. Mine | List candidates: near-duplicate proofs, heavily reused lemmas, repeated hypotheses bundles | laptop |
| 3. Pilot | Refactor one small, self-contained part and measure the shrinkage | laptop / one server |
| 4. Scale | Apply the abstractions that worked across the library | shared build cache |

Next goal: remove 1 % of the library, starting with unused declarations ([plan](docs/plan-one-percent.md)).
Where larger reductions could come from, ranked by the lines each theorem's proof costs: [Strategy](docs/strategy.md).

Status: **stage 1 done; stage 3 pilot running on Feit–Thompson**, with
concepts introduced by an unattended loop and judged by Lean
([Pilot: Feit–Thompson](docs/pilot-feit-thompson.md)). The dependency graph of all 2.2 million
declarations has been extracted without a build; see
[Stage 1: Map](docs/stage1-map.md) for the layout of the formalization, the
most used declarations, and candidate ranges for stages 2 and 3, and
[Compute plan and model trials](docs/compute-and-trials.md) for what runs on
a laptop and how refactorings will be tried with several model providers.

## Progress

The progress page ([`docs/site/`](docs/site)) shows the map of the
formalization, how much has been removed so far, the concepts found, the points of
each contributor, who (and which agent) is working on what, and which
candidates are free. It is regenerated from
the ledger in [`data/ledger/`](data/ledger) by
[`tools/site/build_site.py`](tools/site/README.md), which also checks the
ledger on every pull request.

## How to contribute

The refactoring is done by AI agents that anyone can run. Details in
[CONTRIBUTING.md](CONTRIBUTING.md).

- **Run an agent.** Fork the repository, add a model provider's API key, and
  run the *Contribute* workflow, or run one command locally with your agent
  (Claude Code, Codex, or any other; see [Contribute](docs/contribute.md)).
  The agent claims a free candidate, introduces the concept, checks it with
  Lean and opens a pull request. CI checks it again and merges it if it is
  correct and saves tokens.
- **Points.** Every accepted change earns points by a fixed, mechanical rule:
  1 point per 100 Lean tokens removed, plus points for uses and reuse of the
  concepts it introduces. See [docs/scoring.md](docs/scoring.md).
- **Name a concept (optional).** Say what a concept an agent found is called
  in group theory. No Lean needed.
- **Compute.** Hosting builds or a shared build cache makes every check
  faster. Open an issue with the *Offer compute* template.

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
