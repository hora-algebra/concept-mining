# Compute plan and model trials

How much of the work fits on one strong laptop, what should go to shared or
cloud machines, and how stages 2 and 3 will try many refactorings with
language models from several providers, compared on cost per line removed.

## Measured on one laptop

Machine: Apple M5 Max, 18 cores, 64 GB memory, 3.0 TB free disk.
Builds ran at low priority (`nice -n 15`) while the machine was in normal use.
Upstream commit `965a077`, Lean `v4.35.0`.

| Step | Size | Wall time | Peak memory of one process | Disk |
|---|---|---|---|---|
| Partial clone + sparse checkout of the Lean sources | 203,046 files | 3 min | – | 2.3 GB |
| Mathlib build cache (`lake exe cache get`) | 9,034 files | 4 min | – | 6.8 GB (all dependencies) |
| Build `CFSG/Combinatorics` (closed, Mathlib only) | 64 modules, 13,926 lines | 2.1 min | 2.3 GB | 0.15 GB |
| Build `CFSG/FeitThompson` (closed, Mathlib only) | 1,414 modules, 274,110 lines | 9.8 min | 3.1 GB | 3.5 GB |

For `FeitThompson`, the summed compile time of its modules is 9,780 s, i.e.
0.036 s per line, and the 18 cores were used 16.5 times in parallel. For
`Combinatorics` it is 0.023 s per line.

### Extrapolation to the whole library (not measured)

| | Low | High | Basis |
|---|---|---|---|
| CPU time | 275 core-hours | 430 core-hours | 0.023–0.036 s per line × 43.1 M lines |
| Wall time on this laptop | 17 h | 26 h | same parallelism as `FeitThompson` |
| Build output on disk | 110 GB | 550 GB | 0.4–12.8 KB per line (with or without the generated C files) |

Upstream reports "under 24 hours" with unreleased Lake changes; on which
machine is **unverified** (the README and the release blog post do not say).
The extrapolation ignores three things that can make the real build slower:
long dependency chains in `LocalAnalysis` (less parallelism), the certificate
modules compiled to native code, and modules that may need much more memory
than 3 GB (with 18 jobs at once, 64 GB is the limit). A full build is
therefore plausible on this laptop in one to two days, but **unverified**.

### What runs where

| Work | Where | Why |
|---|---|---|
| Dependency graph, source scans, candidate lists (stage 1–2) | laptop | minutes, no build |
| Building a closed part and judging refactorings inside it (stage 3) | laptop | `FeitThompson`-size parts rebuild in ~10 min; a single changed file rebuilds in seconds to minutes |
| One full build, to obtain all `.olean` files once | laptop, overnight on a weekend (17–26 h, cores fully busy) — or a shared machine | possible here; the laptop is hard to use meanwhile |
| Judging refactorings that touch widely used definitions (e.g. merging the p-core definitions: tens of thousands of dependents) | shared build machine with a build cache | every attempt forces a large rebuild |
| Stage 4 (applying changes across the library, CI for contributors) | shared build cache (community / cloud) | repeated full rebuilds |

## Trials with several providers

### Design

```
candidates (stage 2) ──> tasks.jsonl ──> run_trials.py ──> replies + token counts + price
                                              │ (any provider, in parallel, hard budget cap)
                                              v
                                          judge.py  ──> pass/fail by Lean, lines removed
                                              v
                                        summarize.py ──> USD per 100 lines removed, per model
```

* **Providers are interchangeable** ([`tools/trials/providers.py`](../tools/trials/providers.py)):
  one class per vendor with the same `complete()` method. Anthropic and OpenAI
  are implemented with their official SDKs; others are added the same way.
* **Same prompt, same task, same judge for every model.** No server-side
  fallback to another model, so a refusal counts against the model that
  refused.
* **Lean decides.** A reply passes only if the affected modules build, the
  protected declarations keep exactly the same statement and axioms
  (`#check`, `#print axioms`), and it contains no `sorry`, `admit`,
  `native_decide` or `axiom`. The model never grades itself.
* **Comparison metric:** total cost of all attempts (passed or not) divided
  by the code lines removed in passing replies. Prices come from
  [`pricing.json`](../tools/trials/pricing.json), copied from the providers'
  own price pages on 2026-11-21.
* **Spending control:** `--dry-run` prints the estimate without calling
  anything; a real run requires `--budget-usd`, and each request is sent only
  if the worst case still fits in the budget.

### Models and prices (2026-11-21, USD per million tokens)

Sources: [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[OpenAI pricing](https://developers.openai.com/api/docs/pricing). Batch
processing halves all prices at both providers.

| Price tier | Anthropic | OpenAI | Input | Output |
|---|---|---|---|---|
| Top | `claude-fable-5-2` | `gpt-6.2-astra` | 8.00 | 40.00 |
| Upper middle | `claude-opus-5-5` | `gpt-5.6-sol` | 4.00 | 20.00 |
| Middle | `claude-sonnet-5-5` | `gpt-6.2-sol` | 2.00 | 10.00 |
| Low | `claude-haiku-5-5` | `gpt-6-luna` | 0.10 | 0.50 |

`gpt-5.6-sol` is at a promotional price until 2026-11-30 (OpenAI). The two price lists line up tier by tier, so models can be compared in pairs
at equal price. Which models are better at Lean is **unverified**; that is
what phase A below measures.

### Cost estimate

Assumed size of one attempt: 12 k input tokens (one file of about 300 lines
plus the definitions it uses) and 10 k output tokens (new file plus
reasoning). Real counts are recorded per attempt and replace these figures
after phase A.

| Tier | Cost of one attempt |
|---|---|
| Top | 0.50 USD |
| Upper middle | 0.25 USD |
| Middle | 0.12 USD |
| Low | 0.006 USD |

| Phase | What | Attempts | Estimated cost |
|---|---|---|---|
| A. Calibration | 10 tasks from the pilot × 8 models × 2 attempts | 160 | about 35 USD |
| B. Pilot (stage 3) | 50 files of the pilot × the 4 best models by phase A × 3 attempts | 600 | 40–150 USD |
| C. One stage-2 family (e.g. unify the p-core definitions) | depends on the number of affected files; judged on a shared build machine | – | estimated after B |

With batch processing (results within 24 h) the API cost is half.

### Status

* A small test call (Anthropic, estimated 0.01 USD) was rejected by the
  provider with `401 invalid x-api-key`: the key in the existing secrets file
  is not accepted. No API cost has been incurred.
* No OpenAI key file exists in the secrets directory; the OpenAI provider is
  implemented but **untested**.
* `judge.py` was checked on two hand-made replies for one module: an
  unchanged file passes (8 s), and a file whose theorem statement was changed
  (`Type*` to `Type`) is rejected. It has not yet judged a model's reply.

## Reproducing the measurements

```bash
cd upstream/cfsg
lake exe cache get
find CFSG/FeitThompson -name '*.lean' | sed 's/\.lean$//; s#/#.#g' > ../ft_mods.txt
/usr/bin/time -l nice -n 15 xargs lake build < ../ft_mods.txt
```
