"""Store and search vectors with PostgreSQL + pgvector.

* One table `chunks`; rows are keyed by (strategy, chunk_id), so A/B/C/A2 are separate indexes
  over the same schema. `chunk_id` is stable (document + offsets + text hash).
* Search is EXACT cosine search (no HNSW/IVFFlat index), so a metadata filter never reduces the
  number of results the way it can with approximate indexes.
* Re-ingesting is idempotent: rows are upserted by key and chunks of re-ingested documents that no
  longer exist (changed text -> new ids) are deleted.
"""
from __future__ import annotations

from typing import Any

import psycopg

from .models import Chunk

FILTERABLE = {"section": "section", "subsection": "subsection", "document_id": "document_id"}
_BATCH = 200


def _vec(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in values) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        """Retain connection settings and fail immediately if the database is unreachable."""
        if not database_url:
            raise ValueError("DATABASE_URL is empty: copy starter/.env.example to starter/.env")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError(f"invalid embedding dimensions: {dimensions!r}")
        self.database_url = database_url
        self.dimensions = dimensions
        with self._connect() as conn:
            conn.execute("SELECT 1")

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=10)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    strategy       text    NOT NULL,
                    chunk_id       text    NOT NULL,
                    document_id    text    NOT NULL,
                    source         text    NOT NULL,
                    page           integer NOT NULL,
                    page_end       integer NOT NULL,
                    section        text    NOT NULL,
                    subsection     text    NOT NULL,
                    title          text    NOT NULL,
                    heading_path   text    NOT NULL,
                    char_start     integer NOT NULL,
                    char_end       integer NOT NULL,
                    chunk_index    integer NOT NULL,
                    n_chars        integer NOT NULL,
                    source_version text    NOT NULL,
                    text           text    NOT NULL,
                    embedding      vector({int(self.dimensions)}) NOT NULL,
                    ingested_at    timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_scope_idx ON chunks (strategy, section, subsection)")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks (strategy, document_id)")
            row = conn.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass "
                               "AND attname = 'embedding'").fetchone()
            if row and row[0] != self.dimensions:
                raise RuntimeError(f"table chunks has vector({row[0]}) but the model produces {self.dimensions} dims; "
                                   "use a fresh database/volume or the same model")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> dict[str, int]:
        """Write chunks without duplicates; delete obsolete chunks of the same documents.

        Returns counts: inserted / updated (existing id re-written) / deleted (obsolete) / total_after.
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk_id in one upsert")
        for v in vectors:
            if len(v) != self.dimensions:
                raise ValueError(f"vector has {len(v)} dims, expected {self.dimensions}")
        doc_ids = sorted({c.document_id for c in chunks})
        rows = []
        for c, v in zip(chunks, vectors):
            m = c.metadata
            rows.append((strategy, c.chunk_id, c.document_id, c.source, c.page, m["page_end"], m["section"],
                         m["subsection"], m["title"], m["heading_path"], m["char_start"], m["char_end"],
                         m["chunk_index"], m["n_chars"], m["source_version"], c.text, _vec(v)))
        sql = """INSERT INTO chunks (strategy, chunk_id, document_id, source, page, page_end, section, subsection,
                     title, heading_path, char_start, char_end, chunk_index, n_chars, source_version, text, embedding)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                 ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                     source = EXCLUDED.source, page = EXCLUDED.page, page_end = EXCLUDED.page_end,
                     section = EXCLUDED.section, subsection = EXCLUDED.subsection, title = EXCLUDED.title,
                     heading_path = EXCLUDED.heading_path, char_start = EXCLUDED.char_start,
                     char_end = EXCLUDED.char_end, chunk_index = EXCLUDED.chunk_index, n_chars = EXCLUDED.n_chars,
                     source_version = EXCLUDED.source_version, text = EXCLUDED.text,
                     embedding = EXCLUDED.embedding, ingested_at = now()"""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT chunk_id FROM chunks WHERE strategy = %s AND document_id = ANY(%s)", (strategy, doc_ids))
                existing = {r[0] for r in cur.fetchall()}
                cur.execute("DELETE FROM chunks WHERE strategy = %s AND document_id = ANY(%s) AND NOT (chunk_id = ANY(%s))",
                            (strategy, doc_ids, ids))
                deleted = cur.rowcount
                for i in range(0, len(rows), _BATCH):
                    cur.executemany(sql, rows[i:i + _BATCH])
                cur.execute("SELECT count(*) FROM chunks WHERE strategy = %s", (strategy,))
                total = cur.fetchone()[0]
        new = set(ids)
        return {"inserted": len(new - existing), "updated": len(new & existing), "deleted": deleted, "total_after": total}

    def delete_missing_documents(self, strategy: str, keep_document_ids: list[str]) -> int:
        """Remove chunks of documents that are no longer part of the corpus."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM chunks WHERE strategy = %s AND NOT (document_id = ANY(%s))",
                               (strategy, list(keep_document_ids)))
            return cur.rowcount

    def delete_strategy(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute("DELETE FROM chunks WHERE strategy = %s", (strategy,)).rowcount

    def count(self, strategy: str | None = None) -> int:
        with self._connect() as conn:
            if strategy is None:
                return conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
            return conn.execute("SELECT count(*) FROM chunks WHERE strategy = %s", (strategy,)).fetchone()[0]

    def counts_by_strategy(self) -> dict[str, int]:
        with self._connect() as conn:
            return {r[0]: r[1] for r in conn.execute("SELECT strategy, count(*) FROM chunks GROUP BY strategy ORDER BY 1")}

    def fetch_chunks(self, strategy: str) -> list[dict[str, Any]]:
        """All stored chunks of a strategy (without vectors); used by audits."""
        cols = ("chunk_id document_id source page page_end section subsection title heading_path "
                "char_start char_end chunk_index n_chars source_version text").split()
        with self._connect() as conn:
            rows = conn.execute(f"SELECT {', '.join(cols)} FROM chunks WHERE strategy = %s "
                                "ORDER BY document_id, chunk_index", (strategy,)).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Exact cosine top-k within one strategy, optionally restricted by metadata filters.

        Filter columns come from a whitelist and all values are bound parameters.
        """
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector has {len(query_vector)} dims, expected {self.dimensions}")
        where = ["strategy = %s"]
        params: list[Any] = [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTERABLE:
                raise ValueError(f"filter field not allowed: {key}")
            if isinstance(value, (list, tuple, set)):
                where.append(f"{FILTERABLE[key]} = ANY(%s)")
                params.append(list(value))
            else:
                where.append(f"{FILTERABLE[key]} = %s")
                params.append(value)
        qv = _vec(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, page_end, section, subsection, title, heading_path, "
               f"char_start, char_end, chunk_index, n_chars, source_version, text, embedding <=> %s::vector AS distance "
               f"FROM chunks WHERE {' AND '.join(where)} ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [qv, *params, qv, int(top_k)]).fetchall()
        out = []
        for rank, r in enumerate(rows, 1):
            (cid, doc, src, page, page_end, sec, sub, title, hp, cs, ce, ci, nc, ver, text, dist) = r
            out.append({
                "rank": rank, "chunk_id": cid, "document_id": doc, "source": src, "page": page, "text": text,
                "score": float(1.0 - dist), "distance": float(dist),
                "metadata": {"section": sec, "subsection": sub, "title": title, "heading_path": hp,
                             "char_start": cs, "char_end": ce, "chunk_index": ci, "n_chars": nc,
                             "page_end": page_end, "source_version": ver},
            })
        return out
