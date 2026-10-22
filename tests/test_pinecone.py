from __future__ import annotations

from ccr_xva.rag.ingest import load_markdown_chunks
from ccr_xva.rag.pinecone_store import FIELD, PineconeCorpus, PineconeSettings
from ccr_xva.rag.retriever import build_retriever


class _Listed:
    def __init__(self, doc_id: str):
        self.id = doc_id


class _Match:
    def __init__(self, doc_id: str, score: float):
        self.id = doc_id
        self.score = score


class _Search:
    def __init__(self, matches: list[_Match]):
        self.matches = matches


class _UpsertResult:
    failed_item_count = 0


class _Documents:
    def __init__(self):
        self.ids: set[str] = set()
        self.documents: list[dict] = []
        self.queries: list[str] = []

    def list(self, *, namespace: str):
        assert namespace == "methodology"
        return [_Listed(doc_id) for doc_id in self.ids]

    def batch_upsert(self, *, namespace: str, documents: list[dict], batch_size: int, show_progress: bool):
        assert namespace == "methodology"
        assert batch_size <= 96
        self.documents.extend(documents)
        self.ids.update(document["_id"] for document in documents)
        return _UpsertResult()

    def search(self, *, namespace: str, top_k: int, score_by: list[dict]):
        assert namespace == "methodology"
        assert score_by[0]["type"] == "embed"
        assert score_by[0]["fields"] == [FIELD]
        self.queries.append(score_by[0]["query"])
        ranked = []
        for document in self.documents:
            text = document[FIELD].lower()
            if "unilateral cva" in text:
                ranked.append(_Match(document["_id"], 0.91))
        return _Search(ranked[:top_k])


class _Index:
    def __init__(self):
        self.documents = _Documents()


def test_pinecone_embeds_missing_chunks_and_ranks_them():
    index = _Index()
    corpus = PineconeCorpus(PineconeSettings(api_key="test-key"), index=index)
    retriever = build_retriever(chroma_path=None, pinecone=corpus)
    hits = retriever.search("What is the unilateral CVA formula?", k=1)
    assert hits[0]["title"] == "Unilateral CVA"
    assert index.documents.documents
    assert all(FIELD in document and document["title"] for document in index.documents.documents)
    sent = len(index.documents.documents)
    corpus.sync(load_markdown_chunks())
    assert len(index.documents.documents) == sent


def test_pinecone_failure_keeps_local_retrieval():
    class _Broken:
        def sync(self, chunks):
            raise RuntimeError("pinecone down")

    hits = build_retriever(chroma_path=None, pinecone=_Broken()).search("What is the unilateral CVA formula?", k=1)
    assert hits[0]["title"] == "Unilateral CVA"
