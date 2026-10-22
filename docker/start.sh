#!/bin/sh
set -e
uvicorn ccr_xva.api.main:app --host 0.0.0.0 --port 8000 &
exec streamlit run /app/src/ccr_xva/ui/app.py --server.port 8501 --server.address 0.0.0.0
