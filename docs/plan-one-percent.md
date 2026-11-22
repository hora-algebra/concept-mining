# Next goal: remove 1 % of the library

The library is 35,093,004 lines inside declarations. As of 2026-11-21, 346
of them have been removed (0.001 %). The next goal is **1 %, about 351,000
lines**.

## Why cleanup comes first

About 1.9 million lines (5.4 %) are declarations that the final theorem does
not depend on ([potential-and-search.md](potential-and-search.md)). Deleting
them cannot change the final theorem, and it is the only method whose known
upper bound is far above 1 %:

| Method | Upper bound | Share of the library |
|---|---|---|
| Delete declarations the final theorem does not need | 1,897,095 lines | 5.4 % |
| Merge proofs of the same shape | 866,811 lines | 2.5 % |
| Merge copies of the same statement | 671,430 lines | 1.9 % |

The bounds overlap, so they cannot be added.

Cleanup finds no concept by itself, but it prepares the search for one: with
the unused declarations gone, the repetitions that remain are the ones the
proof actually uses. The scoring stays as it is ([scoring.md](scoring.md)):
cleanup earns a quarter of the rate, so introducing a concept remains the way
to earn the most points.

## Rules for this phase

- **Cleanup counts on the progress page.** The page so far counts only lines
  removed from declarations the protected theorems need, so cleanup showed as
  0. From now on the page shows total lines removed from the whole library,
  split into "cleanup" and "concepts", against the same total of 35.09 M.
- **`CFSG.Milestones` is kept.** Its statements are what readers look at
  (339,612 of its lines are not needed by the final theorem); they are not
  deleted to reach the goal.
- **The final theorem and its axioms stay exactly the same**, checked as for
  every contribution.

## Steps

| Step | What | Where |
|---|---|---|
| 1 | Count cleanup on the page (cleanup / concepts split) | this repository |
| 2 | Script that deletes, for chosen parts, every declaration the final theorem does not need, with what depends on it, and that leaves files and imports in order | laptop |
| 3 | One build of the whole library, kept for the next step | rented build machine (48 cores, deleted afterwards) |
| 4 | Delete unused declarations part by part, largest first (`LocalAnalysis` 318,860 lines, `Quasithin` 239,926, `Permutation` 166,205, ...), rebuilding what each deletion touches, until 351,000 lines are removed | same machine |
| 5 | Record each accepted deletion in the ledger | this repository |

The search for concepts on Feit–Thompson goes on in parallel.

## Where the build runs

A laptop build is estimated at 17–26 hours ([compute-and-trials.md](compute-and-trials.md)),
and the output of the modules built so far is 9.6 GB for 1.62 M source lines,
so the whole library needs roughly 80–250 GB of disk. Upstream publishes no
build cache. The build therefore runs on a rented machine with enough disk,
billed by the hour, and the machine is deleted when step 4 is done.
