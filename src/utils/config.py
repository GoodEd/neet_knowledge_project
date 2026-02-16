"""Configuration loader for NEET Knowledge RAG System."""

import os
import yaml
from pathlib import Path
from typing import Any, Dict


class Config:
    def __init__(self, config_path: str = "config.yaml"):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        self.config_path = Path(config_path)
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            base_dir = Path(__file__).parent.parent.parent
            self.config_path = base_dir / "config.yaml"
            if not self.config_path.exists():
                return self._default_config()

        with open(self.config_path, "r") as f:
            return yaml.safe_load(f)

    def _default_config(self) -> Dict[str, Any]:
        return {
            "vector_db": {"type": "faiss", "persist_dir": "./data/faiss_index"},
            "embedding": {
                "provider": "huggingface",
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "dimension": 384,
            },
            "llm": {"provider": "ollama", "model": "llama3.2"},
            "processing": {"chunk_size": 1000, "chunk_overlap": 200},
            "rag": {"retrieval_top_k": 5, "similarity_threshold": 0.7},
            "paths": {
                "data_dir": "./data",
                "content_dir": "./data/content",
                "test_data_dir": "./tests/test_data",
            },
        }

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    @property
    def vector_db_type(self) -> str:
        return self.get("vector_db.type", "faiss")

    @property
    def persist_dir(self) -> str:
        return self.get("vector_db.persist_dir", "./data/faiss_index")

    @property
    def embedding_provider(self) -> str:
        return self.get("embedding.provider", "huggingface")

    @property
    def embedding_model(self) -> str:
        return self.get("embedding.model", "sentence-transformers/all-MiniLM-L6-v2")

    @property
    def embedding_dimension(self) -> int:
        return self.get("embedding.dimension", 384)

    @property
    def llm_provider(self) -> str:
        return self.get("llm.provider", "ollama")

    @property
    def llm_model(self) -> str:
        return self.get("llm.model", "llama3.2")

    @property
    def chunk_size(self) -> int:
        return self.get("processing.chunk_size", 1000)

    @property
    def chunk_overlap(self) -> int:
        return self.get("processing.chunk_overlap", 200)

    @property
    def retrieval_top_k(self) -> int:
        return self.get("rag.retrieval_top_k", 5)

    @property
    def similarity_threshold(self) -> float:
        return self.get("rag.similarity_threshold", 0.7)

    @property
    def data_dir(self) -> str:
        return self.get("paths.data_dir", "./data")

    @property
    def content_dir(self) -> str:
        return self.get("paths.content_dir", "./data/content")


config = Config()
