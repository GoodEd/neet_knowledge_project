import os
import threading

import streamlit as st

from src.rag.neet_rag import NEETRAG


_warmup_lock = threading.Lock()
_warmup_done = False


@st.cache_resource
def get_rag_system() -> NEETRAG:
    llm_provider = "openai"
    llm_model = os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001")
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    return NEETRAG(
        llm_provider=llm_provider, llm_model=llm_model, llm_base_url=base_url
    )


def warm_rag_system_once() -> NEETRAG:
    global _warmup_done

    if _warmup_done:
        return get_rag_system()

    with _warmup_lock:
        if _warmup_done:
            return get_rag_system()

        rag = get_rag_system()
        _warmup_done = True
        return rag
