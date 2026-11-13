# Error log

Every failure met while running the pipeline, what caused it and what was done. Nothing was silently skipped and no
mock/random vectors were ever used.

| When (UTC) | Step | Error | Cause | Action |
|---|---|---|---|---|
| 2026-11-13 ~11:24 | `python -m src.run ingest` (strategy C, after A and B were stored) | `IndexError: list index out of range` in `transformers/tokenization_utils_tokenizers.py` | Bug in `MyEmbedder.count_tokens`: C re-uses B's texts, so the list of texts still to tokenize was empty and the tokenizer was called with `[]`. | Guard for an empty list added; `ingest_stats.json` is now written after every strategy. Ingest re-run for all strategies (A and B rows were upserted again: the re-run doubles as an idempotency check on real data). |
| 2026-11-13 | unit test `test_fixed_size_respects_cap_and_words` | assertion: window ends mid-word in `k8s-workloads-controllers-job` | Not a pipeline bug: the Job example prints 2,000 digits of pi with no whitespace, so a 500/1000-char window must cut inside that token. | Test narrowed: a mid-token cut is accepted only when the second half of the window has no whitespace at all. |
| 2026-11-13 ~11:40 | manual grounding labels (test) | two labels were wrong | They were first assigned while reading top-3 texts printed with a 420-character cut-off. A full-text keyword re-check of every 0/1 label found: `t08`/A chunk #1 does contain "supports and maintains AWS, and GCE" (0 → 2); `t06`/A2 chunks #3 + #2 together contain the condition and the consequence (1 → 2). | Labels corrected with a note in the `reason` column; all other 0 labels confirmed on full text. Lesson: never label from truncated output. |
