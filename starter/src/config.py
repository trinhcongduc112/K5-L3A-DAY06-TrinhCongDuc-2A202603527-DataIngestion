"""Single place for paths and the experiment configuration (strategies A / B / C).

The three required strategies share the same corpus, embedding model, vector store and
cosine metric. `A2` is an extra *control* (same chunker as A but with B's size cap) used
only to tell apart "bigger chunks" from "better boundaries"; it is never a candidate for
selection (see results/selection_criteria.md).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
PAGES_DIR = DATA_DIR / "pages"
MANIFEST_JSON = DATA_DIR / "manifest.json"
BENCHMARK_DIR = REPO_ROOT / "benchmark"
QUESTIONS_SOURCE = BENCHMARK_DIR / "questions_source.json"
QUESTIONS_FILE = BENCHMARK_DIR / "questions.json"
RESULTS_DIR = REPO_ROOT / "results"
LOG_DIR = RESULTS_DIR / "logs"
TRACE_DIR = RESULTS_DIR / "traces"
AUDIT_DIR = RESULTS_DIR / "audit"

TOP_K = 3
FILTER_FIELDS = ("section", "subsection")  # metadata fields allowed in a filter

# chunker: name of a function in src/chunking.py; filter_mode: "none" | "metadata"
STRATEGIES: dict[str, dict] = {
    "A": {
        "chunker": "fixed_size", "size": 500, "overlap": 50, "filter_mode": "none",
        "description": "Fixed-size windows of 500 chars, overlap 50, snapped to word boundaries",
    },
    "B": {
        "chunker": "by_paragraph", "max_size": 1000, "min_size": 300, "filter_mode": "none",
        "description": "Heading/paragraph-aware chunks, max 1000 chars, never crossing an H2",
    },
    "C": {
        "chunker": "by_paragraph", "max_size": 1000, "min_size": 300, "filter_mode": "metadata",
        "description": "Same chunks as B + metadata filter (section/subsection) when the question has one",
    },
    "A2": {
        "chunker": "fixed_size", "size": 1000, "overlap": 100, "filter_mode": "none",
        "description": "CONTROL: fixed-size windows of 1000 chars, overlap 100 (B's size cap)",
    },
}
REQUIRED_STRATEGIES = ("A", "B", "C")
CONTROL_STRATEGIES = ("A2",)
