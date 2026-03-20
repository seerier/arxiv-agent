"""Semantic embedding support for the Arxiv Intelligence System.

Uses sentence-transformers (all-MiniLM-L6-v2) to embed paper text and queries
so that search is meaning-based rather than keyword-based.

The model (~90 MB) is downloaded automatically on first use and cached by
sentence-transformers in ~/.cache/huggingface/.
"""

from __future__ import annotations

import logging
import struct
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None


def is_available() -> bool:
    """Return True if sentence-transformers is installed."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def get_model():
    """Lazily load and cache the embedding model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model '%s'…", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
        logger.info("Embedding model loaded.")
    return _model


def embed(text: str) -> np.ndarray:
    """Return a normalised float32 embedding vector for *text*."""
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
    return vec.astype(np.float32)


def embed_batch(texts: List[str], batch_size: int = 64) -> List[np.ndarray]:
    """Embed a list of texts efficiently in batches."""
    model = get_model()
    vecs = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
        show_progress_bar=False,
    )
    return [v.astype(np.float32) for v in vecs]


def vec_to_blob(vec: np.ndarray) -> bytes:
    """Serialise a float32 numpy array to raw bytes for SQLite BLOB storage."""
    return vec.astype(np.float32).tobytes()


def blob_to_vec(blob: bytes) -> np.ndarray:
    """Deserialise a BLOB back to a float32 numpy array."""
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two already-normalised vectors."""
    return float(np.dot(a, b))


def paper_text(title: str, abstract: str) -> str:
    """Combine title and abstract into the text that gets embedded."""
    return f"{title}. {abstract}" if abstract else title


def rank_by_similarity(
    query_vec: np.ndarray,
    candidates: List[Tuple[str, bytes]],  # [(paper_id, embedding_blob), ...]
    top_k: int,
) -> List[Tuple[str, float]]:
    """Return top-k (paper_id, score) pairs sorted by cosine similarity."""
    results: List[Tuple[str, float]] = []
    for paper_id, blob in candidates:
        if blob:
            paper_vec = blob_to_vec(blob)
            score = cosine_similarity(query_vec, paper_vec)
            results.append((paper_id, score))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]
