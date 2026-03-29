from typing import Any

from langchain_core.documents import Document

from src.rag import neet_rag
from src.rag.neet_rag import NEETRAG


def _doc(content: str, source: str) -> Document:
    return Document(
        page_content=content, metadata={"source": source, "source_type": "csv"}
    )


def test_rrf_merges_two_lists():
    rrf = getattr(neet_rag, "_reciprocal_rank_fusion", None)
    assert rrf is not None

    doc_a = _doc("alpha", "a")
    doc_b = _doc("beta", "b")
    doc_c = _doc("gamma", "c")

    merged = rrf(
        [
            [(doc_a, 0.9), (doc_b, 0.8)],
            [(doc_c, 1.5), (doc_b, 1.2)],
        ]
    )

    assert {doc.metadata["source"] for doc in merged} == {"a", "b", "c"}


def test_rrf_boosts_docs_in_both_lists():
    rrf = getattr(neet_rag, "_reciprocal_rank_fusion", None)
    assert rrf is not None

    doc_a = _doc("alpha", "a")
    doc_b = _doc("beta", "b")
    doc_c = _doc("gamma", "c")

    merged = rrf(
        [
            [(doc_a, 0.9), (doc_b, 0.8)],
            [(doc_b, 1.4), (doc_c, 1.1)],
        ]
    )

    assert merged[0].metadata["source"] == "b"


def test_no_docs_above_threshold_returns_empty():
    class _FakeVectorManager:
        def similarity_search_with_score(self, question, k, filter=None):
            return [
                (_doc("irrelevant one", "x"), 100.0),
                (_doc("irrelevant two", "y"), 80.0),
            ]

    rag: Any = NEETRAG.__new__(NEETRAG)
    rag.vector_manager = _FakeVectorManager()
    rag.similarity_threshold = 0.99

    docs = rag._retrieve_docs("mitosis", top_k=3)

    assert docs == []
