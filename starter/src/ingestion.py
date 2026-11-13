"""Read and normalize the Markdown corpus.

The corpus (43 Kubernetes concept pages) is produced by `scripts/build_corpus.py` and described
by `data/manifest.json`. There is no PDF in this lab, so `pypdf` is not used.

Normalization is deterministic and reports every change it makes, so the page log shows what
happened to each page. Evidence quotes in the benchmark are verified against the *normalized*
text, which is also the text that gets chunked, embedded and stored.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from .config import MANIFEST_JSON, PAGES_DIR
from .models import DocumentPage

MIN_UNITS = 30          # GUIDE.md: at least 30 content pages / independent units
MIN_UNIT_CHARS = 1500   # GUIDE.md: a unit of non-paginated text needs >= 1,500 normalized chars


class CorpusError(RuntimeError):
    """Raised (never swallowed) when the corpus does not meet the lab requirements."""


_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")
_EMPTY_HEADING = re.compile(r"^(#{2,6})[ \t]*$")
_HEADING_LINE = re.compile(r"^#{2,6}[ \t]+\S")
_HEADING_ATTR = re.compile(r"[ \t]*\{#[^{}\s]+\}[ \t]*$")
_ANCHOR_LINE = re.compile(r'^\s*<a\s+(?:id|name)="[^"]*"\s*(?:/>|>\s*</a>)\s*$')
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


def fence_marker(line: str) -> str | None:
    """Return the code-fence marker (``` or ~~~, any length >= 3) opening on this line."""
    m = _FENCE_OPEN.match(line)
    return m.group(1) if m else None


def closes_fence(line: str, opener: str) -> bool:
    s = line.strip()
    return bool(s) and set(s) == {opener[0]} and len(s) >= len(opener)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_with_report(text: str) -> tuple[str, dict[str, int]]:
    """Normalize one page and return (text, counters of what changed).

    * Unicode NFC, CRLF -> LF, NBSP -> space, zero-width characters removed.
    * Trailing whitespace stripped; runs of blank lines collapsed to one (outside code fences).
    * Hugo heading ids (`## Title {#id}`) and standalone `<a id="..."/>` anchor lines removed.
    * Empty headings left behind when the build step stripped `{{% heading "..." %}}` shortcodes
      are restored: the first heading of a page -> "Before you begin", otherwise "What's next".
    * Code blocks (fenced) are left intact apart from trailing whitespace.
    """
    rep: Counter[str] = Counter()
    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        rep["unicode_nfc_changed"] = 1
    text = nfc
    if "\r" in text:
        rep["crlf_converted"] = text.count("\r")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    rep["nbsp_replaced"] = text.count(" ")
    text = text.replace(" ", " ")
    rep["invisible_removed"] = sum(text.count(chr(c)) for c in _INVISIBLE)
    text = text.translate(_INVISIBLE)

    out: list[str] = []
    fence: str | None = None
    seen_heading = False
    blank_run = 0
    for raw in text.split("\n"):
        line = raw.rstrip()
        if line != raw:
            rep["trailing_ws_lines"] += 1
        if fence is not None:                      # inside a code block: keep as is
            out.append(line)
            if closes_fence(line, fence):
                fence = None
            blank_run = 0
            continue
        marker = fence_marker(line)
        if marker:
            fence = marker
            out.append(line)
            blank_run = 0
            continue
        if not line:
            blank_run += 1
            if blank_run > 1:
                rep["blank_lines_collapsed"] += 1
                continue
            out.append(line)
            continue
        blank_run = 0
        if _ANCHOR_LINE.match(line):
            rep["anchor_lines_removed"] += 1
            continue
        m = _EMPTY_HEADING.match(line)
        if m:
            title = "What's next" if seen_heading else "Before you begin"
            rep["empty_heading_restored_whatsnext" if seen_heading else "empty_heading_restored_prerequisites"] += 1
            line = f"{m.group(1)} {title}"
            seen_heading = True
        elif _HEADING_LINE.match(line):
            new = _HEADING_ATTR.sub("", line)
            if new != line:
                rep["heading_ids_removed"] += 1
                line = new
            seen_heading = True
        out.append(line)
    return "\n".join(out).strip("\n"), {k: v for k, v in rep.items() if v}


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace without discarding useful structure."""
    return normalize_with_report(text)[0]


def load_markdown_corpus(manifest_path: Path = MANIFEST_JSON,
                         pages_dir: Path = PAGES_DIR) -> tuple[list[DocumentPage], list[dict[str, Any]]]:
    """Load every document listed in the manifest as one DocumentPage (one source unit).

    Returns (pages, page_log). `page_log` has one row per page: sizes, hashes, normalization
    counters and warnings. Missing/empty/short pages raise CorpusError (no silent skipping).
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    pages: list[DocumentPage] = []
    log: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in manifest["documents"]:
        sid = doc["source_id"]
        if sid in seen:
            raise CorpusError(f"duplicate source_id in manifest: {sid}")
        seen.add(sid)
        path = Path(pages_dir) / f"{sid}.md"
        if not path.is_file():
            raise CorpusError(f"page file missing for {sid}: {path}")
        raw = path.read_text(encoding="utf-8")
        warnings: list[str] = []
        if not raw.strip():
            raise CorpusError(f"page is empty: {sid}")
        if len(raw) != doc["char_count"]:
            warnings.append(f"raw length {len(raw)} != manifest char_count {doc['char_count']}")
        text, rep = normalize_with_report(raw)
        if len(text) < MIN_UNIT_CHARS:
            raise CorpusError(f"{sid}: only {len(text)} normalized chars (< {MIN_UNIT_CHARS})")
        meta = {
            "title": doc["title"], "section": doc["section"], "subsection": doc["subsection"],
            "source_url": doc["source_url"], "source_repo_path": doc["source_repo_path"],
            "source_version": doc["git_blob_sha1"], "license": doc["license"],
            "accessed_at": doc["accessed_at"],
        }
        pages.append(DocumentPage(document_id=sid, source=doc["source_url"], page=1, text=text, metadata=meta))
        log.append({
            "document_id": sid, "status": "ok" if not warnings else "warning",
            "raw_chars": len(raw), "normalized_chars": len(text),
            "raw_sha256": sha256(raw), "normalized_sha256": sha256(text),
            "normalization": rep, "warnings": warnings,
        })
    validate_corpus(pages)
    return pages, log


def validate_corpus(pages: list[DocumentPage]) -> dict[str, Any]:
    """Check the corpus against the lab minimums and return a summary."""
    if len(pages) < MIN_UNITS:
        raise CorpusError(f"corpus has {len(pages)} units, need >= {MIN_UNITS}")
    short = [p.document_id for p in pages if len(p.text) < MIN_UNIT_CHARS]
    if short:
        raise CorpusError(f"units below {MIN_UNIT_CHARS} chars: {short}")
    hashes = Counter(sha256(p.text) for p in pages)
    dup = [h for h, c in hashes.items() if c > 1]
    if dup:
        raise CorpusError("duplicate page texts found (units must not be duplicated)")
    by_section: Counter[str] = Counter(p.metadata["section"] for p in pages)
    return {"units": len(pages), "total_chars": sum(len(p.text) for p in pages),
            "by_section": dict(by_section), "min_unit_chars": min(len(p.text) for p in pages)}
