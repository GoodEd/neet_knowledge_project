#!/usr/bin/env bash
set -euo pipefail

# Start Telegram bot in background (if token is configured)
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "[entrypoint] Starting Telegram bot (polling mode)..."
  python run_telegram_bot.py &
  TELEGRAM_PID=$!
  echo "[entrypoint] Telegram bot started (PID: $TELEGRAM_PID)"
fi

# Start Streamlit frontend (foreground — container stays alive)
exec python deploy/start_frontend.py
