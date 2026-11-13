"""Evaluate retrieved evidence automatically and keep a full per-query trace.

Definitions (GUIDE.md section 4):
  * hit        = the chunk belongs to an accepted gold document AND contains the whole accepted
                 evidence quote (whitespace-insensitive). Alternative sources listed in the benchmark
                 are accepted as well.
  * Hit@1      = questions whose top-1 chunk is a hit / questions
  * Evidence Hit@3 = questions with at least one hit in the top-3 / questions

Human judgements (chunk coherence, grounding sufficiency, metadata correctness) are NOT inferred
from string matching; they live in results/audit/.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def accepted_evidence(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Primary + alternative evidence as {source_id, quote, start, end}."""
    acc = [{"source_id": question["gold_source_id"], "quote": norm(question["evidence_quote"]),
            "start": question["evidence_start"], "end": question["evidence_end"]}]
    for a in question.get("alt_evidence", []):
        acc.append({"source_id": a["source_id"], "quote": norm(a["evidence_quote"]),
                    "start": a["evidence_start"], "end": a["evidence_end"]})
    return acc


def within_filter(hit: dict[str, Any], flt: dict[str, Any] | None) -> bool:
    return all(hit["metadata"].get(k) == v for k, v in (flt or {}).items())


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Score one query. `hits` are search() results (rank order). Returns a trace-ready dict."""
    acc = accepted_evidence(question)
    acc_ids = {a["source_id"] for a in acc}
    judged = []
    for h in hits:
        text = norm(h["text"])
        contains = any(a["source_id"] == h["document_id"] and a["quote"] in text for a in acc)
        same_doc = h["document_id"] in acc_ids
        cs, ce = h["metadata"]["char_start"], h["metadata"]["char_end"]
        overlaps = any(a["source_id"] == h["document_id"] and cs < a["end"] and a["start"] < ce for a in acc)
        if contains:
            status = "hit"
        elif same_doc and overlaps:
            status = "evidence_split"          # right place, but the chunk holds only part of the evidence
        elif same_doc:
            status = "right_document_other_passage"
        else:
            status = "wrong_document"
        judged.append({"rank": h["rank"], "chunk_id": h["chunk_id"], "status": status})
    hit_ranks = [j["rank"] for j in judged if j["status"] == "hit"]
    first = hit_ranks[0] if hit_ranks else None
    failure = None
    if first is None:
        statuses = {j["status"] for j in judged}
        for s in ("evidence_split", "right_document_other_passage", "wrong_document"):
            if s in statuses:
                failure = s
                break
    flt = question.get("filter")
    return {
        "hit_at_1": first == 1, "hit_at_3": first is not None, "first_hit_rank": first,
        "failure_mode": failure, "judgements": judged,
        "scope_compliant_top3": (all(within_filter(h, flt) for h in hits) if flt else None),
    }


def _rate(n: int, d: int) -> str:
    return f"{n}/{d}" if d else "N/A"


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 / Evidence Hit@3 by strategy and split (counts, not only percentages)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
    out: dict[str, Any] = {}
    for (strategy, split), ts in sorted(groups.items()):
        n = len(ts)
        h1 = sum(t["hit_at_1"] for t in ts)
        h3 = sum(t["hit_at_3"] for t in ts)
        ft = [t for t in ts if t["filter"]]
        by_type: dict[str, dict[str, Any]] = {}
        for typ in sorted({t["type"] for t in ts}):
            tt = [t for t in ts if t["type"] == typ]
            by_type[typ] = {"n": len(tt), "hit_at_1": _rate(sum(t["hit_at_1"] for t in tt), len(tt)),
                            "hit_at_3": _rate(sum(t["hit_at_3"] for t in tt), len(tt))}
        mrr = sum((1.0 / t["first_hit_rank"]) if t["first_hit_rank"] else 0.0 for t in ts) / n
        out.setdefault(strategy, {})[split] = {
            "n": n, "hit_at_1_count": h1, "hit_at_3_count": h3,
            "hit_at_1": _rate(h1, n), "hit_at_3": _rate(h3, n),
            "hit_at_1_pct": round(100 * h1 / n, 1), "hit_at_3_pct": round(100 * h3 / n, 1),
            "mrr_at_3": round(mrr, 3),
            "filter_questions": len(ft),
            "filter_applied": sum(1 for t in ft if t["filter_applied"]),
            "scope_compliant_top3": _rate(sum(1 for t in ft if t["scope_compliant_top3"]), len(ft)),
            "hit_at_3_on_filter_questions": _rate(sum(t["hit_at_3"] for t in ft), len(ft)),
            "hit_at_1_on_filter_questions": _rate(sum(t["hit_at_1"] for t in ft), len(ft)),
            "by_type": by_type,
            "failure_modes": dict(sorted(_count(t["failure_mode"] for t in ts if t["failure_mode"]).items())),
        }
    return out


def _count(items) -> dict[str, int]:
    d: dict[str, int] = defaultdict(int)
    for i in items:
        d[i] += 1
    return d
