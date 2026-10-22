#!/bin/bash
set -e
cd "$(dirname "$0")/.."
mkdir -p data
export CCR_LLM_ENABLED=false
export CCR_DATABASE_URL="${CCR_DATABASE_URL:-sqlite:///./data/ccr_xva.db}"
export PYTHONPATH=src
if ! curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null; then
  python -m uvicorn ccr_xva.api.main:app --host 127.0.0.1 --port 8000 > /tmp/ccr-api.log 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null; then
      break
    fi
    sleep 1
  done
fi
exec python -m streamlit run src/ccr_xva/ui/app.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --server.enableWebsocketCompression false
