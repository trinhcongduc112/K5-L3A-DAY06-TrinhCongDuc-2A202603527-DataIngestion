# Corpus — Kubernetes concepts (Workloads and Services/Networking)

| | |
|---|---|
| Publisher | The Kubernetes Authors (CNCF / Linux Foundation) |
| Source | <https://github.com/kubernetes/website>, rendered at <https://kubernetes.io/docs/concepts/> |
| Snapshot | commit `fe0b20298483501236ad25c02c4271b876144d03` (commit date 2026-11-13T07:52:06Z; it was the repo `HEAD` when accessed) |
| Accessed | 2026-11-13 |
| License | **CC BY 4.0** for the documentation (the repo `LICENSE` file is the CC BY 4.0 text; full text in [LICENSE-CC-BY-4.0.txt](LICENSE-CC-BY-4.0.txt)). Redistribution is allowed with attribution: "© The Kubernetes Authors, Kubernetes Documentation". Code samples in the repo are Apache-2.0 and are **not** part of this corpus. |
| Content | English only; no personal, confidential or secret data |

## Units and size

* One **source unit = one concept page** (43 independent pages, each >= 2,326 normalized characters, so both the
  "30 independent units" and the "1,500 characters" rules of GUIDE.md are met). Nothing is duplicated: the
  unit tests check that no two pages are identical.
* 43 pages: 11 in `services-networking`, 32 in `workloads` (subsections: `(root)`, `autoscaling`,
  `compositepodgroup-api`, `controllers`, `podgroup-api`, `pods`, `workload-api`).
* 622,448 characters as published in `pages/`; 619,252 after the pipeline's normalization (`results/corpus_summary.json`,
  per-page counters in `results/logs/ingestion_pages.jsonl`).
* [manifest.json](manifest.json) / [manifest.csv](manifest.csv): per page `source_id`, `title`, `section`,
  `subsection`, `source_url`, repository path, GitHub permalink, `git_blob_sha1` (the version of the original Markdown
  file), license, attribution, `accessed_at`, `char_count` (the unit boundaries are the whole page, `[0, char_count)`),
  `approx_printed_pages` (= chars / 3000, informational only).

## Inclusion rule and what it leaves out

Rule (from `scripts/build_corpus.py`): English concept pages under `concepts/workloads` and
`concepts/services-networking`; `_index.md` pages and pages shorter than 1,500 characters after cleaning are excluded.

Excluded pages (cleaned size): `workloads/pods/_index.md` (21,292, the main "Pods" page), `workload-api/_index.md` (7,779),
`podgroup-api/_index.md` (7,081), `compositepodgroup-api/_index.md` (5,670), `services-networking/_index.md` (4,586),
`workloads/_index.md` (4,407), `controllers/_index.md` (2,613) and `services-networking/service-traffic-policy.md` (1,491,
just under the threshold). Consequence: the benchmark cannot ask about topics that only these pages cover (for example
"what is a Pod?" or the PodGroup API overview). This is a known limitation, not an error.

## What the cleaning step changed (and lost)

`scripts/build_corpus.py` removes front matter, HTML comments and Hugo shortcodes, and reduces links to their anchor
text. Measured on the 43 source files:

* 41 `code_sample` shortcodes were dropped, so the example YAML they pull in is **missing** from the pages.
* 92 `feature-state` shortcodes were dropped (no "FEATURE STATE ..." lines); `param`/`skew` shortcodes were dropped too, so
  a few sentences lost their version number (for example "As of Kubernetes , VPA does not ..."). Benchmark evidence never uses such sentences.
* 42 `{{% heading %}}` shortcodes left empty `## ` lines; normalization restores them (41 x "What's next", 1 x
  "Before you begin"), verified against the raw shortcodes.
* 7 `figure` images are gone; 4 Mermaid diagrams remain as plain text in the HPA page; tab titles were dropped.

The pipeline normalization (`starter/src/ingestion.py`) additionally applies Unicode NFC, NBSP to space, trailing-space and
blank-line cleanup, removes Hugo heading ids (`{#id}`) and bare `<a id="...">` anchor lines, leaves code blocks intact, and
logs every change per page.

## How to rebuild and verify (reproducibility)

```bash
C=fe0b20298483501236ad25c02c4271b876144d03
S=$(mktemp -d)                                          # any empty directory outside the repo
git init -q "$S/k8s-website" && cd "$S/k8s-website"
git remote add origin https://github.com/kubernetes/website.git
git sparse-checkout set content/en/docs/concepts/workloads content/en/docs/concepts/services-networking
git fetch -q --depth 1 --filter=blob:none origin $C && git checkout -q FETCH_HEAD     # exact commit, even if HEAD moved on
cd - >/dev/null                                         # back to the repository root
# the script runs in isolated mode (-I) because the cloned repository is untrusted input
python3 -I starter/scripts/build_corpus.py "$S/k8s-website" "$S/out" $C 2026-11-13
diff -r "$S/out/pages" data/pages && diff "$S/out/manifest.json" data/manifest.json && echo identical
```

On 2026-11-13 this exact procedure produced pages and manifests **byte-identical** to the files committed here (43 pages,
622,448 characters), and the original zip the corpus came from was identical too. `git_blob_sha1` in the manifest is the
hash of the original Markdown file in that commit.
