import os
import sys
import time

sys.path.insert(0, os.getcwd())

print("[startup] Pre-warming RAG singleton...")
t0 = time.monotonic()
from src.utils.rag_singleton import get_rag_system  # noqa: E402

get_rag_system()
print(f"[startup] RAG singleton ready in {time.monotonic() - t0:.1f}s")

sys.argv = [
    "streamlit",
    "run",
    "app.py",
    "--server.address",
    "0.0.0.0",
    "--server.enableCORS",
    "false",
    "--server.enableWebsocketCompression",
    "false",
]

from streamlit.web.cli import main  # noqa: E402

main()
