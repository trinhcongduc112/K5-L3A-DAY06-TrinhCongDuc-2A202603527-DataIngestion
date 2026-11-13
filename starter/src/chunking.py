"""Fixed-size and structure-aware chunking.

Invariant shared by every chunker: `chunk.text == page.text[char_start:char_end]` (a verbatim
slice of the normalized page), so each chunk can be traced back to exact offsets, a heading
path and an H2 "page" ordinal, and so audits can recompute them from the source.
"""
from __future__ import annotations

import bisect
import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .ingestion import closes_fence, fence_marker
from .models import Chunk, DocumentPage

_HEADING = re.compile(r"^(#{2,6})[ \t]+(\S.*?)\s*$")


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    kind: str          # "heading" | "text" | "code"
    level: int = 0     # heading level (2..6), 0 otherwise
    title: str = ""    # heading title


def parse_blocks(text: str, warnings: list[str] | None = None) -> list[Block]:
    """Split text into heading / paragraph(text) / fenced-code blocks with char offsets.

    Blank lines separate paragraphs; a fenced code block is one atomic block even when it
    contains blank lines (also when the fence is indented inside a list item). H1 lines are not
    treated as headings: the page title lives in the front matter, and `# ` lines are normally
    shell/YAML comments.
    """
    blocks: list[Block] = []
    cur_s: int | None = None
    cur_e = 0
    fence: str | None = None
    fence_s = 0
    last_end = 0
    pos = 0
    for line in text.split("\n"):
        s, e = pos, pos + len(line)
        pos = e + 1
        last_end = e
        if fence is not None:
            if closes_fence(line, fence):
                blocks.append(Block(fence_s, e, "code"))
                fence = None
            continue
        if not line.strip():
            if cur_s is not None:
                blocks.append(Block(cur_s, cur_e, "text"))
                cur_s = None
            continue
        marker = fence_marker(line)
        if marker:
            if cur_s is not None:
                blocks.append(Block(cur_s, cur_e, "text"))
                cur_s = None
            fence, fence_s = marker, s
            continue
        m = _HEADING.match(line)
        if m:
            if cur_s is not None:
                blocks.append(Block(cur_s, cur_e, "text"))
                cur_s = None
            blocks.append(Block(s, e, "heading", len(m.group(1)), re.sub(r"\s+", " ", m.group(2))))
            continue
        if cur_s is None:
            cur_s = s
        cur_e = e
    if cur_s is not None:
        blocks.append(Block(cur_s, cur_e, "text"))
    if fence is not None:
        blocks.append(Block(fence_s, last_end, "code"))
        if warnings is not None:
            warnings.append("unclosed_code_fence")
    return blocks


class SectionIndex:
    """Maps a character offset to (heading path, H2 page ordinal)."""

    def __init__(self, text: str) -> None:
        self.offsets: list[int] = []
        self.paths: list[tuple[str, ...]] = []
        self.pages: list[int] = []
        stack: list[tuple[int, str]] = []
        h2 = 0
        for b in parse_blocks(text):
            if b.kind != "heading":
                continue
            while stack and stack[-1][0] >= b.level:
                stack.pop()
            stack.append((b.level, b.title))
            if b.level == 2:
                h2 += 1
            self.offsets.append(b.start)
            self.paths.append(tuple(t for _, t in stack))
            self.pages.append(1 + h2)

    def lookup(self, offset: int) -> tuple[tuple[str, ...], int]:
        i = bisect.bisect_right(self.offsets, offset) - 1
        return ((), 1) if i < 0 else (self.paths[i], self.pages[i])


