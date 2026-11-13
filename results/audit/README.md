# Audits — method, rubrics and who labelled

**Who labelled.** All labels in this folder were assigned by **Claude (an AI model, via Claude Code)** following the
rubrics of GUIDE.md §4, not by an independent human annotator. Each label has a written reason. The column
`student_review` is empty: the student must read the samples, confirm or change each label, and say so in the report.
Risk of bias: the same assistant also wrote the pipeline and the benchmark.

## 1. Chunk coherence — `coherence_positions.json`, `coherence_samples.csv`, `coherence_labels.csv`

* 10 source positions picked by `starter/scripts/make_coherence_samples.py` (seed 20261113; 3 positions in
  services-networking, 7 in workloads; distinct documents; middle of a random paragraph >= 200 chars, not in "What's next").
  Positions were chosen and **all 30 judgements (40 rows including C's inherited copies) were written before any query
  was run** (column `labeled_before_retrieval_results`).
* For each strategy, the chunk covering the position is judged (A, B and the control A2; C uses B's chunks, so it inherits B's labels).
* Rubric (applied to the idea at the sampled position and to the chunk edges):
  * **2**: the idea at the position is complete and understandable alone, with its subject or lead-in, and the chunk
    does not begin or end inside another idea.
  * **1**: understandable only in part: the idea is cut at its start or end, or its lead-in/subject is in another chunk,
    or the chunk begins/ends with a dangling fragment of a neighbouring idea.
  * **0**: the idea is cut **and** loses what it is about, so it cannot be understood from this chunk.

## 2. Metadata — `metadata_audit_test.csv`, `metadata_audit_test_summary.json`

Script-assisted: `starter/scripts/audit_metadata.py` re-derives every field of every top-3 record (8 test questions x 3 x
each strategy) **from the source page** and compares: `source` vs manifest URL, `section`/`subsection` vs manifest, chunk
text vs the page slice `[char_start:char_end]`, `heading_path` and `page` (H2 ordinal) vs the section containing
`char_start`, and whether the chunk stays inside one H2 block (otherwise `page`/`heading_path` only describe its start).
"Correct and complete" requires every check. Filter compliance = all top-3 records inside the filter scope.

## 3. Grounding — `grounding_labels_test.csv`

For each test question and strategy the **top-3 together** are judged against the expected answer:
**2** = enough evidence to answer, including conditions, and traceable to a source; **1** = relevant evidence but a
needed condition/part/context is missing; **0** = no usable evidence. This judges retrieved evidence only — it is
**not** the accuracy of an LLM answer (no LLM answer is generated in this lab).
