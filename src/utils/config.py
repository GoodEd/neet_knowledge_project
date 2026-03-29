"""Configuration loader for NEET Knowledge RAG System."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml


class Config:
    config_path: Path
    _config: dict[str, object]

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        self.config_path = Path(config_path)
        self._config = self._load_config()

    def _load_config(self) -> dict[str, object]:
        defaults = self._default_config()

        if not self.config_path.exists():
            base_dir = Path(__file__).parent.parent.parent
            self.config_path = base_dir / "config.yaml"
            if not self.config_path.exists():
                return defaults

        with open(self.config_path, "r", encoding="utf-8") as f:
            loaded_config_obj = cast(object, yaml.safe_load(f))

        loaded_config: dict[str, object]
        if isinstance(loaded_config_obj, dict):
            loaded_config = cast(dict[str, object], loaded_config_obj)
        else:
            loaded_config = {}

        return self._merge_dicts(defaults, loaded_config)

    def _merge_dicts(
        self,
        defaults: dict[str, object],
        override: dict[str, object],
    ) -> dict[str, object]:
        merged: dict[str, object] = dict(defaults)
        for key, value in override.items():
            current = merged.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                current_dict = cast(dict[str, object], current)
                value_dict = cast(dict[str, object], value)
                merged[key] = self._merge_dicts(current_dict, value_dict)
            else:
                merged[key] = value
        return merged

    def _default_config(self) -> dict[str, object]:
        return {
            "vector_db": {
                "type": "faiss",
                "persist_dir": os.path.join(
                    os.environ.get("DATA_DIR", "./data"), "faiss_index"
                ),
            },
            "embedding": {
                "provider": "huggingface",
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "dimension": 384,
            },
            "llm": {
                "provider": "ollama",
                "model": "llama3.2",
            },
            "processing": {
                "chunk_size": 1000,
                "chunk_overlap": 200,
            },
            "translation": {
                "enabled": False,
                "provider": "transformers",
                "model": "google/translategemma-12b-it",
                "source_lang": "hi",
                "target_lang": "en",
                "max_chars_per_request": 1500,
                "apply_only_to_s3_transcript": True,
            },
            "rag": {
                "retrieval_top_k": 5,
                "similarity_threshold": 0.7,
            },
            "paths": {
                "data_dir": "./data",
                "content_dir": os.path.join(
                    os.environ.get("DATA_DIR", "./data"), "content"
                ),
                "test_data_dir": "./tests/test_data",
            },
        }

    def get(self, key: str, default: object = None) -> object:
        keys = key.split(".")
        value: object = self._config
        for k in keys:
            if isinstance(value, Mapping):
                value = cast(Mapping[str, object], value).get(k)
            else:
                return default
        return value if value is not None else default

    @property
    def vector_db_type(self) -> str:
        return cast(str, self.get("vector_db.type", "faiss"))

    @property
    def persist_dir(self) -> str:
        return cast(
            str,
            self.get(
                "vector_db.persist_dir",
                os.path.join(os.environ.get("DATA_DIR", "./data"), "faiss_index"),
            ),
        )

    @property
    def embedding_provider(self) -> str:
        return cast(str, self.get("embedding.provider", "huggingface"))

    @property
    def embedding_model(self) -> str:
        return cast(
            str,
            self.get(
                "embedding.model",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
        )

    @property
    def embedding_dimension(self) -> int:
        return cast(int, self.get("embedding.dimension", 384))

    @property
    def llm_provider(self) -> str:
        return cast(str, self.get("llm.provider", "ollama"))

    @property
    def llm_model(self) -> str:
        return cast(str, self.get("llm.model", "llama3.2"))

    @property
    def chunk_size(self) -> int:
        return cast(int, self.get("processing.chunk_size", 400))

    @property
    def chunk_overlap(self) -> int:
        return cast(int, self.get("processing.chunk_overlap", 80))

    @property
    def translation_enabled(self) -> bool:
        return cast(bool, self.get("translation.enabled", False))

    @property
    def translation_provider(self) -> str:
        return cast(str, self.get("translation.provider", "transformers"))

    @property
    def translation_model(self) -> str:
        return cast(str, self.get("translation.model", "google/translategemma-12b-it"))

    @property
    def translation_source_lang(self) -> str:
        return cast(str, self.get("translation.source_lang", "hi"))

    @property
    def translation_target_lang(self) -> str:
        return cast(str, self.get("translation.target_lang", "en"))

    @property
    def translation_max_chars_per_request(self) -> int:
        return cast(int, self.get("translation.max_chars_per_request", 1500))

    @property
    def translation_apply_only_to_s3_transcript(self) -> bool:
        return cast(bool, self.get("translation.apply_only_to_s3_transcript", True))

    @property
    def retrieval_top_k(self) -> int:
        return cast(int, self.get("rag.retrieval_top_k", 5))

    @property
    def similarity_threshold(self) -> float:
        return cast(float, self.get("rag.similarity_threshold", 0.7))

    @property
    def data_dir(self) -> str:
        return cast(str, self.get("paths.data_dir", "./data"))

    @property
    def content_dir(self) -> str:
        return cast(
            str,
            self.get(
                "paths.content_dir",
                os.path.join(os.environ.get("DATA_DIR", "./data"), "content"),
            ),
        )


config = Config()
