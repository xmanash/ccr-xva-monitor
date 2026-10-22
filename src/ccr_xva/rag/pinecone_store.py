"""Pinecone document index. Pinecone embeds the methodology text; this process never builds those vectors."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

FIELD = "chunk_text"


@dataclass(frozen=True)
class PineconeSettings:
    api_key: str
    index: str = "ccr-methodology"
    cloud: str = "aws"
    region: str = "us-east-1"
    model: str = "llama-text-embed-v2"
    namespace: str = "methodology"


class PineconeCorpus:
    def __init__(self, settings: PineconeSettings, index=None):
        self.settings = settings
        self._index = index

    def connect(self):
        if self._index is not None:
            return self._index
        from pinecone import Pinecone

        client = Pinecone(api_key=self.settings.api_key)
        if self.settings.index not in _index_names(client):
            client.indexes.create(
                name=self.settings.index,
                schema={
                    "fields": {
                        FIELD: {
                            "type": "string",
                            "embed": {"model": self.settings.model},
                        }
                    }
                },
                deployment={
                    "deployment_type": "managed",
                    "cloud": self.settings.cloud,
                    "region": self.settings.region,
                },
            )
        self._index = client.index(name=self.settings.index)
        return self._index

    def sync(self, chunks: list[dict]) -> int:
        """Upsert chunks Pinecone has not embedded yet. Returns how many were sent."""
        if not chunks:
            return 0
        index = self.connect()
        known = _known_ids(index, self.settings.namespace)
        missing = [chunk for chunk in chunks if chunk["id"] not in known]
        if not missing:
            return 0
        documents = [_document(chunk) for chunk in missing]
        result = index.documents.batch_upsert(
            namespace=self.settings.namespace,
            documents=documents,
            batch_size=90,
            show_progress=False,
        )
        failed = int(getattr(result, "failed_item_count", 0) or 0)
        if failed:
            raise RuntimeError(f"Pinecone rejected {failed} methodology chunks")
        return len(documents)

    def scores(self, query: str, k: int) -> dict[str, float]:
        index = self.connect()
        response = index.documents.search(
            namespace=self.settings.namespace,
            top_k=k,
            score_by=[{"type": "embed", "fields": [FIELD], "query": query}],
        )
        return {match.id: float(match.score) for match in response.matches}


def _document(chunk: dict) -> dict:
    title = chunk.get("title", "")
    return {
        "_id": chunk["id"],
        FIELD: f"{title}\n{chunk['text']}".strip(),
        "source": chunk["source"],
        "title": title,
    }


def _known_ids(index, namespace: str) -> set[str]:
    try:
        listed = index.documents.list(namespace=namespace)
    except Exception as exc:
        if _missing_namespace(exc):
            return set()
        raise
    return {item.id for item in listed}


def _missing_namespace(exc: Exception) -> bool:
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    return status == 404 or "not found" in str(exc).lower()


def _index_names(client) -> set[str]:
    listed = client.indexes.list()
    items = getattr(listed, "indexes", None)
    if items is None and isinstance(listed, dict):
        items = listed.get("indexes", [])
    if items is None:
        items = listed
    names: set[str] = set()
    for item in items:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict):
            name = item.get("name")
            if name:
                names.add(name)
        else:
            name = getattr(item, "name", None)
            if name:
                names.add(name)
    return names
