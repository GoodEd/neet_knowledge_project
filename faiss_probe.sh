#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 \"<query text>\" [--top-k N] [--show-prompt] [other options]"
  echo "Example: $0 \"work done in thermodynamics\" --top-k 8 --source-type youtube"
  exit 1
fi

python -m src.faiss_probe "$@"
