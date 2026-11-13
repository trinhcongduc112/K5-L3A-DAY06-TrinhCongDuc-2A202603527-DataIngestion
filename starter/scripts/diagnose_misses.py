"""Post-hoc diagnosis (analysis only; nothing is tuned): for every question a strategy missed in the top-3,
find the rank of the first chunk that does contain the evidence, searching the top-50 of the same index with the
same filter mode. Also counts, over the whole index, how many chunks straddle an H2 boundary.

Run from starter/ after both evaluations:  python scripts/diagnose_misses.py
Writes results/diagnostics_misses.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from src.config import QUESTIONS_FILE, RESULTS_DIR, STRATEGIES, TRACE_DIR  # noqa: E402
from src.embeddings import MyEmbedder  # noqa: E402
from src.evaluation import evaluate_query  # noqa: E402
from src.store import PgVectorStore  # noqa: E402

DEPTH = 50


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    embedder = MyEmbedder(os.getenv("EMBEDDING_MODEL"))
    store = PgVectorStore(os.getenv("DATABASE_URL"), embedder.dimensions)
    questions = {q["id"]: q for q in json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]}
    out: dict = {"depth": DEPTH, "misses": [], "straddling_chunks": {}}
    for split in ("dev", "test"):
        for strategy, cfg in STRATEGIES.items():
            path = TRACE_DIR / f"{split}_{strategy}.jsonl"
            if not path.exists():
                continue
            for t in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
                if t["hit_at_3"]:
                    continue
                q = questions[t["question_id"]]
                flt = q.get("filter") if cfg["filter_mode"] == "metadata" else None
                hits = store.search(strategy, embedder.embed_query(q["question"]), DEPTH, flt)
                ev = evaluate_query(q, hits)
                out["misses"].append({"split": split, "strategy": strategy, "question_id": q["id"],
                                      "failure_mode_top3": t["failure_mode"],
                                      "first_evidence_rank_within_top50": ev["first_hit_rank"]})
    with store._connect() as conn:
        for strategy, n, bad in conn.execute(
                "SELECT strategy, count(*), count(*) FILTER (WHERE page_end <> page) FROM chunks GROUP BY 1 ORDER BY 1"):
            out["straddling_chunks"][strategy] = {"chunks": n, "straddle_h2": bad, "share": round(bad / n, 3)}
    (RESULTS_DIR / "diagnostics_misses.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    for m in out["misses"]:
        print(m)
    print(out["straddling_chunks"])


if __name__ == "__main__":
    main()
