import streamlit as st
import os
import sys

# Ensure we can import from src
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.utils.ui_helpers import setup_public_page_chrome

st.set_page_config(page_title="NEET Knowledge Base", page_icon="📚", layout="wide")

setup_public_page_chrome()

st.title("Welcome to NEET Knowledge Assistant 📚")

st.markdown("""
### Your AI Study Companion for NEET 2025

This tool helps you search through vast amounts of curated NEET material, including:
- 📺 Educational YouTube video transcripts
- 📄 Curated PDFs and Study Materials

**Get Started:**
👈 Select **Chat** from the sidebar to start asking questions.
""")
