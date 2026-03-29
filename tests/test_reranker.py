import os
import sys
from unittest.mock import patch

from langchain_core.documents import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rag.reranker import Reranker


def _candidates() -> list[Document]:
    return [
        Document(page_content="doc-1", metadata={"id": "d1", "source_type": "youtube"}),
        Document(page_content="doc-2", metadata={"id": "d2", "source_type": "pdf"}),
        Document(page_content="doc-3", metadata={"id": "d3", "source_type": "notes"}),
        Document(page_content="doc-4", metadata={"id": "d4", "source_type": "html"}),
    ]


def test_rerank_returns_top_k():
    candidates = _candidates()

    with patch("src.rag.reranker.CrossEncoder") as mock_cross_encoder:
        model = mock_cross_encoder.return_value
        model.predict.return_value = [0.9, 0.1, 0.7, 0.05]

        reranker = Reranker()
        top_docs = reranker.rerank("young modulus", candidates, top_k=2)

    assert [doc.page_content for doc in top_docs] == ["doc-1", "doc-3"]


def test_rerank_empty_candidates():
    with patch("src.rag.reranker.CrossEncoder") as mock_cross_encoder:
        reranker = Reranker()

        result = reranker.rerank("any query", [], top_k=3)

    assert result == []
    mock_cross_encoder.assert_not_called()


def test_rerank_preserves_metadata():
    candidates = _candidates()

    with patch("src.rag.reranker.CrossEncoder") as mock_cross_encoder:
        model = mock_cross_encoder.return_value
        model.predict.return_value = [0.1, 0.9, 0.2, 0.3]

        reranker = Reranker()
        top_docs = reranker.rerank("ohm law", candidates, top_k=1)

    assert len(top_docs) == 1
    assert top_docs[0].metadata == {"id": "d2", "source_type": "pdf"}
