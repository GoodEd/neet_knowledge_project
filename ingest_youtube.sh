#!/bin/bash
# Batch YouTube video ingestion script for NEET 2025 content
# Runs sequentially to avoid OpenRouter rate limits

set -e

cd /home/jp/neet_knowledge_project
source venv/bin/activate

LOG_FILE="data/ingestion_log.txt"
echo "=== YouTube Ingestion Started: $(date) ===" > "$LOG_FILE"

VIDEOS=(
    "https://www.youtube.com/watch?v=nXPX15FPfsE"
    "https://www.youtube.com/watch?v=0ewYxHCVBQ4"
    "https://www.youtube.com/watch?v=Epk7DjFybDk"
    "https://www.youtube.com/watch?v=Vi5kWOoliCo"
    "https://www.youtube.com/watch?v=vVp3rNKFAsU"
)

NAMES=(
    "NEET 2025 Full Paper Discussion"
    "Video 2"
    "Allen NEET 2025 Paper Discussion"
    "Video 4"
    "Video 5"
)

SUCCESS=0
FAIL=0

for i in "${!VIDEOS[@]}"; do
    VIDEO="${VIDEOS[$i]}"
    NAME="${NAMES[$i]}"
    echo "" >> "$LOG_FILE"
    echo "--- Video $((i+1))/5: $NAME ---" >> "$LOG_FILE"
    echo "URL: $VIDEO" >> "$LOG_FILE"
    echo "Started: $(date)" >> "$LOG_FILE"
    
    echo ">>> Processing video $((i+1))/5: $NAME ($VIDEO)"
    
    if python -m src.main --llm-provider openai --llm-model google/gemini-2.0-flash-001 --llm-base-url https://openrouter.ai/api/v1 ingest "$VIDEO" >> "$LOG_FILE" 2>&1; then
        echo "Completed: $(date)" >> "$LOG_FILE"
        echo "Status: SUCCESS" >> "$LOG_FILE"
        echo ">>> SUCCESS: Video $((i+1)) completed"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "Completed: $(date)" >> "$LOG_FILE"
        echo "Status: FAILED" >> "$LOG_FILE"
        echo ">>> FAILED: Video $((i+1))"
        FAIL=$((FAIL + 1))
    fi
    
    # Small delay between videos to avoid rate limits
    sleep 5
done

echo "" >> "$LOG_FILE"
echo "=== YouTube Ingestion Completed: $(date) ===" >> "$LOG_FILE"
echo "Success: $SUCCESS, Failed: $FAIL" >> "$LOG_FILE"

echo ""
echo "=== DONE ==="
echo "Success: $SUCCESS, Failed: $FAIL"
echo "See $LOG_FILE for details"
echo "FAISS index size:"
ls -la data/faiss_index/
