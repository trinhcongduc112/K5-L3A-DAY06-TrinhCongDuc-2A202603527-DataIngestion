# Selection decision — made on dev only, before the test split was run

Written: 2026-11-13T11:31:57Z (UTC). Inputs: `results/metrics_dev.json` (22 dev questions, benchmark sha256 a9f42408…), the rules in
`results/selection_criteria.md` (written 2026-11-13T11:21:14Z, before any query). The test split has **not** been run.

| Strategy | Hit@1 | Evidence Hit@3 | MRR@3 | Filter questions: Hit@3 / top-3 in scope | Chunks |
|---|---|---|---|---|---|
| A | 5/22 | 11/22 | 0.356 | 2/4 / 1/4 | 1393 |
| B | 11/22 | 18/22 | 0.652 | 4/4 / 3/4 | 967 |
| C | 12/22 | 18/22 | 0.682 | 4/4 / 4/4 | 967 (same index as B) |
| A2 (control, not eligible) | 9/22 | 15/22 | 0.538 | 2/4 / 2/4 | 704 |

## Applying the rules
1. Highest Evidence Hit@3: **B = C = 18/22** (A 11/22).
2. Tie → Hit@1: C 12/22 vs B 11/22 (C better by one question, `d20`).
3. Rule 5 (noise): B and C differ by 0 on Hit@3 and by 1 on Hit@1 → "no clear difference"; rule 3 (resources) decides.
   Resources are equal: C uses exactly B's 967 chunks and vectors. (C's measured ingest time of 0.41 s is only because its
   vectors were reused from B; it is not a real saving.)
4. Rule 4: C is chosen over B only if it is clearly better; with no clear difference **B is preferred**, because it
   needs no extra filter context at query time.

## Decision
**Selected strategy: B** (heading/paragraph-aware chunks, max 1000 chars, no filter).
A, B, C and the control A2 are all evaluated on test and reported; the decision above does not change after that.

## What dev already shows (for the report)
* A→B (chunking changed): Hit@3 11→18, Hit@1 5→11. A's misses are mostly `evidence_split` (6 of 11): 500-char windows cut the evidence.
* A→A2 (only size changed) recovers part of it (11→15); A2→B (same cap, boundaries changed) adds more (15→18).
* B→C (only the filter changed): the single difference is `d20`, where B ranks the PodGroup-priority page
  (workload-api) above the Pod PriorityClass page (rank 3); the `pods` filter moves the gold chunk to rank 1.
