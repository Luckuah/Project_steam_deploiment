#!/bin/sh
set -eu

cd /app

API_PORT="${API_BASE_PORT:-27099}"
DB_IP="${DB_IP:-mongo.steam.internal}"
DB_PORT="${DB_PORT:-27017}"

# --- CETTE FONCTION TOURNE MAINTENANT EN ARRIÈRE-PLAN ---
init_database_async() {
  echo "[INIT] Background task: Checking MongoDB at ${DB_IP}:${DB_PORT}..."
  
  # On attend Mongo sans bloquer le reste du script
  while ! nc -z "${DB_IP}" "${DB_PORT}" >/dev/null 2>&1; do
    sleep 2
  done
  echo "[INIT] MongoDB is reachable. Starting import..."

  # Ta logique d'import (inchangée)
  marker_file="/app/db_initialized"
  if [ "${RUN_DB_IMPORT:-1}" = "1" ] && [ ! -f "${marker_file}" ]; then
    echo "[INIT] Running DB_import.py..."
    if uv run /app/src/DB_import.py --workers 4 --log-level INFO; then
      touch "$marker_file"
      echo "[INIT] DB import successful."
    fi
  fi
}

# 1) Lancer l'initialisation de la DB en tâche de fond (&)
init_database_async &

echo "[START] Starting API only on port ${API_PORT}..."
cd /app/src
exec uv run uvicorn API_DB:app --host 0.0.0.0 --port "${API_PORT}"
