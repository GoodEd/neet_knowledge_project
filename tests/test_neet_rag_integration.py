# pyright: reportMissingImports=false

from pathlib import Path
import os
import sys
from unittest.mock import patch

import pytest
from langchain_core.documents import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rag.llm_manager import LLMManager
from src.rag.neet_rag import NEETRAG
from src.rag.vector_store import CompositeVectorStoreManager, VectorStoreManager


EMBEDDING_DIM = 16


@pytest.fixture(autouse=True)
def stub_llm_initialization(monkeypatch):
    def _fake_initialize_llm(self, api_key=None, base_url=None):
        self.llm = object()

    monkeypatch.setattr(LLMManager, "_initialize_llm", _fake_initialize_llm)


def _build_csv_doc(idx: int) -> Document:
    return Document(
        page_content=f"Biology QA pair {idx}: Cell is the basic unit of life.",
        metadata={
            "source": f"csv://neet_bio_{idx}.csv",
            "source_type": "csv",
            "content_type": "csv_qa_pair",
            "chapter_name": "Biology",
            "question_id": str(idx),
        },
    )


def _build_youtube_doc(idx: int, video_id: str = "abc123def45") -> Document:
    return Document(
        page_content=f"YouTube transcript chunk {idx}: photosynthesis explained.",
        metadata={
            "source": f"https://www.youtube.com/watch?v={video_id}",
            "source_type": "youtube",
            "content_type": "youtube",
            "video_id": video_id,
            "start_time": float(idx * 60),
        },
    )


def _create_index(index_dir: Path, docs: list[Document]) -> None:
    manager = VectorStoreManager(
        persist_directory=str(index_dir),
        embedding_provider="fake",
        embedding_dimension=EMBEDDING_DIM,
    )
    manager.create_vectorstore(docs)


def _create_split_indexes(
    tmp_path: Path, csv_count: int = 3, youtube_count: int = 2
) -> tuple[Path, Path]:
    youtube_dir = tmp_path / "youtube"
    csv_dir = tmp_path / "csv"

    _create_index(
        youtube_dir, [_build_youtube_doc(i) for i in range(1, youtube_count + 1)]
    )
    _create_index(csv_dir, [_build_csv_doc(i) for i in range(1, csv_count + 1)])

    return youtube_dir, csv_dir


def _create_single_index(
    tmp_path: Path, csv_count: int = 2, youtube_count: int = 1
) -> None:
    docs = [_build_csv_doc(i) for i in range(1, csv_count + 1)] + [
        _build_youtube_doc(i) for i in range(1, youtube_count + 1)
    ]
    _create_index(tmp_path, docs)


def _build_rag(tmp_path: Path) -> NEETRAG:
    rag = NEETRAG(
        persist_directory=str(tmp_path),
        embedding_provider="fake",
        embedding_dimension=EMBEDDING_DIM,
        llm_provider="openai",
        llm_model="mock-model",
    )
    rag.similarity_threshold = 0.0
    return rag


def test_neetrag_initializes_without_error_with_fake_embeddings(tmp_path):
    _create_single_index(tmp_path)

    rag = _build_rag(tmp_path)

    assert rag is not None
    assert isinstance(rag.vector_manager, VectorStoreManager)


def test_neetrag_detects_split_indexes_when_youtube_and_csv_subdirs_exist(tmp_path):
    _create_split_indexes(tmp_path)

    rag = _build_rag(tmp_path)

    assert isinstance(rag.vector_manager, CompositeVectorStoreManager)


def test_neetrag_falls_back_to_single_index_without_split_subdirs(tmp_path):
    _create_single_index(tmp_path)

    rag = _build_rag(tmp_path)

    assert isinstance(rag.vector_manager, VectorStoreManager)
    assert not isinstance(rag.vector_manager, CompositeVectorStoreManager)


def test_is_youtube_doc_identifies_youtube_documents(tmp_path):
    _create_single_index(tmp_path)
    doc = _build_youtube_doc(1)

    assert NEETRAG._is_youtube_doc(doc) is True


def test_is_youtube_doc_identifies_non_youtube_documents(tmp_path):
    _create_single_index(tmp_path)
    doc = _build_csv_doc(1)

    assert NEETRAG._is_youtube_doc(doc) is False


def test_query_returns_answer_sources_and_question_sources_keys(tmp_path):
    _create_split_indexes(tmp_path, csv_count=4, youtube_count=3)
    rag = _build_rag(tmp_path)

    with patch.object(LLMManager, "generate", return_value="Mocked LLM answer"):
        result = rag.query("What is the basic unit of life?", top_k=5)

    assert result["answer"] == "Mocked LLM answer"
    assert "sources" in result
    assert "question_sources" in result
    assert isinstance(result["sources"], list)
    assert isinstance(result["question_sources"], list)


def test_format_youtube_url_generates_timestamped_url():
    url = NEETRAG._format_youtube_url(
        "https://www.youtube.com/watch?v=abc123", "abc123", 120.0
    )

    assert url == "https://www.youtube.com/watch?v=abc123&t=120s"


def test_format_youtube_url_generates_url_without_timestamp():
    url = NEETRAG._format_youtube_url(
        "https://www.youtube.com/watch?v=abc123", "abc123", 0.0
    )

    assert url == "https://www.youtube.com/watch?v=abc123"
