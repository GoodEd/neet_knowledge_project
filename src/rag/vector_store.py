from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import contextlib
import io
import logging
import os

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings, FakeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


class VectorStoreManager:
    def __init__(
        self,
        persist_directory: Optional[str] = None,
        embedding_provider: str = "huggingface",
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        embedding_dimension: int = 384,
    ) -> None:
        self.persist_directory = persist_directory or os.path.join(
            os.environ.get("DATA_DIR", "./data"), "faiss_index"
        )
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension

        self.embeddings: Optional[Embeddings] = None
        self.vectorstore: Optional[FAISS] = None
        self._initialize_embeddings()

    def _initialize_embeddings(self) -> None:
        if self.embedding_provider == "huggingface":
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

            def _build_hf_embeddings() -> HuggingFaceEmbeddings:
                return HuggingFaceEmbeddings(
                    model_name=self.embedding_model,
                    model_kwargs={"device": "cpu"},
                    encode_kwargs={"normalize_embeddings": True},
                )

            try:
                self.embeddings = _build_hf_embeddings()
            except BrokenPipeError:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.embeddings = _build_hf_embeddings()
        elif self.embedding_provider == "openai":
            self.embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=os.getenv("OPENAI_API_KEY"),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]  # LangChain accepts raw str API keys at runtime
            )
        elif self.embedding_provider == "fake":
            self.embeddings = FakeEmbeddings(size=self.embedding_dimension)
        else:
            raise ValueError(
                f"Unsupported embedding provider: {self.embedding_provider}"
            )

    def create_vectorstore(
        self, documents: List[Document], collection_name: str = "neet_knowledge"
    ) -> FAISS:
        if not documents:
            raise ValueError("No documents provided")
        if self.embeddings is None:
            raise ValueError("Embeddings not initialized")
        embeddings = self.embeddings
        assert embeddings is not None

        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

        self.vectorstore = FAISS.from_documents(
            documents=documents,
            embedding=embeddings,
        )
        self.vectorstore.save_local(self.persist_directory)

        return self.vectorstore

    def load_vectorstore(self, collection_name: str = "neet_knowledge") -> FAISS:
        if not os.path.exists(self.persist_directory):
            raise FileNotFoundError(f"No vectorstore found at {self.persist_directory}")
        if self.embeddings is None:
            raise ValueError("Embeddings not initialized")
        embeddings = self.embeddings
        assert embeddings is not None

        self.vectorstore = FAISS.load_local(
            self.persist_directory,
            embeddings,
            allow_dangerous_deserialization=True,
        )

        return self.vectorstore

    def add_documents(self, documents: List[Document]) -> FAISS:
        if self.vectorstore is None:
            return self.create_vectorstore(documents)

        self.vectorstore.add_documents(documents)
        self.vectorstore.save_local(self.persist_directory)

        return self.vectorstore

    def similarity_search(
        self, query: str, k: int = 5, filter: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        if self.vectorstore is None:
            raise ValueError(
                "Vectorstore not initialized. Load or create a vectorstore first."
            )

        return self.vectorstore.similarity_search(query=query, k=k, filter=filter)

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        fetch_k: Optional[int] = None,
    ) -> List[Tuple[Document, float]]:
        if self.vectorstore is None:
            raise ValueError(
                "Vectorstore not initialized. Load or create a vectorstore first."
            )

        kwargs: Dict[str, Any] = {"query": query, "k": k}
        if filter is not None:
            kwargs["filter"] = filter
            kwargs["fetch_k"] = fetch_k or max(k * 100, 1000)
        elif fetch_k is not None:
            kwargs["fetch_k"] = fetch_k

        return self.vectorstore.similarity_search_with_score(**kwargs)

    def delete_collection(self, collection_name: str = "neet_knowledge") -> None:
        if os.path.exists(self.persist_directory):
            import shutil

            shutil.rmtree(self.persist_directory)

    def delete_by_source(self, source: str, track_id: Optional[str] = None) -> int:
        return self._delete_by_metadata_key(
            metadata_key="source",
            metadata_value=source,
            track_id=track_id,
            include_trackless_when_track_set=True,
        )

    def delete_by_source_id(
        self, source_id: str, track_id: Optional[str] = None
    ) -> int:
        return self._delete_by_metadata_key(
            metadata_key="source_id",
            metadata_value=source_id,
            track_id=track_id,
            include_trackless_when_track_set=False,
        )

    def has_documents_for_source_id(self, source_id: str) -> bool:
        if not os.path.exists(self.persist_directory):
            return False

        if self.vectorstore is None:
            try:
                self.load_vectorstore()
            except FileNotFoundError:
                return False

        if self.vectorstore is None:
            return False

        doc_map = getattr(self.vectorstore.docstore, "_dict", {})
        for doc in doc_map.values():
            if isinstance(doc, Document) and doc.metadata.get("source_id") == source_id:
                return True
        return False

    def delete_by_source_id_and_question_id(
        self, source_id: str, question_id: str
    ) -> int:
        if not os.path.exists(self.persist_directory):
            return 0

        if self.vectorstore is None:
            self.load_vectorstore()
        if self.vectorstore is None:
            return 0
        if self.embeddings is None:
            raise ValueError("Embeddings not initialized")
        vectorstore = self.vectorstore
        embeddings = self.embeddings
        assert embeddings is not None

        doc_map = getattr(vectorstore.docstore, "_dict", {})
        all_docs = [doc for doc in doc_map.values() if isinstance(doc, Document)]

        keep_docs: List[Document] = []
        removed = 0
        for doc in all_docs:
            same_source_id = doc.metadata.get("source_id") == source_id
            same_question_id = str(doc.metadata.get("question_id", "")) == str(
                question_id
            )
            if same_source_id and same_question_id:
                removed += 1
            else:
                keep_docs.append(doc)

        if removed == 0:
            return 0

        if keep_docs:
            self.vectorstore = FAISS.from_documents(
                documents=keep_docs,
                embedding=embeddings,
            )
            self.vectorstore.save_local(self.persist_directory)
        else:
            self.delete_collection()
            self.vectorstore = None

        return removed

    def _delete_by_metadata_key(
        self,
        metadata_key: str,
        metadata_value: str,
        track_id: Optional[str],
        include_trackless_when_track_set: bool,
    ) -> int:
        if not os.path.exists(self.persist_directory):
            return 0

        if self.vectorstore is None:
            self.load_vectorstore()
        if self.vectorstore is None:
            return 0
        if self.embeddings is None:
            raise ValueError("Embeddings not initialized")
        vectorstore = self.vectorstore
        embeddings = self.embeddings
        assert embeddings is not None

        doc_map = getattr(vectorstore.docstore, "_dict", {})
        all_docs = [doc for doc in doc_map.values() if isinstance(doc, Document)]

        keep_docs: List[Document] = []
        removed = 0
        for doc in all_docs:
            same_source = doc.metadata.get(metadata_key) == metadata_value
            doc_track_id = doc.metadata.get("track_id")
            same_track = track_id is None or doc_track_id == track_id
            legacy_trackless_match = (
                include_trackless_when_track_set
                and track_id is not None
                and not doc_track_id
            )
            if same_source and (same_track or legacy_trackless_match):
                removed += 1
            else:
                keep_docs.append(doc)

        if removed == 0:
            return 0

        if keep_docs:
            self.vectorstore = FAISS.from_documents(
                documents=keep_docs,
                embedding=embeddings,
            )
            self.vectorstore.save_local(self.persist_directory)
        else:
            self.delete_collection()
            self.vectorstore = None

        return removed

    def get_collection_info(self) -> Dict[str, Any]:
        if self.vectorstore is None:
            return {"status": "not_initialized"}

        return {
            "collection_name": "faiss_index",
            "embedding_model": self.embedding_model,
            "persist_directory": self.persist_directory,
        }

    def get_all_documents(self) -> List[Document]:
        if self.vectorstore is None:
            return []
        docstore = self.vectorstore.docstore
        if hasattr(docstore, "_dict"):
            return list(docstore._dict.values())
        return []


