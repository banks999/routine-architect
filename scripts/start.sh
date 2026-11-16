#!/bin/sh
# Container entrypoint. Mongo is OPTIONAL: if MONGO_URL is set, load it from the committed data and
# serve from it; if it's unset (single-container hosts like Hugging Face Spaces) or the load fails,
# the app falls back to the parquet files and /health reports store=parquet-fallback.
# The old CMD was `load_mongo && uvicorn`, which aborted the whole container on any host without Mongo.
if [ -n "$MONGO_URL" ]; then
  python scripts/01_load_mongo.py || echo "[start] Mongo load failed; serving from parquet fallback"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
