import os
import sys
import time

sys.path.insert(0, os.getcwd())

print("[startup] Pre-warming RAG singleton...")
t0 = time.monotonic()
from src.utils.rag_singleton import get_rag_system  # noqa: E402

rag = get_rag_system()
print(f"[startup] RAG singleton ready in {time.monotonic() - t0:.1f}s")

telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if telegram_token:
    webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "")
    if webhook_url:
        import subprocess

        print(f"[startup] Starting Telegram bot (webhook mode: {webhook_url})...")
        bot_proc = subprocess.Popen(
            [sys.executable, "run_telegram_bot.py"],
        )
        print(f"[startup] Telegram bot started (PID: {bot_proc.pid})")
    else:
        print("[startup] TELEGRAM_WEBHOOK_URL not set - skipping bot startup")

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

from importlib import import_module  # noqa: E402

import_module("streamlit.web.cli").main()
