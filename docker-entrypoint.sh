#!/bin/sh
set -eu



API_PORT="${API_BASE_PORT:-27099}"
DB_IP="${DB_IP:-mongo.steam.internal}"
DB_PORT="${DB_PORT:-27017}"

# --- FONCTION D'IMPORT (ARRIÈRE-PLAN) ---
init_database_async() {
  echo "[INIT] Background task: Checking MongoDB at ${DB_IP}:${DB_PORT}..."
  while ! nc -z "${DB_IP}" "${DB_PORT}" >/dev/null 2>&1; do
    sleep 2
  done
  echo "[INIT] MongoDB is reachable. Starting import..."

  marker_file="/app/db_initialized"
  if [ "${RUN_DB_IMPORT:-1}" = "1" ] && [ ! -f "${marker_file}" ]; then
    echo "[INIT] Running DB_import.py..."
    # Utilisation du chemin relatif correct depuis /app
    if uv run src/DB_import.py --workers 4 --log-level INFO; then
      touch "$marker_file"
      echo "[INIT] DB import successful."
    fi
  fi
}

# 1) Lancer l'initialisation de la DB en fond
init_database_async &

# On se place à la racine
cd /app

# 2) Lancer l'API en fond
echo "[START] Starting API..."
# On utilise --app-dir pour éviter le 'cd' et rester à la racine
uv run uvicorn API_DB:app --app-dir src --host 0.0.0.0 --port "${API_PORT}" &

# 3) CONFIGURER STREAMLIT (C'est ce qui règle la page blanche)
mkdir -p /.streamlit
cat <<EOF > /.streamlit/config.toml
[server]
port = 8080
address = "0.0.0.0"
enableCORS = false
enableXsrfProtection = false
headless = true

[browser]
gatherUsageStats = false
EOF

# 4) LANCEMENT FINAL DE STREAMLIT (AU PREMIER PLAN)
echo "[START] Starting Streamlit on port 8080..."
# Pas de parenthèses, pas de &, pas de wait après. 
# exec remplace le script par Streamlit.
exec uv run streamlit run src/Application/app.py --server.port 8080 --server.address 0.0.0.0