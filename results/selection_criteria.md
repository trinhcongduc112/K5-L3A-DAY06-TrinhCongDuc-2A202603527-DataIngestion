# Selection criteria — fixed before any retrieval result was seen

Written: 2026-11-13T11:21:14Z (UTC). At this moment the benchmark is frozen (benchmark/FREEZE.json, 2026-11-13T11:17:54Z), the
corpus is chunked/embedded into pgvector, and **no query has been run**.

## Candidates and controls
* Candidates: **A** (fixed 500/50), **B** (heading/paragraph, max 1000), **C** (B + metadata filter on filter questions).
* **A2** (fixed 1000/100) is a *diagnostic control* for "bigger chunks vs better boundaries". It is reported but is
  **not eligible** for selection.

## Rule (applied to the 22 dev questions only)
1. Highest **Evidence Hit@3** on dev.
2. Tie → higher **Hit@1** on dev.
3. Tie → fewer chunks and shorter ingest time (resources).
4. **C vs B**: C differs from B only on the 4 dev questions that carry a filter. Choose C over B only if it is strictly
   better on rule 1 or 2; if equal, prefer B because it needs no extra filter context at query time.
5. With n = 22 a difference of 1 question is within noise: if the top two candidates differ by <= 1 question on Hit@3
   and by <= 1 on Hit@1, report "no clear difference" and let rule 3 decide.

## Test split
* The test split (8 questions) is evaluated **once**, after `results/selection_decision.md` exists
  (`src/run.py` refuses otherwise). No parameter, chunk size, prompt or benchmark file changes afterwards.
* If anything is changed after test results were seen, it is logged in the report and the test result is no longer
  presented as an independent hold-out.

## Manual audits (labels are written by Claude, an AI, following GUIDE.md section 4 — see the report)
* **Chunk coherence**: 10 source positions chosen by a seeded rule (scripts/make_coherence_samples.py) *before* any
  retrieval output is viewed; the same positions for every strategy; C shares B's chunks.
* **Grounding** and **metadata** audits: all 8 test questions x top-3 x each strategy (>= the required 5).
