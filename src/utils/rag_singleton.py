import os

import streamlit as st

from src.rag.neet_rag import NEETRAG


@st.cache_resource
def get_rag_system() -> NEETRAG:
    llm_provider = "openai"
    llm_model = os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001")
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    return NEETRAG(
        llm_provider=llm_provider, llm_model=llm_model, llm_base_url=base_url
    )
