from typing import Dict, Any, List, Optional
from pathlib import Path
import os

from langchain_core.documents import Document
from langchain_core.embeddings import FakeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings


class VectorStoreManager:
    def __init__(
        self,
        persist_directory: str = None,
        embedding_provider: str = "huggingface",
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        embedding_dimension: int = 384,
    ):
        self.persist_directory = persist_directory or os.path.join(os.environ.get("DATA_DIR", "./data"), "faiss_index")
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension

        self.embeddings = None
        self.vectorstore = None
        self._initialize_embeddings()

    def _initialize_embeddings(self):
        if self.embedding_provider == "huggingface":
            self.embeddings = HuggingFaceEmbeddings(
                model_name=self.embedding_model,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
        elif self.embedding_provider == "openai":
            self.embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small", api_key=os.getenv("OPENAI_API_KEY")
            )
        elif self.embedding_provider == "fake":
            self.embeddings = FakeEmbeddings(size=self.embedding_dimension)
        else:
            raise ValueError(
                f"Unsupported embedding provider: {self.embedding_provider}"
            )

    def create_vectorstore(
        self, documents: List[Document], collection_name: str = "neet_knowledge"
    ):
        if not documents:
            raise ValueError("No documents provided")

        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

        self.vectorstore = FAISS.from_documents(
            documents=documents,
            embedding=self.embeddings,
        )
        self.vectorstore.save_local(self.persist_directory)

        return self.vectorstore

    def load_vectorstore(self, collection_name: str = "neet_knowledge"):
        if not os.path.exists(self.persist_directory):
            raise FileNotFoundError(f"No vectorstore found at {self.persist_directory}")

        self.vectorstore = FAISS.load_local(
            self.persist_directory,
            self.embeddings,
            allow_dangerous_deserialization=True,
        )

        return self.vectorstore

    def add_documents(self, documents: List[Document]):
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
        self, query: str, k: int = 5, filter: Optional[Dict[str, Any]] = None
    ) -> List[tuple]:
        if self.vectorstore is None:
            raise ValueError(
                "Vectorstore not initialized. Load or create a vectorstore first."
            )

        return self.vectorstore.similarity_search_with_score(
            query=query, k=k, filter=filter
        )

    def delete_collection(self, collection_name: str = "neet_knowledge"):
        if os.path.exists(self.persist_directory):
            import shutil

            shutil.rmtree(self.persist_directory)

    def get_collection_info(self) -> Dict[str, Any]:
        if self.vectorstore is None:
            return {"status": "not_initialized"}

        return {
            "collection_name": "faiss_index",
            "embedding_model": self.embedding_model,
            "persist_directory": self.persist_directory,
        }