_SOURCE_TYPE_YOUTUBE = "youtube"
_SOURCE_TYPE_CSV = "csv"


class CompositeVectorStoreManager:
    """Wraps per-source-type VectorStoreManagers behind the same interface
    used by content_manager, Admin page, and NEETRAG.

    Searches route by ``filter["source_type"]``; writes route by doc metadata;
    deletes fan out to all sub-managers.
    """

    def __init__(
        self,
        managers: Dict[str, VectorStoreManager],
        *,
        default_source_type: str = _SOURCE_TYPE_YOUTUBE,
    ):
        if not managers:
            raise ValueError("At least one sub-manager is required")
        self._managers = managers
        self._default_source_type = default_source_type

        first = next(iter(managers.values()))
        self.embedding_model = first.embedding_model
        self.embeddings = first.embeddings
        self.persist_directory = first.persist_directory

    def _manager_for_source_type(self, source_type: str) -> VectorStoreManager:
        return self._managers.get(source_type) or next(iter(self._managers.values()))

    def _manager_for_filter(
        self, filter: Optional[Dict[str, Any]]
    ) -> Optional[VectorStoreManager]:
        if filter and "source_type" in filter:
            st = filter["source_type"]
            if st in self._managers:
                return self._managers[st]
        return None

    @staticmethod
    def _strip_source_type_filter(
        filter: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if filter is None:
            return None
        rest = {k: v for k, v in filter.items() if k != "source_type"}
        return rest or None

    @property
    def vectorstore(self) -> Optional[FAISS]:
        for mgr in self._managers.values():
            if mgr.vectorstore is not None:
                return mgr.vectorstore
        return None

    def load_vectorstore(self, collection_name: str = "neet_knowledge") -> None:
        errors: List[str] = []
        for label, mgr in self._managers.items():
            try:
                mgr.load_vectorstore(collection_name=collection_name)
            except FileNotFoundError:
                logger.warning(
                    "Sub-index '%s' not found at %s — skipping",
                    label,
                    mgr.persist_directory,
                )
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        if errors and all(mgr.vectorstore is None for mgr in self._managers.values()):
            raise FileNotFoundError(
                "No sub-indexes could be loaded: " + "; ".join(errors)
            )

    def create_vectorstore(
        self, documents: List[Document], collection_name: str = "neet_knowledge"
    ) -> None:
        buckets: Dict[str, List[Document]] = {k: [] for k in self._managers}
        for doc in documents:
            st = doc.metadata.get("source_type", self._default_source_type)
            bucket = st if st in buckets else self._default_source_type
            buckets[bucket].append(doc)

        for label, docs in buckets.items():
            if docs:
                self._managers[label].create_vectorstore(
                    docs, collection_name=collection_name
                )

    def add_documents(self, documents: List[Document]) -> None:
        buckets: Dict[str, List[Document]] = {k: [] for k in self._managers}
        for doc in documents:
            st = doc.metadata.get("source_type", self._default_source_type)
            bucket = st if st in buckets else self._default_source_type
            buckets[bucket].append(doc)

        for label, docs in buckets.items():
            if docs:
                self._managers[label].add_documents(docs)

    def similarity_search(
        self, query: str, k: int = 5, filter: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        target = self._manager_for_filter(filter)
        if target is not None:
            remaining_filter = self._strip_source_type_filter(filter)
            return target.similarity_search(query=query, k=k, filter=remaining_filter)

        all_docs: List[Document] = []
        for mgr in self._managers.values():
            if mgr.vectorstore is None:
                continue
            try:
                all_docs.extend(mgr.similarity_search(query=query, k=k, filter=filter))
            except Exception:
                continue
        return all_docs[:k]

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        fetch_k: Optional[int] = None,
    ) -> List[Tuple[Document, float]]:
        target = self._manager_for_filter(filter)
        if target is not None:
            remaining_filter = self._strip_source_type_filter(filter)
            return target.similarity_search_with_score(
                query=query, k=k, filter=remaining_filter, fetch_k=fetch_k
            )

        all_scored: List[Tuple[Document, float]] = []
        for mgr in self._managers.values():
            if mgr.vectorstore is None:
                continue
            try:
                all_scored.extend(
                    mgr.similarity_search_with_score(
                        query=query, k=k, filter=filter, fetch_k=fetch_k
                    )
                )
            except Exception:
                continue
        all_scored.sort(key=lambda pair: pair[1])
        return all_scored[:k]

    def delete_collection(self, collection_name: str = "neet_knowledge") -> None:
        for mgr in self._managers.values():
            mgr.delete_collection(collection_name=collection_name)

    def delete_by_source(self, source: str, track_id: Optional[str] = None) -> int:
        total = 0
        for mgr in self._managers.values():
            total += mgr.delete_by_source(source, track_id=track_id)
        return total

    def delete_by_source_id(
        self, source_id: str, track_id: Optional[str] = None
    ) -> int:
        total = 0
        for mgr in self._managers.values():
            total += mgr.delete_by_source_id(source_id, track_id=track_id)
        return total

    def delete_by_source_id_and_question_id(
        self, source_id: str, question_id: str
    ) -> int:
        total = 0
        for mgr in self._managers.values():
            total += mgr.delete_by_source_id_and_question_id(source_id, question_id)
        return total

    def get_collection_info(self) -> Dict[str, Any]:
        sub_info = {}
        for label, mgr in self._managers.items():
            sub_info[label] = mgr.get_collection_info()
        return {
            "type": "composite",
            "sub_indexes": sub_info,
            "embedding_model": self.embedding_model,
        }

    def get_all_documents(self) -> List[Document]:
        all_docs: List[Document] = []
        for mgr in self._managers.values():
            all_docs.extend(mgr.get_all_documents())
        return all_docs


def build_composite_manager(
    base_persist_directory: str,
    embedding_provider: str = "huggingface",
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    embedding_dimension: int = 384,
) -> CompositeVectorStoreManager:
    """Build youtube + csv sub-indexes under ``base_persist_directory/youtube/``
    and ``base_persist_directory/csv/``, sharing a single embedding model.
    """
    youtube_dir = os.path.join(base_persist_directory, "youtube")
    csv_dir = os.path.join(base_persist_directory, "csv")

    primary = VectorStoreManager(
        persist_directory=youtube_dir,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
    )

    csv_mgr = VectorStoreManager.__new__(VectorStoreManager)
    csv_mgr.persist_directory = csv_dir
    csv_mgr.embedding_provider = embedding_provider
    csv_mgr.embedding_model = embedding_model
    csv_mgr.embedding_dimension = embedding_dimension
    csv_mgr.embeddings = primary.embeddings
    csv_mgr.vectorstore = None

    return CompositeVectorStoreManager(
        managers={
            _SOURCE_TYPE_YOUTUBE: primary,
            _SOURCE_TYPE_CSV: csv_mgr,
        },
    )
