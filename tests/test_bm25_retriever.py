import os
import sys
from pathlib import Path

from langchain_core.documents import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rag.bm25_retriever import BM25KeywordRetriever


def _docs() -> list[Document]:
    return [
        Document(
            page_content="Young's modulus measures material stiffness in elasticity.",
            metadata={"source_type": "youtube", "source": "lecture-1"},
        ),
        Document(
            page_content="Bulk modulus and shear modulus are other elastic constants.",
            metadata={"source_type": "pdf", "source": "chapter-2"},
        ),
        Document(
            page_content="The Young double slit experiment demonstrates interference.",
            metadata={"source_type": "youtube", "source": "lecture-2"},
        ),
    ]


def test_search_returns_relevant_docs():
    retriever = BM25KeywordRetriever(_docs())

    results = retriever.search("young modulus", k=3)

    assert len(results) > 0
    assert any("young" in doc.page_content.lower() for doc, _ in results)


def test_search_scores_descending():
    retriever = BM25KeywordRetriever(_docs())

    results = retriever.search("young modulus", k=3)
    scores = [score for _, score in results]

    assert scores == sorted(scores, reverse=True)


def test_search_with_filter():
    retriever = BM25KeywordRetriever(_docs())

    results = retriever.search("young", k=5, source_type="youtube")

    assert len(results) > 0
    assert all(doc.metadata.get("source_type") == "youtube" for doc, _ in results)


def test_empty_query_returns_empty():
    retriever = BM25KeywordRetriever(_docs())

    assert retriever.search("", k=3) == []
    assert retriever.search("   ", k=3) == []


def test_no_match_returns_empty():
    retriever = BM25KeywordRetriever(_docs())

    results = retriever.search("xylophonic quasar neutrinozzz", k=3)

    assert results == []


def test_build_from_empty_list():
    retriever = BM25KeywordRetriever([])

    assert retriever.search("young", k=5) == []
