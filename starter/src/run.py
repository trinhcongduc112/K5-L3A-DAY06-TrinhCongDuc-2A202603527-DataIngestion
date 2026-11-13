"""Day 06 pipeline entry point (run from starter/).

    python -m src.run validate          # load + normalize the corpus, write the page log
    python -m src.run ingest            # chunk (A, B, C, A2) -> embed -> store in pgvector
    python -m src.run evaluate --split dev
    python -m src.run evaluate --split test   # refused until results/selection_decision.md exists
    python -m src.run reingest-check    # idempotency / changed-document / removed-document test
    python -m src.run                   # validate + ingest + evaluate --split dev  (never test)

Everything is deterministic except wall-clock timings. Backends fail loudly; nothing falls back
to mock vectors.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import make_chunks
from .config import (AUDIT_DIR, BENCHMARK_DIR, CONTROL_STRATEGIES, LOG_DIR, QUESTIONS_FILE, REPO_ROOT, RESULTS_DIR,
                     STRATEGIES, TOP_K, TRACE_DIR)
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_markdown_corpus, validate_corpus
from .store import PgVectorStore


# ------------------------------------------------------------------ helpers
def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_settings() -> tuple[str, str]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    url = os.getenv("DATABASE_URL", "")
    model = os.getenv("EMBEDDING_MODEL", "")
    if not url:
        sys.exit("DATABASE_URL missing: copy starter/.env.example to starter/.env first.")
    if not model:
        sys.exit("EMBEDDING_MODEL missing in starter/.env (this lab uses intfloat/multilingual-e5-small).")
    return url, model


def package_versions() -> dict[str, str]:
    out = {}
    for name in ("sentence-transformers", "torch", "transformers", "tokenizers", "numpy", "psycopg", "psycopg-binary",
                 "python-dotenv", "huggingface-hub"):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = "not installed"
    return out


def compose_image() -> str | None:
    compose = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    for line in compose.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("image:"):
            return line.split("image:", 1)[1].strip()
    return None


def db_info(store: PgVectorStore) -> dict[str, str]:
    with store._connect() as conn:
        pg = conn.execute("SHOW server_version").fetchone()[0]
        ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    return {"postgresql": pg, "pgvector": ext[0] if ext else "missing", "docker_image": compose_image() or "?"}


def record_environment(embedder: MyEmbedder, store: PgVectorStore) -> dict[str, Any]:
    env = {"recorded_at": now(), "python": platform.python_version(), "platform": platform.platform(),
           "cpu_count": os.cpu_count(), "packages": package_versions(), "database": db_info(store),
           "embedding": embedder.describe(), "vector_store": {"table": "chunks", "metric": "cosine (<=>)",
                                                               "search": "exact (no ANN index)"}}
    write_json(RESULTS_DIR / "environment.json", env)
    return env


def verify_freeze() -> str:
    """The benchmark must be byte-identical to the file frozen before any experiment."""
    freeze = json.loads((BENCHMARK_DIR / "FREEZE.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(QUESTIONS_FILE.read_bytes()).hexdigest()
    if digest != freeze["sha256"]:
        sys.exit("benchmark/questions.json changed after it was frozen (see benchmark/FREEZE.json). "
                 "Log the change in benchmark/CHANGELOG.md and re-freeze deliberately before evaluating.")
    return digest


# ------------------------------------------------------------------ commands
def cmd_validate(_: argparse.Namespace) -> None:
    pages, log = load_markdown_corpus()
    summary = validate_corpus(pages)
    raw_total = sum(r["raw_chars"] for r in log)
    norm_counts: Counter[str] = Counter()
    for r in log:
        norm_counts.update(r["normalization"])
    by_sub = Counter(f'{p.metadata["section"]}/{p.metadata["subsection"]}' for p in pages)
    summary.update({"raw_chars": raw_total, "normalization_totals": dict(norm_counts), "by_subsection": dict(by_sub),
                    "pages_with_warnings": [r["document_id"] for r in log if r["warnings"]],
                    "max_unit_chars": max(len(p.text) for p in pages), "validated_at": now()})
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "ingestion_pages.jsonl", "w", encoding="utf-8") as fh:
        for r in log:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_json(RESULTS_DIR / "corpus_summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _length_stats(values: list[int]) -> dict[str, float]:
    v = sorted(values)
    return {"min": v[0], "p5": v[len(v) // 20], "median": statistics.median(v), "mean": round(statistics.mean(v), 1),
            "p95": v[int(len(v) * 0.95)], "max": v[-1]}


def cmd_ingest(args: argparse.Namespace) -> None:
    url, model_name = load_settings()
    pages, _ = load_markdown_corpus()
    t0 = time.perf_counter()
    embedder = MyEmbedder(model_name)
    model_load_s = time.perf_counter() - t0
    store = PgVectorStore(url, embedder.dimensions)
    store.create_schema()
    env = record_environment(embedder, store)
    names = args.strategies or list(STRATEGIES)
    vec_cache: dict[str, list[float]] = {}
    tok_cache: dict[str, int] = {}
    stats_path = RESULTS_DIR / "ingest_stats.json"
    all_stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {"strategies": {}}
    for name in names:
        cfg = STRATEGIES[name]
        t_start = time.perf_counter()
        chunks = [c for p in pages for c in make_chunks(p, cfg)]
        t_chunk = time.perf_counter() - t_start
        texts = [c.text for c in chunks]
        unique = list(dict.fromkeys(texts))
        need = [t for t in unique if sha1(t) not in vec_cache]
        t1 = time.perf_counter()
        for i in range(0, len(need), 256):
            part = need[i:i + 256]
            for t, v in zip(part, embedder.embed_documents(part)):
                vec_cache[sha1(t)] = v
        t_embed = time.perf_counter() - t1
        t2 = time.perf_counter()
        need_tok = [t for t in unique if sha1(t) not in tok_cache]
        for t, n in zip(need_tok, embedder.count_tokens(need_tok)):
            tok_cache[sha1(t)] = n
        t_tok = time.perf_counter() - t2
        tokens = [tok_cache[sha1(t)] for t in texts]
        t3 = time.perf_counter()
        db = store.upsert(name, chunks, [vec_cache[sha1(t)] for t in texts])
        removed_docs = store.delete_missing_documents(name, [p.document_id for p in pages])
        t_db = time.perf_counter() - t3
        stat = {
            "config": cfg, "documents": len(pages), "chunks": len(chunks),
            "total_chars": sum(len(t) for t in texts), "chars": _length_stats([len(t) for t in texts]),
            "tokens": {"total": sum(tokens), "mean": round(statistics.mean(tokens), 1), "max": max(tokens),
                       "over_model_limit": sum(1 for n in tokens if n > embedder.max_seq_length),
                       "model_limit": embedder.max_seq_length},
            "time_s": {"chunking": round(t_chunk, 3), "embedding": round(t_embed, 2), "tokenizing": round(t_tok, 2),
                       "db_write": round(t_db, 2), "total_ingest": round(t_chunk + t_embed + t_db, 2)},
            "texts_embedded_now": len(need), "texts_reused_from_earlier_strategy": len(unique) - len(need),
            "cost_usd": 0.0, "db_result": db, "documents_removed_from_index": removed_docs,
            "control_only": name in CONTROL_STRATEGIES, "ingested_at": now(),
        }
        all_stats["strategies"][name] = stat
        all_stats["run"] = {"model_load_s": round(model_load_s, 2), "embedding": env["embedding"],
                            "database": env["database"], "last_run_at": now()}
        write_json(stats_path, all_stats)          # after every strategy, so a later failure loses nothing
        with open(LOG_DIR / "ingest_runs.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": now(), "strategy": name, "chunks": len(chunks), "db_result": db,
                                 "texts_embedded_now": len(need), "time_s": stat["time_s"]}) + "\n")
        print(f"[{name}] chunks={len(chunks)} tokens(max)={max(tokens)} embedded_now={len(need)} "
              f"time={stat['time_s']['total_ingest']}s db={db}")
    print("rows per strategy:", store.counts_by_strategy())


def cmd_evaluate(args: argparse.Namespace) -> None:
    benchmark_sha = verify_freeze()
    if args.split == "test" and not (RESULTS_DIR / "selection_decision.md").exists():
        sys.exit("Refusing to evaluate the test split: write results/selection_decision.md (choice made on dev only) first.")
    url, model_name = load_settings()
    embedder = MyEmbedder(model_name)
    store = PgVectorStore(url, embedder.dimensions)
    env = record_environment(embedder, store)
    questions = [q for q in json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]
                 if args.split == "all" or q["split"] == args.split]
    names = args.strategies or list(STRATEGIES)
    present = store.counts_by_strategy()
    missing = [n for n in names if present.get(n, 0) == 0]
    if missing:
        sys.exit(f"strategies not ingested yet: {missing} (run: python -m src.run ingest)")
    t0 = time.perf_counter()
    qvecs = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    embed_q_s = time.perf_counter() - t0
    traces: list[dict[str, Any]] = []
    for name in names:
        cfg = STRATEGIES[name]
        for q in questions:
            flt = q.get("filter")
            applied = bool(flt) and cfg["filter_mode"] == "metadata"
            t1 = time.perf_counter()
            hits = store.search(name, qvecs[q["id"]], TOP_K, flt if applied else None)
            ms = (time.perf_counter() - t1) * 1000
            ev = evaluate_query(q, hits)
            status = {j["rank"]: j["status"] for j in ev["judgements"]}
            traces.append({
                "strategy": name, "question_id": q["id"], "split": q["split"], "type": q["type"],
                "question": q["question"], "filter": flt, "filter_applied": applied, "top_k": TOP_K,
                "search_ms": round(ms, 2),
                "hit_at_1": ev["hit_at_1"], "hit_at_3": ev["hit_at_3"], "first_hit_rank": ev["first_hit_rank"],
                "failure_mode": ev["failure_mode"], "scope_compliant_top3": ev["scope_compliant_top3"],
                "gold": {"source_id": q["gold_source_id"], "page": q["gold_page"], "heading": q["gold_heading"],
                         "evidence_quote": q["evidence_quote"], "expected_answer": q["expected_answer"],
                         "alt_sources": [a["source_id"] for a in q.get("alt_evidence", [])]},
                "hits": [{"rank": h["rank"], "chunk_id": h["chunk_id"], "document_id": h["document_id"], "source": h["source"],
                          "page": h["page"], "heading_path": h["metadata"]["heading_path"],
                          "section": h["metadata"]["section"], "subsection": h["metadata"]["subsection"],
                          "char_start": h["metadata"]["char_start"], "char_end": h["metadata"]["char_end"],
                          "page_end": h["metadata"]["page_end"], "score": round(h["score"], 5),
                          "status": status[h["rank"]], "text": h["text"]} for h in hits],
            })
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    for name in names:
        with open(TRACE_DIR / f"{args.split}_{name}.jsonl", "w", encoding="utf-8") as fh:
            for t in traces:
                if t["strategy"] == name:
                    fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    summary = summarize(traces)
    out = {"evaluated_at": now(), "split": args.split, "benchmark_sha256": benchmark_sha, "top_k": TOP_K,
           "embedding_model": env["embedding"]["model"], "embedding_revision": env["embedding"]["revision"],
           "query_embedding_s": round(embed_q_s, 2),
           "median_search_ms": {n: round(statistics.median(t["search_ms"] for t in traces if t["strategy"] == n), 2) for n in names},
           "metrics": summary}
    write_json(RESULTS_DIR / f"metrics_{args.split}.json", out)
    print(f"\nsplit={args.split}  questions={len(questions)}  benchmark_sha256={benchmark_sha[:12]}…")
    print(f"{'strategy':8} {'Hit@1':>8} {'Hit@3':>8} {'MRR@3':>7}  filter-q: Hit@3 / scope-ok")
    for name in names:
        for split, m in summary[name].items():
            tag = " (control)" if name in CONTROL_STRATEGIES else ""
            print(f"{name:8} {m['hit_at_1']:>8} {m['hit_at_3']:>8} {m['mrr_at_3']:>7}  "
                  f"{m['hit_at_3_on_filter_questions']:>5} / {m['scope_compliant_top3']:<5}{tag}  [{split}]")


def cmd_reingest_check(_: argparse.Namespace) -> None:
    """Prove that re-ingesting is idempotent and that changed/removed documents are handled."""
    url, model_name = load_settings()
    pages, _ = load_markdown_corpus()
    embedder = MyEmbedder(model_name)
    store = PgVectorStore(url, embedder.dimensions)
    store.create_schema()
    strategy = "_reingest_check"
    cfg = STRATEGIES["B"]
    ids = ["k8s-workloads-pods-static-pods", "k8s-workloads-pods-ephemeral-containers",
           "k8s-services-networking-ingress-controllers"]
    sample = [p for p in pages if p.document_id in ids]
    store.delete_strategy(strategy)
    cache: dict[str, list[float]] = {}

    def run(ps) -> dict[str, int]:
        chunks = [c for p in ps for c in make_chunks(p, cfg)]
        need = [c.text for c in chunks if sha1(c.text) not in cache]
        for t, v in zip(need, embedder.embed_documents(need)):
            cache[sha1(t)] = v
        res = store.upsert(strategy, chunks, [cache[sha1(c.text)] for c in chunks])
        res["chunks_in_this_ingest"] = len(chunks)
        return res

    changed_id, removed_id = "k8s-workloads-pods-static-pods", "k8s-services-networking-ingress-controllers"
    report: dict[str, Any] = {"strategy_used": strategy, "documents": ids, "changed_document": changed_id,
                              "removed_document": removed_id, "checked_at": now()}
    report["1_first_ingest"] = run(sample)
    report["2_same_version_again"] = run(sample)
    old = next(p for p in sample if p.document_id == changed_id)
    old_chunks = len(make_chunks(old, cfg))
    # edit at the very start: every later offset shifts, so every chunk id of this page changes
    changed = dataclasses.replace(old, text="Edited for the re-ingest test. " + old.text)
    report["3_one_document_changed"] = run([changed if p.document_id == changed_id else p for p in sample])
    report["3_expected"] = {"chunks_of_changed_document_before": old_chunks,
                            "chunks_of_changed_document_after": len(make_chunks(changed, cfg))}
    report["4_after_change_rows"] = store.count(strategy)
    keep = [p.document_id for p in sample if p.document_id != removed_id]
    report["5_document_removed_rows_deleted"] = store.delete_missing_documents(strategy, keep)
    report["6_rows_after_removal"] = store.count(strategy)
    store.delete_strategy(strategy)
    r1, r2, r3 = report["1_first_ingest"], report["2_same_version_again"], report["3_one_document_changed"]
    report["verdict"] = {
        "no_duplicates_on_reingest": r2["inserted"] == 0 and r2["deleted"] == 0 and r2["total_after"] == r1["total_after"],
        "obsolete_chunks_removed_when_document_changes": (
            r3["deleted"] == report["3_expected"]["chunks_of_changed_document_before"]
            and r3["inserted"] == report["3_expected"]["chunks_of_changed_document_after"]
            and r3["total_after"] == r3["chunks_in_this_ingest"]),
        "removed_document_chunks_deleted": report["5_document_removed_rows_deleted"] > 0,
    }
    write_json(RESULTS_DIR / "reingest_check.json", report)
    print(json.dumps(report, indent=2))
    if not all(report["verdict"].values()):
        sys.exit("re-ingest check FAILED")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m src.run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("validate")
    p_in = sub.add_parser("ingest")
    p_in.add_argument("--strategies", nargs="+", choices=list(STRATEGIES))
    p_ev = sub.add_parser("evaluate")
    p_ev.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p_ev.add_argument("--strategies", nargs="+", choices=list(STRATEGIES))
    sub.add_parser("reingest-check")
    args = ap.parse_args()
    for d in (LOG_DIR, TRACE_DIR, AUDIT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if args.cmd is None:
        ns = argparse.Namespace(strategies=None, split="dev")
        cmd_validate(ns)
        cmd_ingest(ns)
        cmd_evaluate(ns)
    else:
        {"validate": cmd_validate, "ingest": cmd_ingest, "evaluate": cmd_evaluate,
         "reingest-check": cmd_reingest_check}[args.cmd](args)


if __name__ == "__main__":
    main()
