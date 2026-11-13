"""Validate benchmark/questions_source.json against the corpus and write benchmark/questions.json.

Run from starter/:  python scripts/build_benchmark.py

What it enforces (BENCHMARK.md / GUIDE.md):
  * >= 20 questions, >= 15 dev / >= 5 test, >= 3 questions with a filter, >= 1 of them in test
  * every evidence quote exists in the *normalized* page text of its source (whitespace-insensitive)
  * dev and test do not share gold/alternative-gold documents
  * a filter only uses allowed metadata fields, existing values, scopes >= 2 documents and
    contains the gold document
  * no question copies its evidence (long common substring) and none names the gold document id
It also derives gold_page / gold_heading / evidence offsets from the page text (so they cannot be
typed wrongly) and scans the corpus for other documents that contain nearly the same sentence.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunking import SectionIndex  # noqa: E402
from src.config import BENCHMARK_DIR, FILTER_FIELDS, LOG_DIR, QUESTIONS_FILE, QUESTIONS_SOURCE  # noqa: E402
from src.ingestion import load_markdown_corpus  # noqa: E402

REQUIRED = ("id", "split", "type", "question", "expected_answer", "gold_source_id", "evidence_quote")


def flex_pattern(quote: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(tok) for tok in quote.split()))


def locate(text: str, quote: str) -> tuple[int, int, int]:
    """(start, end, occurrences) of the whitespace-insensitive quote in text; (-1,-1,0) if absent."""
    matches = list(flex_pattern(quote).finditer(text))
    if not matches:
        return -1, -1, 0
    return matches[0].start(), matches[0].end(), len(matches)


def shingles(text: str, n: int = 6) -> set[tuple[str, ...]]:
    toks = re.findall(r"\w+", text.lower())
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def main() -> int:
    src = json.loads(QUESTIONS_SOURCE.read_text(encoding="utf-8"))
    questions = src["questions"]
    pages, _ = load_markdown_corpus()
    by_id = {p.document_id: p for p in pages}
    sec_idx = {p.document_id: SectionIndex(p.text) for p in pages}
    page_shingles = {p.document_id: shingles(p.text) for p in pages}
    errors: list[str] = []
    warnings: list[str] = []
    out_rows: list[dict] = []

    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)):
        errors.append("duplicate question ids")

    def derive(source_id: str, quote: str, label: str) -> dict | None:
        page = by_id.get(source_id)
        if page is None:
            errors.append(f"{label}: unknown source_id {source_id}")
            return None
        s, e, n = locate(page.text, quote)
        if n == 0:
            errors.append(f"{label}: evidence NOT FOUND in {source_id}: {quote[:80]!r}")
            return None
        if n > 1:
            warnings.append(f"{label}: evidence occurs {n}x in {source_id} (first occurrence used)")
        path, pg = sec_idx[source_id].lookup(s)
        _, pg_end = sec_idx[source_id].lookup(e - 1)
        if pg_end != pg:
            warnings.append(f"{label}: evidence spans H2 pages {pg}-{pg_end}")
        return {"source_id": source_id, "evidence_quote": quote, "page": pg, "heading": " > ".join(path),
                "start": s, "end": e, "n_chars": e - s}

    doc_scope = defaultdict(set)   # (field, value) -> document ids
    for p in pages:
        for f in FILTER_FIELDS:
            doc_scope[(f, p.metadata[f])].add(p.document_id)

    for q in questions:
        qid = q["id"]
        for f in REQUIRED:
            if not q.get(f):
                errors.append(f"{qid}: missing field {f}")
        if q.get("split") not in ("dev", "test"):
            errors.append(f"{qid}: split must be dev or test")
        primary = derive(q["gold_source_id"], q["evidence_quote"], qid)
        accepted = [primary] if primary else []
        for i, alt in enumerate(q.get("alt_evidence", [])):
            d = derive(alt["source_id"], alt["evidence_quote"], f"{qid}.alt{i + 1}")
            if d:
                accepted.append(d)
        flt = q.get("filter")
        scope_docs = None
        if flt:
            if not q.get("filter_context"):
                errors.append(f"{qid}: filter without filter_context")
            bad = [k for k in flt if k not in FILTER_FIELDS]
            if bad:
                errors.append(f"{qid}: filter fields not allowed: {bad}")
            scope_docs = set(by_id)
            for k, v in flt.items():
                vals = doc_scope.get((k, v), set())
                if not vals:
                    errors.append(f"{qid}: filter value {k}={v!r} matches no document")
                scope_docs &= vals
            if len(scope_docs) < 2:
                errors.append(f"{qid}: filter scope has {len(scope_docs)} document(s); need >= 2")
            if q["gold_source_id"] not in scope_docs:
                errors.append(f"{qid}: gold document is outside its own filter scope")
            for k, v in flt.items():
                if v == q["gold_source_id"] or q["gold_source_id"].endswith(str(v)):
                    errors.append(f"{qid}: filter value names the gold document")
        # leakage: the question must not copy the evidence or name the gold id
        sm = SequenceMatcher(None, q["question"].lower(), q["evidence_quote"].lower(), autojunk=False)
        lcs = sm.find_longest_match(0, len(q["question"]), 0, len(q["evidence_quote"])).size
        if lcs >= 60:
            warnings.append(f"{qid}: question shares a {lcs}-char substring with its evidence")
        if q["gold_source_id"].lower() in q["question"].lower():
            errors.append(f"{qid}: question contains the gold source id")
        # other documents containing nearly the same sentence
        quote_sh = shingles(q["evidence_quote"])
        near = []
        accepted_ids = {a["source_id"] for a in accepted}
        for did, sh in page_shingles.items():
            if did in accepted_ids or not quote_sh:
                continue
            frac = len(quote_sh & sh) / len(quote_sh)
            if frac >= 0.4:
                near.append((did, round(frac, 2)))
        if near:
            warnings.append(f"{qid}: other documents share >=40% of the evidence shingles: {near} -> review as possible extra valid sources")
        if primary:
            row = dict(q)
            row.update({
                "gold_page": primary["page"], "gold_heading": primary["heading"],
                "gold_section": by_id[q["gold_source_id"]].metadata["section"],
                "gold_subsection": by_id[q["gold_source_id"]].metadata["subsection"],
                "evidence_start": primary["start"], "evidence_end": primary["end"],
                "evidence_chars": primary["n_chars"],
                "alt_evidence": [{"source_id": a["source_id"], "evidence_quote": a["evidence_quote"], "gold_page": a["page"],
                                  "gold_heading": a["heading"], "evidence_start": a["start"], "evidence_end": a["end"]}
                                 for a in accepted[1:]],
                "filter_scope_documents": len(scope_docs) if scope_docs else None,
            })
            out_rows.append(row)

    # ---- split-level checks
    dev = [q for q in questions if q.get("split") == "dev"]
    test = [q for q in questions if q.get("split") == "test"]
    n_filter = [q for q in questions if q.get("filter")]
    if len(questions) < 20:
        errors.append(f"need >= 20 questions, have {len(questions)}")
    if len(dev) < 15:
        errors.append(f"need >= 15 dev, have {len(dev)}")
    if len(test) < 5:
        errors.append(f"need >= 5 test, have {len(test)}")
    if len(n_filter) < 3:
        errors.append(f"need >= 3 filter questions, have {len(n_filter)}")
    if not any(q.get("filter") for q in test):
        errors.append("need >= 1 filter question in test")

    def docs_of(qs: list[dict]) -> set[str]:
        s: set[str] = set()
        for q in qs:
            s.add(q["gold_source_id"])
            s.update(a["source_id"] for a in q.get("alt_evidence", []))
        return s

    overlap = docs_of(dev) & docs_of(test)
    if overlap:
        errors.append(f"dev and test share gold/alt documents: {sorted(overlap)}")

    evid_len = [r["evidence_chars"] for r in out_rows]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions": len(questions), "dev": len(dev), "test": len(test),
        "with_filter": {"total": len(n_filter), "dev": sum(1 for q in dev if q.get("filter")),
                        "test": sum(1 for q in test if q.get("filter"))},
        "types": {s: dict(Counter(q["type"] for q in qs)) for s, qs in (("dev", dev), ("test", test))},
        "gold_documents": {"dev": len(docs_of(dev)), "test": len(docs_of(test)), "overlap": sorted(overlap)},
        "questions_with_alternative_evidence": [q["id"] for q in questions if q.get("alt_evidence")],
        "evidence_chars": {"min": min(evid_len) if evid_len else None, "max": max(evid_len) if evid_len else None,
                           "mean": round(sum(evid_len) / len(evid_len), 1) if evid_len else None},
        "errors": errors, "warnings": warnings,
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "benchmark_validation.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("errors", "warnings")}, indent=2, ensure_ascii=False))
    for w in warnings:
        print("WARNING:", w)
    if errors:
        for e in errors:
            print("ERROR:", e)
        return 1

    final = {k: v for k, v in src.items() if k != "questions"}
    final["corpus_manifest"] = "data/manifest.json"
    final["questions"] = out_rows
    QUESTIONS_FILE.write_text(json.dumps(final, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with open(BENCHMARK_DIR / "questions.csv", "w", newline="", encoding="utf-8") as fh:
        cols = ["id", "split", "type", "question", "expected_answer", "gold_source_id", "gold_page", "gold_heading",
                "evidence_quote", "filter", "alt_sources"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in out_rows:
            w.writerow({**{c: r.get(c, "") for c in cols}, "filter": json.dumps(r["filter"]) if r["filter"] else "",
                        "alt_sources": ";".join(a["source_id"] for a in r["alt_evidence"])})
    digest = hashlib.sha256(QUESTIONS_FILE.read_bytes()).hexdigest()
    print(f"\nOK: wrote {QUESTIONS_FILE.relative_to(QUESTIONS_FILE.parents[1])} ({len(out_rows)} questions), sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
