"""Check the submission against SUBMISSION.md / RUBRIC.md / BENCHMARK.md. Read-only: it never rewrites results.

Run from starter/ (database container running):  python scripts/verify_submission.py
Prints PASS / WARN / FAIL per check; exit code 1 if any FAIL. WARN = something only the student can do.

Hit@1 / Hit@3 are recomputed here with an independent implementation (not src/evaluation.py), every retrieved
chunk is checked to be an exact slice of its source page, and a few queries are re-run to confirm the stored
traces are reproducible.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
sys.path.insert(0, str(STARTER))

from dotenv import load_dotenv  # noqa: E402

from src.ingestion import load_markdown_corpus  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []
STRATS = ("A", "B", "C", "A2")


def check(ok: bool | None, name: str, detail: str = "") -> None:
    RESULTS.append(("PASS" if ok else ("WARN" if ok is None else "FAIL"), name, detail))


def j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> int:
    # ---------------------------------------------------------------- files
    need = ["STUDENT.md", "README.md", "data/manifest.json", "data/manifest.csv", "data/README.md",
            "benchmark/questions.json", "benchmark/FREEZE.json", "artifacts/experiment_log.csv",
            "results/metrics_dev.json", "results/metrics_test.json", "results/ingest_stats.json",
            "results/selection_criteria.md", "results/selection_decision.md", "results/reingest_check.json",
            "results/audit/coherence_labels.csv", "results/audit/grounding_labels_test.csv",
            "results/audit/metadata_audit_test.csv", "results/logs/errors.md", "results/logs/ingestion_pages.jsonl",
            "report/individual/2A202603527_TrinhCongDuc.md"]
    missing = [f for f in need if not (ROOT / f).is_file() or (ROOT / f).stat().st_size == 0]
    check(not missing, "required files exist and are not empty", ", ".join(missing) or f"{len(need)} files")

    # ---------------------------------------------------------------- corpus + manifest
    pages, log = load_markdown_corpus()
    by_id = {p.document_id: p for p in pages}
    check(len(pages) >= 30 and min(len(p.text) for p in pages) >= 1500, "corpus >= 30 units of >= 1,500 chars",
          f"{len(pages)} units, shortest {min(len(p.text) for p in pages)} chars")
    man = j(ROOT / "data/manifest.json")
    fields = ("source_id", "title", "source_url", "license", "accessed_at", "char_count", "git_blob_sha1")
    bad = [d["source_id"] for d in man["documents"] if any(not d.get(f) for f in fields)]
    check(not bad, "manifest: source, title, URL, license, accessed_at, char count, version per page", ", ".join(bad) or "43/43 complete")
    check(all(r["status"] == "ok" for r in log), "page log: no failed/empty page", f"{sum(r['status'] == 'ok' for r in log)}/{len(log)} ok")

    # ---------------------------------------------------------------- benchmark
    bench = j(ROOT / "benchmark/questions.json")["questions"]
    dev = [q for q in bench if q["split"] == "dev"]
    test = [q for q in bench if q["split"] == "test"]
    flt = [q for q in bench if q.get("filter")]
    check(len(bench) >= 20 and len(dev) >= 15 and len(test) >= 5, ">= 20 questions, >= 15 dev / >= 5 test",
          f"{len(bench)} = {len(dev)} dev + {len(test)} test")
    check(len(flt) >= 3 and any(q["split"] == "test" for q in flt), ">= 3 filter questions, >= 1 in test",
          f"{len(flt)} ({sum(q['split'] == 'test' for q in flt)} in test)")
    req = ("id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote")
    check(all(all(q.get(f) not in (None, "") for f in req) for q in bench), "every question has id/split/question/answer/source/page/evidence")
    not_found = []
    for q in bench:
        for src, quote in [(q["gold_source_id"], q["evidence_quote"])] + [(a["source_id"], a["evidence_quote"]) for a in q.get("alt_evidence", [])]:
            if ws(quote) not in ws(by_id[src].text):
                not_found.append(q["id"])
    check(not not_found, "every evidence quote exists in its normalized source page", ", ".join(not_found) or f"{len(bench)}/{len(bench)}")
    dev_docs = {q["gold_source_id"] for q in dev} | {a["source_id"] for q in dev for a in q.get("alt_evidence", [])}
    test_docs = {q["gold_source_id"] for q in test} | {a["source_id"] for q in test for a in q.get("alt_evidence", [])}
    check(not dev_docs & test_docs, "dev and test share no gold document", ", ".join(sorted(dev_docs & test_docs)) or "disjoint")
    freeze = j(ROOT / "benchmark/FREEZE.json")
    digest = hashlib.sha256((ROOT / "benchmark/questions.json").read_bytes()).hexdigest()
    check(digest == freeze["sha256"], "benchmark unchanged since it was frozen", f"sha256 {digest[:12]}…")

    # ---------------------------------------------------------------- timeline (no peeking at test)
    crit = re.search(r"Written: (\S+)", (ROOT / "results/selection_criteria.md").read_text(encoding="utf-8")).group(1)
    deci = re.search(r"Written: (\S+)", (ROOT / "results/selection_decision.md").read_text(encoding="utf-8")).group(1)
    coh_rows = list(csv.DictReader(open(ROOT / "results/audit/coherence_labels.csv", encoding="utf-8")))
    order = [("benchmark frozen", freeze["frozen_at_utc"]), ("selection criteria", crit),
             ("coherence labels", coh_rows[0]["labeled_at_utc"]),
             ("dev evaluated", j(ROOT / "results/metrics_dev.json")["evaluated_at"]),
             ("selection decision", deci), ("test evaluated", j(ROOT / "results/metrics_test.json")["evaluated_at"])]
    ok = all(ts(order[i][1]) <= ts(order[i + 1][1]) for i in range(len(order) - 1))
    check(ok, "order: freeze < criteria < coherence labels < dev < decision < test",
          " < ".join(f"{n} {t[11:19]}" for n, t in order))

    # ---------------------------------------------------------------- traces: recompute metrics independently
    metrics = {sp: j(ROOT / f"results/metrics_{sp}.json")["metrics"] for sp in ("dev", "test")}
    slice_bad, recompute_bad, trace_rows = 0, [], 0
    for sp, qs in (("dev", dev), ("test", test)):
        qmap = {q["id"]: q for q in qs}
        for s in STRATS:
            tr = [json.loads(line) for line in open(ROOT / f"results/traces/{sp}_{s}.jsonl", encoding="utf-8")]
            if len(tr) != len(qs) or any(len(t["hits"]) != 3 for t in tr):
                recompute_bad.append(f"{sp}/{s}: wrong number of rows or hits")
                continue
            h1 = h3 = 0
            for t in tr:
                q = qmap[t["question_id"]]
                acc = [(q["gold_source_id"], ws(q["evidence_quote"]))] + [(a["source_id"], ws(a["evidence_quote"])) for a in q.get("alt_evidence", [])]
                flags = [any(h["document_id"] == d and e in ws(h["text"]) for d, e in acc) for h in t["hits"]]
                h1 += flags[0]
                h3 += any(flags)
                for h in t["hits"]:
                    trace_rows += 1
                    if by_id[h["document_id"]].text[h["char_start"]:h["char_end"]] != h["text"]:
                        slice_bad += 1
            m = metrics[sp][s][sp]
            if (m["hit_at_1_count"], m["hit_at_3_count"]) != (h1, h3):
                recompute_bad.append(f"{sp}/{s}: file {m['hit_at_1']} {m['hit_at_3']} vs recomputed {h1}/{len(qs)} {h3}/{len(qs)}")
    check(not recompute_bad, "Hit@1 / Hit@3 recomputed independently from the traces = metrics files",
          "; ".join(recompute_bad) or "dev + test x A, B, C, A2 identical")
    check(slice_bad == 0, "every retrieved chunk is an exact slice of its source page", f"{trace_rows - slice_bad}/{trace_rows} records")

    # ---------------------------------------------------------------- report + experiment log agree with results
    rep = (ROOT / "report/individual/2A202603527_TrinhCongDuc.md").read_text(encoding="utf-8")
    mism = []
    for line in rep.splitlines():
        m = re.match(r"\|\s*\**(A2|A|B|C)\b[^|]*\|\s*(dev|test)\s*\|\s*(\d+/\d+)\s*\|\s*(\d+/\d+)\s*\|", line)
        if m:
            s, sp, a1, a3 = m.groups()
            mm = metrics[sp][s][sp]
            if (a1, a3) != (mm["hit_at_1"], mm["hit_at_3"]):
                mism.append(f"{s}/{sp}")
    check(not mism, "report table 1 numbers = metrics files", ", ".join(mism) or "8/8 rows match")
    elog = list(csv.DictReader(open(ROOT / "artifacts/experiment_log.csv", encoding="utf-8")))
    emis = []
    for r in elog:
        s = r["strategy"].split()[0]
        exp = (metrics["dev"][s]["dev"]["hit_at_1"], metrics["dev"][s]["dev"]["hit_at_3"],
               metrics["test"][s]["test"]["hit_at_1"], metrics["test"][s]["test"]["hit_at_3"])
        if (r["dev_hit1"], r["dev_hit3"], r["test_hit1"], r["test_hit3"]) != exp or any(not v for v in r.values()):
            emis.append(s)
    check({r["strategy"].split()[0] for r in elog} >= {"A", "B", "C"} and not emis,
          "experiment log: A, B, C rows complete and equal to metrics", ", ".join(emis) or f"{len(elog)} rows")
    absent = [k for k in ("Độ chính xác truy xuất", "mạch lạc", "metadata", "Grounding", "Tác động của chiến lược dữ liệu",
                          "Hai ví dụ sai", "Chiến lược chọn", "Hạn chế", "Sử dụng AI") if k.lower() not in rep.lower()]
    check(not absent, "report has the 5 dimensions, 2 error examples, choice, limitations, AI disclosure",
          "missing: " + ", ".join(absent) if absent else "all sections present")

    # ---------------------------------------------------------------- audits
    grd = list(csv.DictReader(open(ROOT / "results/audit/grounding_labels_test.csv", encoding="utf-8")))
    labels = ("0", "1", "2")
    check(all(len([r for r in coh_rows if r["strategy"] == s and r["label"] in labels and r["reason"]]) == 10 for s in ("A", "B", "C")),
          "coherence: 10 labelled positions with reasons for A, B, C")
    check(all(len([r for r in grd if r["strategy"] == s and r["label"] in labels and r["reason"]]) == len(test) for s in ("A", "B", "C")),
          f"grounding: all {len(test)} test questions labelled with reasons for A, B, C")
    meta = j(ROOT / "results/audit/metadata_audit_test_summary.json")
    check(all(meta[s]["records"] == 3 * len(test) for s in ("A", "B", "C")), "metadata audit: every test top-3 record checked",
          ", ".join(f"{s} {meta[s]['rate_strict']}" for s in ("A", "B", "C")))
    unreviewed = sum(1 for r in coh_rows + grd if not r["student_review"].strip())
    check(None if unreviewed else True, "labels reviewed by the student (column student_review)",
          f"{unreviewed} rows not reviewed yet — labels were written by Claude (AI)" if unreviewed else "all reviewed")

    # ---------------------------------------------------------------- database + reproducibility
    load_dotenv(STARTER / ".env")
    try:
        from src.embeddings import MyEmbedder
        from src.store import PgVectorStore
        emb = MyEmbedder(os.getenv("EMBEDDING_MODEL"))
        store = PgVectorStore(os.getenv("DATABASE_URL"), emb.dimensions)
        counts = store.counts_by_strategy()
        stats = j(ROOT / "results/ingest_stats.json")["strategies"]
        check(all(counts.get(s) == stats[s]["chunks"] for s in STRATS) and emb.dimensions == 384,
              "pgvector rows per strategy = ingest stats; real 384-dim model",
              ", ".join(f"{s}={counts.get(s)}" for s in STRATS))
        repro = []
        for qid in ("d01", "d20", "t03"):
            q = next(x for x in bench if x["id"] == qid)
            vec = emb.embed_query(q["question"])
            for s in ("B", "C"):
                f = q.get("filter") if s == "C" else None
                got = [h["chunk_id"] for h in store.search(s, vec, 3, f)]
                stored = next(json.loads(line) for line in open(ROOT / f"results/traces/{q['split']}_{s}.jsonl", encoding="utf-8")
                              if json.loads(line)["question_id"] == qid)
                if got != [h["chunk_id"] for h in stored["hits"]]:
                    repro.append(f"{qid}/{s}")
        check(not repro, "re-running queries reproduces the stored top-3 (d01, d20, t03 on B and C)", ", ".join(repro) or "identical")
    except Exception as exc:  # database down, model missing, ...
        check(False, "database / model reachable", repr(exc)[:200])

    # ---------------------------------------------------------------- hygiene + student actions
    tracked = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    secret = re.compile(r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|hf_[A-Za-z0-9]{30,}|(OPENAI|GEMINI|OPENROUTER)_API_KEY=\S+)")
    leaks = [f for f in tracked if (ROOT / f).is_file() and (ROOT / f).stat().st_size < 5_000_000
             and secret.search((ROOT / f).read_text(encoding="utf-8", errors="ignore"))]
    check(not leaks and "starter/.env" not in tracked, "no API key / .env in files that would be committed", ", ".join(leaks) or "clean")
    student = (ROOT / "STUDENT.md").read_text(encoding="utf-8")
    todo = [k for k in ("Repo bài nộp", "Commit chốt bài") if re.search(rf"{k}:\s*_?\(điền", student)]
    check(None if todo else True, "STUDENT.md complete", f"still to fill: {', '.join(todo)}" if todo else "")
    dirty = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
    check(None if dirty else True, "work committed and pushed", f"{len(dirty)} paths not committed yet" if dirty else "clean")

    width = max(len(n) for _, n, _ in RESULTS)
    for status, name, detail in RESULTS:
        print(f"[{status}] {name:<{width}}  {detail}")
    n = {k: sum(1 for s, _, _ in RESULTS if s == k) for k in ("PASS", "WARN", "FAIL")}
    print(f"\n{n['PASS']} PASS, {n['WARN']} WARN (student actions), {n['FAIL']} FAIL")
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
