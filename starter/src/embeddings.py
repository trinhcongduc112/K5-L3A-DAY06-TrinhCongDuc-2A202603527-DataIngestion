"""Real embedding provider: a local Sentence Transformers model (no API key, no cost).

Default: `intfloat/multilingual-e5-small` (384 dims, 512-token context, cosine). E5 models need
"query: " / "passage: " prefixes; they are applied here and recorded in the run metadata.
Failures raise: there is deliberately no mock/random-vector fallback.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


def _prefixes(model_name: str) -> tuple[str, str]:
    """(query_prefix, document_prefix) required by the model family."""
    if "e5" in model_name.lower():
        return "query: ", "passage: "
    return "", ""


def _cached_revision(model_name: str) -> str | None:
    """Commit hash of the Hugging Face snapshot that is actually loaded (from the local cache)."""
    try:
        from huggingface_hub import snapshot_download
        return Path(snapshot_download(model_name, local_files_only=True)).name
    except Exception:  # provenance only; never affects the vectors
        return None


class MyEmbedder:
    def __init__(self, model_name: str | None = None, device: str = "cpu", batch_size: int = 32) -> None:
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL", "").strip()
        if not self.model_name:
            raise RuntimeError("EMBEDDING_MODEL is empty: set it in starter/.env (e.g. intfloat/multilingual-e5-small)")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # fail loudly: do not fall back to a fake embedder
            raise RuntimeError("sentence-transformers is not installed: pip install -r requirements-embedding.txt") from exc
        self.device = device
        self.batch_size = batch_size
        self.model = SentenceTransformer(self.model_name, device=device)
        # sentence-transformers >= 6 renamed the method; fall back to the old name on older versions
        get_dim = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dimensions = int(get_dim())
        self.max_seq_length = int(self.model.max_seq_length)
        self.query_prefix, self.document_prefix = _prefixes(self.model_name)
        self.revision = _cached_revision(self.model_name)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                    convert_to_numpy=True, show_progress_bar=False)
        if vectors.shape != (len(texts), self.dimensions):
            raise RuntimeError(f"unexpected embedding shape {vectors.shape} for {len(texts)} texts")
        return vectors.astype("float32").tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode([self.document_prefix + t for t in texts])

    def embed_query(self, question: str) -> list[float]:
        return self._encode([self.query_prefix + question])[0]

    def count_tokens(self, texts: list[str]) -> list[int]:
        """Token count of each document text as the model sees it (prefix + special tokens included)."""
        if not texts:
            return []
        ids = self.model.tokenizer([self.document_prefix + t for t in texts], add_special_tokens=True,
                                   truncation=False)["input_ids"]
        return [len(x) for x in ids]

    def describe(self) -> dict:
        import sentence_transformers
        import torch
        import transformers
        return {
            "provider": "local (sentence-transformers)", "model": self.model_name, "revision": self.revision,
            "dimensions": self.dimensions, "max_seq_length": self.max_seq_length, "device": self.device,
            "normalize_embeddings": True, "metric": "cosine", "query_prefix": self.query_prefix,
            "document_prefix": self.document_prefix, "batch_size": self.batch_size,
            "versions": {"sentence-transformers": sentence_transformers.__version__,
                         "torch": torch.__version__, "transformers": transformers.__version__},
            "cost_usd": 0.0,
        }
