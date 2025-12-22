#!/bin/sh
set -eu

cd /app

API_PORT="${API_BASE_PORT:-27099}"
DB_IP="${DB_IP:-mongo}"
DB_PORT="${DB_PORT:-27017}"

wait_for_mongo() {
  echo "[INIT] Waiting for MongoDB at ${DB_IP}:${DB_PORT}..."
  while ! nc -z "${DB_IP}" "${DB_PORT}" >/dev/null 2>&1; do
    sleep 1
  done
  echo "[INIT] MongoDB is up."
}

run_db_import_once() {
  # Marker will persist in /init-state (shared volume)
  marker_file="/init-state/db_initialized"

  if [ "${RUN_DB_IMPORT:-1}" != "1" ]; then
    echo "[INIT] RUN_DB_IMPORT != 1, skipping DB import."
    return
  fi

  if [ -f "${marker_file}" ]; then
    echo "[INIT] DB already initialized (marker present), skipping DB_import.py."
    return
  fi

  echo "[INIT] Running DB_import.py --workers 4 --log-level INFO"
  if uv run src/DB_import.py --workers 4 --log-level INFO; then
    echo "[INIT] DB_import.py completed successfully, writing marker."
    mkdir -p "$(dirname "$marker_file")"
    touch "$marker_file"
  else
    echo "[WARN] DB_import.py failed; NOT writing marker; will retry next start."
  fi
}

_api_pid=""
_streamlit_pid=""

term_handler() {
  if [ -n "${_api_pid}" ] 2>/dev/null && kill -0 "${_api_pid}" 2>/dev/null; then
    kill "${_api_pid}" || true
  fi
  if [ -n "${_streamlit_pid}" ] 2>/dev/null && kill -0 "${_streamlit_pid}" 2>/dev/null; then
    kill "${_streamlit_pid}" || true
  fi
  wait || true
}

trap term_handler INT TERM

# 1) Wait for Mongo to be reachable
wait_for_mongo

# 2) Initialize DB once
run_db_import_once

# 3) Start API (run from src like your bootstrap does)
(
  cd /app/src
  uv run uvicorn API_DB:app --host 0.0.0.0 --port "${API_PORT}"
) &
_api_pid=$!

# 4) Start Streamlit (run from project root)
(
  cd /app
  uv run streamlit run src/Application/app.py \
    --server.port 8501 \
    --server.address 0.0.0.0
) &
_streamlit_pid=$!

# 5) Wait for either process to exit
wait
