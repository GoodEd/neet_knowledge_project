import os
import threading

from src.rag.neet_rag import NEETRAG


_instance: NEETRAG | None = None
_lock = threading.Lock()


def get_rag_system() -> NEETRAG:
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:
            return _instance
        llm_provider = "openai"
        llm_model = os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001")
        base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        _instance = NEETRAG(
            llm_provider=llm_provider, llm_model=llm_model, llm_base_url=base_url
        )
        return _instance