def _make_chunk(page: DocumentPage, idx: SectionIndex, start: int, end: int, index: int) -> Chunk:
    text = page.text[start:end]
    path, pg = idx.lookup(start)
    _, pg_end = idx.lookup(max(start, end - 1))
    h8 = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    meta: dict[str, Any] = {
        "title": page.metadata.get("title", ""),
        "section": page.metadata.get("section", ""),
        "subsection": page.metadata.get("subsection", ""),
        "heading_path": " > ".join(path),
        "char_start": start, "char_end": end, "n_chars": end - start,
        "page_end": pg_end, "chunk_index": index,
        "source_version": page.metadata.get("source_version", ""),
    }
    return Chunk(chunk_id=f"{page.document_id}@{start}-{end}-{h8}", document_id=page.document_id,
                 source=page.source, page=pg, text=text, metadata=meta)


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Overlapping windows of at most `size` chars; cuts are moved back to whitespace so that
    no word is split. Consecutive windows start `size - overlap` chars apart (approximately)."""
    if size <= overlap or overlap < 0:
        raise ValueError("need 0 <= overlap < size")
    text = page.text
    n = len(text)
    idx = SectionIndex(text)
    spans: list[tuple[int, int]] = []
    start = 0
    while start < n:
        end = min(start + size, n)
        if end < n and not text[end].isspace() and not text[end - 1].isspace():
            cut = max((m.start() for m in re.finditer(r"\s", text[start + size // 2:end])), default=None)
            if cut is not None:
                end = start + size // 2 + cut
        s, e = _trim(text, start, end)
        if e > s:
            spans.append((s, e))
        if end >= n:
            break
        nxt = max(end - overlap, start + 1)
        while nxt < end and not text[nxt - 1].isspace():     # start the next window at a word start
            nxt += 1
        start = nxt
    return [_make_chunk(page, idx, s, e, i) for i, (s, e) in enumerate(spans)]


def _last_boundary(text: str, lo: int, hi: int) -> int | None:
    """Best place to cut inside text[lo:hi]: last newline, else last sentence end, else last space."""
    i = text.rfind("\n", lo, hi)
    if i != -1:
        return i
    last = None
    for m in re.finditer(r"[.!?][\"')\]`]*\s", text[lo:hi]):
        last = m
    if last:
        return lo + last.end() - 1
    last = None
    for m in re.finditer(r"\s", text[lo:hi]):
        last = m
    return lo + last.start() if last else None


def _split_span(text: str, s: int, e: int, max_size: int) -> list[tuple[int, int]]:
    """Split text[s:e] into pieces of at most max_size chars (newline > sentence > space)."""
    out: list[tuple[int, int]] = []
    pos = s
    while e - pos > max_size:
        remaining = e - pos
        if remaining <= int(max_size * 1.25):
            # just over the cap: split near the middle instead of leaving a tiny tail
            cut = _last_boundary(text, pos + int(remaining * 0.4), pos + int(remaining * 0.6) + 1)
            fallback = pos + remaining // 2
        else:
            cut = _last_boundary(text, pos + max_size // 3, pos + max_size + 1)
            fallback = pos + max_size
        if cut is None or cut <= pos:
            cut = fallback
        a, b = _trim(text, pos, cut)
        if b > a:
            out.append((a, b))
        pos = cut + 1 if text[cut:cut + 1].isspace() else cut
    a, b = _trim(text, pos, e)
    if b > a:
        out.append((a, b))
    return out


def by_paragraph(page: DocumentPage, max_size: int = 1000, min_size: int = 300) -> list[Chunk]:
    """Heading/paragraph-aware chunking.

    * Blocks (headings, paragraphs/lists/tables, fenced code) are never cut unless one block alone
      exceeds `max_size`; then it is split at newline > sentence end > whitespace.
    * A new chunk always starts at an H2; at an H3+ heading it starts only when the current chunk
      already holds >= `min_size` chars. Otherwise blocks are packed greedily up to `max_size`.
    * A heading is never left alone at the end of a chunk (it stays with the text that follows it),
      so a chunk may exceed `max_size` by at most that heading line.
    """
    text = page.text
    idx = SectionIndex(text)
    pieces: list[tuple[int, int, str, int]] = []      # (start, end, kind, heading level)
    for b in parse_blocks(text):
        if b.end - b.start <= max_size:
            pieces.append((b.start, b.end, b.kind, b.level))
        else:
            pieces.extend((a, z, b.kind, 0) for a, z in _split_span(text, b.start, b.end, max_size))
    spans: list[tuple[int, int]] = []
    cur_s = cur_e = -1
    last_is_heading = False
    for s, e, kind, level in pieces:
        if cur_s < 0:
            cur_s, cur_e, last_is_heading = s, e, kind == "heading"
            continue
        too_big = e - cur_s > max_size
        hard = kind == "heading" and level == 2
        soft = kind == "heading" and level >= 3 and (cur_e - cur_s) >= min_size
        if (too_big or hard or soft) and not last_is_heading:
            spans.append((cur_s, cur_e))
            cur_s, cur_e = s, e
        else:
            cur_e = e
        last_is_heading = kind == "heading"
    if cur_s >= 0:
        spans.append((cur_s, cur_e))
    return [_make_chunk(page, idx, s, e, i) for i, (s, e) in enumerate(spans)]


def make_chunks(page: DocumentPage, cfg: dict[str, Any]) -> list[Chunk]:
    """Chunk one page with a strategy config from src/config.py."""
    if cfg["chunker"] == "fixed_size":
        return fixed_size(page, cfg["size"], cfg["overlap"])
    if cfg["chunker"] == "by_paragraph":
        return by_paragraph(page, cfg["max_size"], cfg["min_size"])
    raise ValueError(f"unknown chunker: {cfg['chunker']}")
