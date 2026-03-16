# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportAny=false, reportPrivateUsage=false, reportArgumentType=false, reportAttributeAccessIssue=false, reportUnusedCallResult=false, reportUnannotatedClassAttribute=false
import os
import sys
from pathlib import Path

import pytest
from langchain_core.documents import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.vector_store import (
    CompositeVectorStoreManager,
    VectorStoreManager,
    build_composite_manager,
)


class RecordingManager:
    def __init__(self, label: str, *, has_vectorstore: bool = True):
        self.label = label
        self.embedding_model = f"{label}-embedding"
        self.embeddings = object()
        self.persist_directory = f"/tmp/{label}"
        self.vectorstore = object() if has_vectorstore else None

        self.added_batches = []
        self.search_calls = []
        self.search_with_score_calls = []
        self.delete_calls = []

    def add_documents(self, documents):
        self.added_batches.append(documents)

    def similarity_search(self, query, k=5, filter=None):
        self.search_calls.append({"query": query, "k": k, "filter": filter})
        return [
            Document(
                page_content=f"{self.label}-result-{i}",
                metadata={"source_type": self.label, "rank": i},
            )
            for i in range(k)
        ]

    def similarity_search_with_score(self, query, k=5, filter=None, fetch_k=None):
        self.search_with_score_calls.append(
            {
                "query": query,
                "k": k,
                "filter": filter,
                "fetch_k": fetch_k,
            }
        )
        return [
            (
                Document(
                    page_content=f"{self.label}-scored-{i}",
                    metadata={"source_type": self.label, "rank": i},
                ),
                float(i),
            )
            for i in range(k)
        ]

    def delete_by_source(self, source, track_id=None):
        self.delete_calls.append({"source": source, "track_id": track_id})
        return 1

    def get_collection_info(self):
        return {
            "collection_name": self.label,
            "persist_directory": self.persist_directory,
        }


def _make_doc(text: str, source_type: str | None = None, **metadata):
    doc_metadata = dict(metadata)
    if source_type is not None:
        doc_metadata["source_type"] = source_type
    return Document(page_content=text, metadata=doc_metadata)


def _make_real_manager(path: Path) -> VectorStoreManager:
    return VectorStoreManager(
        persist_directory=str(path),
        embedding_provider="fake",
        embedding_dimension=16,
    )


def _stored_docs(manager: VectorStoreManager):
    if manager.vectorstore is None:
        return []
    doc_map = getattr(manager.vectorstore.docstore, "_dict", {})
    return [doc for doc in doc_map.values() if isinstance(doc, Document)]


def test_composite_requires_at_least_one_manager():
    with pytest.raises(ValueError, match="At least one sub-manager is required"):
        CompositeVectorStoreManager(managers={})


def test_manager_for_filter_routes_by_source_type():
    yt = RecordingManager("youtube")
    csv = RecordingManager("csv")
    composite = CompositeVectorStoreManager({"youtube": yt, "csv": csv})

    selected = composite._manager_for_filter({"source_type": "csv"})

    assert selected is csv


def test_manager_for_filter_returns_none_without_source_type():
    yt = RecordingManager("youtube")
    csv = RecordingManager("csv")
    composite = CompositeVectorStoreManager({"youtube": yt, "csv": csv})

    assert composite._manager_for_filter({"source": "chapter-1"}) is None
    assert composite._manager_for_filter(None) is None


def test_strip_source_type_filter_preserves_other_fields():
    stripped = CompositeVectorStoreManager._strip_source_type_filter(
        {"source_type": "youtube", "source": "abc", "track_id": "t1"}
    )

    assert stripped == {"source": "abc", "track_id": "t1"}


def test_strip_source_type_filter_returns_none_when_only_source_type():
    assert (
        CompositeVectorStoreManager._strip_source_type_filter(
            {"source_type": "youtube"}
        )
        is None
    )


def test_add_documents_routes_docs_by_source_type():
    yt = RecordingManager("youtube")
    csv = RecordingManager("csv")
    composite = CompositeVectorStoreManager({"youtube": yt, "csv": csv})

    docs = [
        _make_doc("yt-1", source_type="youtube", source="yt1"),
        _make_doc("csv-1", source_type="csv", source="csv1"),
        _make_doc("unknown", source_type="pdf", source="pdf1"),
        _make_doc("missing", source="no-type"),
    ]

    composite.add_documents(docs)

    assert len(yt.added_batches) == 1
    assert len(csv.added_batches) == 1
    assert [doc.metadata.get("source") for doc in yt.added_batches[0]] == [
        "yt1",
        "pdf1",
        "no-type",
    ]
    assert [doc.metadata.get("source") for doc in csv.added_batches[0]] == ["csv1"]


def test_similarity_search_routes_to_specific_manager_with_source_type_filter():
    yt = RecordingManager("youtube")
    csv = RecordingManager("csv")
    composite = CompositeVectorStoreManager({"youtube": yt, "csv": csv})

    results = composite.similarity_search(
        query="find topic", k=2, filter={"source_type": "csv", "source": "sheet1"}
    )

    assert len(csv.search_calls) == 1
    assert csv.search_calls[0]["filter"] == {"source": "sheet1"}
    assert yt.search_calls == []
    assert all(doc.metadata["source_type"] == "csv" for doc in results)


