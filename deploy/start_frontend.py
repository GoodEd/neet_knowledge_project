import os
import sys
import time

sys.path.insert(0, os.getcwd())

print("[startup] Pre-warming RAG singleton...")
t0 = time.monotonic()
from src.utils.rag_singleton import get_rag_system  # noqa: E402

rag = get_rag_system()
print(f"[startup] RAG singleton ready in {time.monotonic() - t0:.1f}s")

# Start Telegram bot in-process after RAG is warm (avoids OOM from parallel loading)
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if telegram_token:
    import subprocess

    print("[startup] Starting Telegram bot (polling mode)...")
    bot_proc = subprocess.Popen(
        [sys.executable, "run_telegram_bot.py"],
        env={**os.environ, "RAG_PREWARMED": "1"},
    )
    print(f"[startup] Telegram bot started (PID: {bot_proc.pid})")

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
