import json
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple


def _clean(value: str) -> str:
    value = (value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return cleaned.strip("._-") or "default"


def index_root(data_dir: Optional[str] = None) -> str:
    root_data = data_dir or os.environ.get("DATA_DIR", "./data")
    return os.path.join(root_data, "faiss_indexes")


def active_index_file(data_dir: Optional[str] = None) -> str:
    return os.path.join(index_root(data_dir), "active_index.json")


def build_index_name(embedding_provider: str, embedding_model: str) -> str:
    return f"{_clean(embedding_provider)}__{_clean(embedding_model)}"


def resolve_index_directory(
    embedding_provider: str,
    embedding_model: str,
    index_name: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> str:
    root = index_root(data_dir)
    provider = _clean(embedding_provider)
    model = _clean(embedding_model)
    name = _clean(index_name or build_index_name(embedding_provider, embedding_model))
    return os.path.join(root, provider, model, name)


def get_active_index(data_dir: Optional[str] = None) -> Optional[Dict[str, str]]:
    path = active_index_file(data_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return None
        if not payload.get("embedding_provider") or not payload.get("embedding_model"):
            return None
        return payload
    except Exception:
        return None


def set_active_index(
    embedding_provider: str,
    embedding_model: str,
    index_name: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> Dict[str, str]:
    root = index_root(data_dir)
    Path(root).mkdir(parents=True, exist_ok=True)
    payload = {
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "index_name": index_name
        or build_index_name(embedding_provider, embedding_model),
        "persist_directory": resolve_index_directory(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            index_name=index_name,
            data_dir=data_dir,
        ),
    }
    with open(active_index_file(data_dir), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def resolve_runtime_index(
    embedding_provider: str,
    embedding_model: str,
    persist_directory: Optional[str] = None,
    index_name: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> Tuple[str, str, str]:
    if persist_directory:
        return embedding_provider, embedding_model, persist_directory

    active = get_active_index(data_dir)
    if active and not index_name:
        return (
            active.get("embedding_provider", embedding_provider),
            active.get("embedding_model", embedding_model),
            active.get("persist_directory")
            or resolve_index_directory(
                embedding_provider=active.get("embedding_provider", embedding_provider),
                embedding_model=active.get("embedding_model", embedding_model),
                index_name=active.get("index_name"),
                data_dir=data_dir,
            ),
        )

    return (
        embedding_provider,
        embedding_model,
        resolve_index_directory(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            index_name=index_name,
            data_dir=data_dir,
        ),
    )