def test_similarity_search_with_score_routes_with_source_type_filter():
    yt = RecordingManager("youtube")
    csv = RecordingManager("csv")
    composite = CompositeVectorStoreManager({"youtube": yt, "csv": csv})

    results = composite.similarity_search_with_score(
        query="rank docs",
        k=3,
        filter={"source_type": "youtube", "source": "lecture-1"},
        fetch_k=77,
    )

    assert len(yt.search_with_score_calls) == 1
    assert yt.search_with_score_calls[0]["filter"] == {"source": "lecture-1"}
    assert yt.search_with_score_calls[0]["fetch_k"] == 77
    assert csv.search_with_score_calls == []
    assert all(doc.metadata["source_type"] == "youtube" for doc, _ in results)


def test_similarity_search_without_filter_fans_out_to_all_managers():
    yt = RecordingManager("youtube")
    csv = RecordingManager("csv")
    composite = CompositeVectorStoreManager({"youtube": yt, "csv": csv})

    results = composite.similarity_search(query="biology", k=3)

    assert len(yt.search_calls) == 1
    assert len(csv.search_calls) == 1
    assert len(results) == 3
    assert [doc.page_content for doc in results] == [
        "youtube-result-0",
        "youtube-result-1",
        "youtube-result-2",
    ]


def test_delete_by_source_fans_out_to_all_sub_managers():
    yt = RecordingManager("youtube")
    csv = RecordingManager("csv")

    def _yt_delete(source, track_id=None):
        yt.delete_calls.append({"source": source, "track_id": track_id})
        return 2

    def _csv_delete(source, track_id=None):
        csv.delete_calls.append({"source": source, "track_id": track_id})
        return 3

    yt.delete_by_source = _yt_delete
    csv.delete_by_source = _csv_delete

    composite = CompositeVectorStoreManager({"youtube": yt, "csv": csv})
    removed = composite.delete_by_source("shared-source", track_id="track-9")

    assert removed == 5
    assert yt.delete_calls == [{"source": "shared-source", "track_id": "track-9"}]
    assert csv.delete_calls == [{"source": "shared-source", "track_id": "track-9"}]


def test_get_collection_info_includes_composite_and_sub_indexes():
    yt = RecordingManager("youtube")
    csv = RecordingManager("csv")
    composite = CompositeVectorStoreManager({"youtube": yt, "csv": csv})

    info = composite.get_collection_info()

    assert info["type"] == "composite"
    assert set(info["sub_indexes"].keys()) == {"youtube", "csv"}
    assert info["sub_indexes"]["youtube"]["collection_name"] == "youtube"
    assert info["sub_indexes"]["csv"]["collection_name"] == "csv"
    assert info["embedding_model"] == yt.embedding_model


def test_build_composite_manager_creates_youtube_csv_with_shared_embeddings(tmp_path):
    composite = build_composite_manager(
        base_persist_directory=str(tmp_path / "indexes"),
        embedding_provider="fake",
        embedding_dimension=24,
    )

    assert isinstance(composite, CompositeVectorStoreManager)
    assert set(composite._managers.keys()) == {"youtube", "csv"}

    yt = composite._managers["youtube"]
    csv = composite._managers["csv"]

    assert yt.embeddings is csv.embeddings
    assert yt.persist_directory.endswith(os.path.join("indexes", "youtube"))
    assert csv.persist_directory.endswith(os.path.join("indexes", "csv"))


def test_create_vectorstore_routes_docs_to_correct_sub_managers(tmp_path):
    composite = build_composite_manager(
        base_persist_directory=str(tmp_path / "composite"),
        embedding_provider="fake",
        embedding_dimension=16,
    )

    docs = [
        _make_doc("yt-doc", source_type="youtube", source="yt-1"),
        _make_doc("csv-doc", source_type="csv", source="csv-1"),
        _make_doc("fallback-unknown", source_type="pdf", source="pdf-1"),
        _make_doc("fallback-missing", source="none-1"),
    ]

    composite.create_vectorstore(docs)

    yt_docs = _stored_docs(composite._managers["youtube"])
    csv_docs = _stored_docs(composite._managers["csv"])

    assert len(yt_docs) == 3
    assert len(csv_docs) == 1
    assert {doc.metadata.get("source") for doc in yt_docs} == {
        "yt-1",
        "pdf-1",
        "none-1",
    }
    assert {doc.metadata.get("source") for doc in csv_docs} == {"csv-1"}


def test_vectorstore_property_returns_first_non_none_vectorstore(tmp_path):
    youtube_mgr = _make_real_manager(tmp_path / "youtube")
    csv_mgr = _make_real_manager(tmp_path / "csv")

    composite = CompositeVectorStoreManager({"youtube": youtube_mgr, "csv": csv_mgr})

    assert composite.vectorstore is None

    csv_mgr.create_vectorstore([_make_doc("csv-one", source_type="csv", source="c1")])
    assert composite.vectorstore is csv_mgr.vectorstore

    youtube_mgr.create_vectorstore(
        [_make_doc("yt-one", source_type="youtube", source="y1")]
    )
    assert composite.vectorstore is youtube_mgr.vectorstore
