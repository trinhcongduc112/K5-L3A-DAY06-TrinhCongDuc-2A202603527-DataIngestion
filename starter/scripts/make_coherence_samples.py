"""Pick the 10 source positions used to judge chunk coherence, then export the chunk that covers each one.

Run from starter/:  python scripts/make_coherence_samples.py

Selection rule (fixed in advance, independent of any retrieval result):
  * seed 20261113; 3 positions from `services-networking` (11 docs) and 7 from `workloads` (32 docs),
    roughly proportional to the corpus; distinct documents.
  * inside each chosen document the candidates are paragraph/list blocks (not code, not headings)
    with >= 200 chars that are not under "What's next"; one is drawn at random.
  * the position is the middle character of that block.
For every strategy the chunk that covers the position is exported (the first one when two overlap).
C uses B's chunks, so only A, B and the control A2 are exported; C inherits B's labels.
Labels (0/1/2) are written afterwards in results/audit/coherence_labels.csv.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunking import SectionIndex, make_chunks, parse_blocks  # noqa: E402
from src.config import AUDIT_DIR, STRATEGIES  # noqa: E402
from src.ingestion import load_markdown_corpus  # noqa: E402

SEED = 20261113
PER_SECTION = {"services-networking": 3, "workloads": 7}


def main() -> None:
    pages, _ = load_markdown_corpus()
    rng = random.Random(SEED)
    positions = []
    for section, k in PER_SECTION.items():
        docs = sorted(p.document_id for p in pages if p.metadata["section"] == section)
        for doc_id in rng.sample(docs, k):
            page = next(p for p in pages if p.document_id == doc_id)
            idx = SectionIndex(page.text)
            cands = []
            for b in parse_blocks(page.text):
                if b.kind != "text" or b.end - b.start < 200:
                    continue
                path, _ = idx.lookup(b.start)
                if path and path[0] == "What's next":
                    continue
                cands.append(b)
            b = cands[rng.randrange(len(cands))]
            pos = b.start + (b.end - b.start) // 2
            positions.append({"document_id": doc_id, "position": pos, "block_start": b.start, "block_end": b.end,
                              "heading_path": " > ".join(idx.lookup(pos)[0])})
    positions.sort(key=lambda r: (r["document_id"], r["position"]))
    for i, p in enumerate(positions, 1):
        p["sample_id"] = f"c{i:02d}"

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIT_DIR / "coherence_positions.json").write_text(json.dumps(
        {"seed": SEED, "per_section": PER_SECTION, "positions": positions}, indent=2), encoding="utf-8")
    rows = []
    for strategy in ("A", "B", "A2"):
        for p in positions:
            page = next(x for x in pages if x.document_id == p["document_id"])
            chunk = next(c for c in make_chunks(page, STRATEGIES[strategy])
                         if c.metadata["char_start"] <= p["position"] < c.metadata["char_end"])
            rows.append({"sample_id": p["sample_id"], "strategy": strategy, "document_id": p["document_id"],
                         "position": p["position"], "heading_path_at_position": p["heading_path"],
                         "chunk_id": chunk.chunk_id, "chunk_chars": len(chunk.text), "chunk_text": chunk.text})
    with open(AUDIT_DIR / "coherence_samples.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(positions)} positions, {len(rows)} chunk rows written to results/audit/")
    for p in positions:
        print(p["sample_id"], p["document_id"], p["position"], "|", p["heading_path"][:60])


if __name__ == "__main__":
    main()
