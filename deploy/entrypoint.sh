#!/usr/bin/env bash
set -euo pipefail

# Pre-warm RAG singleton ONCE before starting any processes.
# This avoids duplicate model loading (OOM risk with 2048 MiB limit).
echo "[entrypoint] Pre-warming RAG singleton..."
python -c "
import os, sys, time
sys.path.insert(0, os.getcwd())
t0 = time.monotonic()
from src.utils.rag_singleton import get_rag_system
get_rag_system()
print(f'[entrypoint] RAG singleton ready in {time.monotonic() - t0:.1f}s')
"

# Start Telegram bot in background (if token is configured)
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "[entrypoint] Starting Telegram bot (polling mode)..."
  python run_telegram_bot.py &
  TELEGRAM_PID=$!
  echo "[entrypoint] Telegram bot started (PID: $TELEGRAM_PID)"
fi

# Start Streamlit frontend (foreground — container stays alive)
exec python deploy/start_frontend.py
