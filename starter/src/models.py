"""Shared data contracts; keep traceability from chunk back to source."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DocumentPage:
    """One *source unit*. In this corpus a unit is one whole Markdown concept page
    (data/manifest.json counts 43 of them), so `page` is always 1 and `text` is the
    normalized body of the page. Finer positions are carried by Chunk (heading + offsets)."""
    document_id: str
    source: str
    page: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """`text` is always an exact slice of the normalized page text:
    `page.text[metadata['char_start']:metadata['char_end']] == text`.

    `page` is the traceability unit inside the document: the 1-based ordinal of the H2 block
    that contains the first character of the chunk (1 = intro text before the first H2).
    """
    chunk_id: str
    document_id: str
    source: str
    page: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
