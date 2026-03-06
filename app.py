import os

import streamlit as st

from src.utils.rag_singleton import warm_rag_system_once


def _warmup_enabled() -> bool:
    return os.getenv("RAG_WARMUP_ON_LAUNCH", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


st.set_page_config(page_title="NEET PYQ Assistant", page_icon="📚", layout="wide")

if _warmup_enabled():
    warm_rag_system_once()

st.switch_page("pages/1_Chat.py")
