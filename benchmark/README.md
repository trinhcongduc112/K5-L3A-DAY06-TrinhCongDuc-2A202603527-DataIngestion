# Benchmark — 30 questions over the Kubernetes corpus

| File | What it is |
|---|---|
| [questions_source.json](questions_source.json) | The questions as written (id, split, type, question, expected answer, gold source, evidence quote, optional filter / alternative evidence). **Authoring input.** |
| [questions.json](questions.json) / [questions.csv](questions.csv) | Output of `starter/scripts/build_benchmark.py`: the same questions plus derived, verified fields (`gold_page`, `gold_heading`, `gold_section/subsection`, `evidence_start/end`). **This is what the pipeline reads.** |
| [FREEZE.json](FREEZE.json) | SHA-256 and UTC time at which `questions.json` was frozen — before any chunk was embedded or any query ran. `src/run.py` refuses to evaluate if the file no longer matches. |
| [CHANGELOG.md](CHANGELOG.md) | Any change after the freeze must be logged here. |
| `../results/logs/benchmark_validation.json` | Result of every check below (errors = 0, warnings = 0). |

## Size and split (decided before any experiment)

* 30 questions: **22 dev** (`d01`–`d22`) and **8 test** (`t01`–`t08`).
* Types — dev: 6 direct, 6 paraphrase, 6 condition/exception, 4 metadata-scope; test: 2 of each.
* **6 questions carry a metadata filter** (4 dev: `d18`–`d21`; 2 test: `t06`, `t07`).
* Split by **document**: no gold or alternative-gold document appears in both dev and test (checked by the script).
  Topical leakage remains possible (e.g. `ingress` in dev vs `ingress-controllers` in test; Pod hostname vs DNS for Pods;
  static Pods vs DaemonSet), so the test set is not topic-independent of dev.
* Questions are in English because the corpus is English; cross-language retrieval is not measured.

## Fields

`id`, `split`, `type` (`direct` / `paraphrase` / `condition_exception` / `metadata_scope`), `question`, `expected_answer`,
`gold_source_id` (= `document_id` in the manifest), `gold_page` (**H2 ordinal inside the page**: 1 = text before the first
H2; the corpus unit itself is the whole page), `gold_heading`, `evidence_quote`, `evidence_start/end` (character offsets
in the normalized page), `alt_evidence` (other sources that are equally valid), `filter` + `filter_context`, `notes`.

## How evidence was checked

1. `evidence_quote` must be found in the **normalized** text of its source page (whitespace-insensitive) — all 30 are, each
   exactly once. Quotes are 80–403 characters (mean 198) and include the conditions/exceptions the answer needs.
2. The script scans the whole corpus for other documents sharing >= 40 % of a quote's 6-word shingles; none did, and the two
   questions whose sentence appears twice (`d07` TTL page + Job page, `d08` probes page + Pod lifecycle page) list both as accepted.
3. A hit in the evaluation means: the chunk is from an accepted document **and contains the whole quote**. A chunk with
   only part of the evidence is reported as `evidence_split`, not as a hit.

## Filters

A filter is context available before retrieval (the docs area the reader is browsing), e.g. `{"section": "workloads",
"subsection": "workload-api"}`. It never names the gold document, always contains the gold document, scopes 4–32 documents,
and uses only `section` / `subsection`, which come from the file path in the repository (not guessed). For questions
without a filter, strategy C runs unfiltered, exactly like B.

## Authorship and review

The questions were drafted by Claude (an AI) from the corpus pages and verified programmatically. They are **not** a
substitute for the student's own review: read `questions.csv` and challenge any question or expected answer.
