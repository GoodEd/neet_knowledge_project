#!/usr/bin/env bash
set -euo pipefail

# Start Streamlit in the background
streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.enableCORS false \
  --server.enableWebsocketCompression false &

STREAMLIT_PID=$!

# Wait for Streamlit to be ready (up to 30s)
echo "[entrypoint] Waiting for Streamlit on port 8501..."
for i in $(seq 1 60); do
  if curl -sf -o /dev/null http://localhost:8501/_stcore/health 2>/dev/null; then
    echo "[entrypoint] Streamlit is up (attempt $i)."
    break
  fi
  sleep 0.5
done

# Fire a request to trigger app.py execution and warm the RAG cache
echo "[entrypoint] Triggering RAG warmup..."
curl -sf -o /dev/null http://localhost:8501/ || true
echo "[entrypoint] Warmup request sent."

# Hand off to Streamlit as the main process
wait $STREAMLIT_PID
