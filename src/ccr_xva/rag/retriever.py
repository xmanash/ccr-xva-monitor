"""Hybrid retriever: BM25 plus a dense score.

The dense score is a Pinecone embedding when that index is configured, and a local hashed cosine otherwise. Chroma mirrors the hashed vectors only on the local path.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from pathlib import Path

import numpy as np

from ccr_xva.rag.ingest import load_markdown_chunks
from ccr_xva.rag.pinecone_store import PineconeCorpus

logger = logging.getLogger(__name__)
TOKEN = re.compile(r"[a-z0-9]+")
DIM = 256


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def hash_embed(text: str, dim: int = DIM) -> np.ndarray:
    vector = np.zeros(dim, dtype=float)
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector /= norm
    return vector


class HybridRetriever:
    def __init__(self, chunks: list[dict], chroma_path: str | None = None, pinecone: PineconeCorpus | None = None):
        self.chunks = chunks
        self._matrix = (
            np.vstack([hash_embed(f"{chunk.get('title', '')}\n{chunk['text']}") for chunk in chunks])
            if chunks
            else np.zeros((0, DIM))
        )
        self._bm25 = None
        self._title_bm25 = None
        if chunks:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi([tokenize(f"{chunk.get('title', '')}\n{chunk['text']}") or ["note"] for chunk in chunks])
            self._title_bm25 = BM25Okapi([tokenize(chunk.get("title", "")) or ["note"] for chunk in chunks])
        self._pinecone = None
        if pinecone is not None and chunks:
            try:
                pinecone.sync(chunks)
                self._pinecone = pinecone
            except Exception:
                logger.warning("Pinecone embedding index skipped", exc_info=True)
        self._collection = None
        if chroma_path and chunks and self._pinecone is None:
            self._mirror_chroma(chroma_path)

    def _mirror_chroma(self, chroma_path: str) -> None:
        try:
            import chromadb
        except ImportError:
            logger.warning("chromadb is not installed; retrieval uses BM25 and hashed cosine only")
            return
        try:
            Path(chroma_path).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=chroma_path)
            collection = client.get_or_create_collection(name="ccr_methodology_v2", embedding_function=_ChromaHash())
            ids = [chunk["id"] for chunk in self.chunks]
            existing = set(collection.get(ids=ids).get("ids", []))
            new_chunks = [chunk for chunk in self.chunks if chunk["id"] not in existing]
            if new_chunks:
                collection.add(
                    ids=[chunk["id"] for chunk in new_chunks],
                    documents=[f"{chunk.get('title', '')}\n{chunk['text']}" for chunk in new_chunks],
                    metadatas=[{"source": chunk["source"], "title": chunk.get("title", "")} for chunk in new_chunks],
                )
            self._collection = collection
        except Exception:
            logger.warning("Chroma mirror skipped", exc_info=True)

    def search(self, query: str, k: int = 4) -> list[dict]:
        if not self.chunks:
            return []
        query_tokens = tokenize(query)
        bm25_scores = np.zeros(len(self.chunks))
        if self._bm25 is not None and query_tokens:
            bm25_scores = np.asarray(self._bm25.get_scores(query_tokens), dtype=float)
        title_scores = np.zeros(len(self.chunks))
        if self._title_bm25 is not None and query_tokens:
            title_scores = np.asarray(self._title_bm25.get_scores(query_tokens), dtype=float)
        if self._pinecone is not None:
            try:
                found = self._pinecone.scores(query, min(max(k * 4, 8), len(self.chunks)))
                dense = np.array([found.get(chunk["id"], 0.0) for chunk in self.chunks], dtype=float)
                combined = (0.45 * _unit(bm25_scores)) + (0.15 * _unit(title_scores)) + (0.40 * _unit(dense))
            except Exception:
                logger.warning("Pinecone query failed; using the local hash score", exc_info=True)
                combined = self._local_score(bm25_scores, title_scores, query)
        else:
            combined = self._local_score(bm25_scores, title_scores, query)
        if self._pinecone is None and self._collection is not None:
            try:
                found = self._collection.query(query_texts=[query], n_results=min(k, len(self.chunks)))
                ids = found.get("ids", [[]])[0]
                boost = {chunk_id: (len(ids) - rank) / max(len(ids), 1) for rank, chunk_id in enumerate(ids)}
                for index, chunk in enumerate(self.chunks):
                    combined[index] += boost.get(chunk["id"], 0.0)
            except Exception:
                logger.warning("Chroma query failed", exc_info=True)
        order = np.argsort(-combined)[:k]
        results = []
        for index in order:
            if combined[index] <= 0:
                continue
            chunk = self.chunks[int(index)]
            results.append({**chunk, "score": float(combined[index])})
        return results

    def _local_score(self, bm25_scores: np.ndarray, title_scores: np.ndarray, query: str) -> np.ndarray:
        query_vector = hash_embed(query)
        cosine = self._matrix @ query_vector if len(self._matrix) else np.zeros(len(self.chunks))
        return (0.6 * _unit(bm25_scores)) + (0.25 * _unit(title_scores)) + (0.15 * _unit(cosine))


def _unit(scores: np.ndarray) -> np.ndarray:
    peak = float(np.max(scores)) if len(scores) else 0.0
    if peak <= 0 or math.isnan(peak):
        return np.zeros_like(scores)
    return scores / peak


class _ChromaHash:
    """Chroma embedding function backed by the same hashed vectors as local search."""

    def __init__(self) -> None:
        return

    def __call__(self, input):
        return [hash_embed(text).tolist() for text in input]

    @staticmethod
    def name() -> str:
        return "ccr-hash-v1"

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine"]

    def get_config(self) -> dict:
        return {}

    def is_legacy(self) -> bool:
        return False

    @staticmethod
    def build_from_config(config):
        _ = config
        return _ChromaHash()


def build_retriever(
    chunks: list[dict] | None = None,
    chroma_path: str | None = None,
    pinecone: PineconeCorpus | None = None,
) -> HybridRetriever:
    loaded = chunks if chunks is not None else load_markdown_chunks()
    return HybridRetriever(loaded, chroma_path=chroma_path, pinecone=pinecone)
