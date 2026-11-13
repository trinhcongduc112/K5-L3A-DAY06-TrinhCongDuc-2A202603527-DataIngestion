"""Audit the metadata of every retrieved record against the source (criterion 3).

Run from starter/ after `python -m src.run evaluate --split test`:
    python scripts/audit_metadata.py --split test

For each top-3 record of each strategy the script re-derives the truth from the *source page* and compares:
  source        == manifest source_url of document_id
  section/subsection == manifest values
  text          == normalized page text [char_start:char_end]   (the chunk really comes from there)
  heading_path  == heading path of the section that contains char_start
  page          == H2 ordinal of char_start
  complete      == chunk does not straddle an H2 boundary (page_end == page), i.e. page/heading describe the WHOLE chunk
A record is "correct and complete" only if every check passes. "correct_start_only" means every check passes except
that the chunk straddles two H2 blocks (the metadata describes only where the chunk starts).
This is a script-assisted audit against the source (not a by-eye reading of every record); the report says so.
It also reports filter compliance for questions that carry a filter.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunking import SectionIndex  # noqa: E402
from src.config import AUDIT_DIR, STRATEGIES, TRACE_DIR  # noqa: E402
from src.ingestion import load_markdown_corpus  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--strategies", nargs="+", default=["A", "B", "C"])
    args = ap.parse_args()
    pages, _ = load_markdown_corpus()
    by_id = {p.document_id: p for p in pages}
    idx = {p.document_id: SectionIndex(p.text) for p in pages}
    rows, summary = [], {}
    for strategy in args.strategies:
        path = TRACE_DIR / f"{args.split}_{strategy}.jsonl"
        traces = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        n = ok = start_only = 0
        filt_q = filt_ok = 0
        errors: list[str] = []
        for t in traces:
            if t["filter"]:
                filt_q += 1
                filt_ok += bool(t["scope_compliant_top3"])
            for h in t["hits"]:
                n += 1
                page = by_id.get(h["document_id"])
                problems = []
                straddles, pg_end = False, h["page"]
                if page is None:
                    problems.append("unknown document_id")
                else:
                    s, e = h["char_start"], h["char_end"]
                    if h["source"] != page.metadata["source_url"]:
                        problems.append("source differs from manifest")
                    if h["section"] != page.metadata["section"] or h["subsection"] != page.metadata["subsection"]:
                        problems.append("section/subsection differs from manifest")
                    if page.text[s:e] != h["text"]:
                        problems.append("chunk text is not the page slice at char_start:char_end")
                    hp, pg = idx[h["document_id"]].lookup(s)
                    _, pg_end = idx[h["document_id"]].lookup(max(s, e - 1))
                    if " > ".join(hp) != h["heading_path"]:
                        problems.append(f"heading_path {h['heading_path']!r} != source {' > '.join(hp)!r}")
                    if pg != h["page"]:
                        problems.append(f"page {h['page']} != source {pg}")
                    straddles = pg_end != pg
                if problems:
                    verdict = "incorrect"
                elif straddles:
                    verdict = "correct_start_only"
                    start_only += 1
                else:
                    verdict = "correct_and_complete"
                    ok += 1
                if verdict != "correct_and_complete":
                    errors.append(f"{t['question_id']} rank{h['rank']} {h['chunk_id']}: {verdict}; " + "; ".join(problems or [f"chunk spans H2 pages {h['page']}-{pg_end}"]))
                rows.append({"strategy": strategy, "question_id": t["question_id"], "rank": h["rank"], "chunk_id": h["chunk_id"],
                             "document_id": h["document_id"], "source": h["source"], "page": h["page"],
                             "heading_path": h["heading_path"], "section": h["section"], "subsection": h["subsection"],
                             "char_range": f"{h['char_start']}-{h['char_end']}", "verdict": verdict,
                             "issues": "; ".join(problems) if problems else ("chunk straddles H2 pages" if straddles else "")})
        summary[strategy] = {"records": n, "correct_and_complete": ok, "correct_start_only": start_only,
                             "incorrect": n - ok - start_only, "rate_strict": f"{ok}/{n}",
                             "rate_lenient_start_correct": f"{ok + start_only}/{n}",
                             "filter_questions": filt_q, "scope_compliant_top3": f"{filt_ok}/{filt_q}" if filt_q else "N/A",
                             "issues": errors}
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_DIR / f"metadata_audit_{args.split}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (AUDIT_DIR / f"metadata_audit_{args.split}_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    for s, m in summary.items():
        print(f"{s}: strict correct+complete {m['rate_strict']}, lenient {m['rate_lenient_start_correct']}, "
              f"filter scope-compliant {m['scope_compliant_top3']}")


if __name__ == "__main__":
    main()
