#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
#  PROJECT BOOTSTRAP SCRIPT (Linux / macOS)
#  - Creates virtual environment (.venv)
#  - Ensures src/.env exists (via setup_env.py)
#  - Optional: DB import, NLGCL training, GenSar training
#  - Starts MongoDB, API (uvicorn) and Streamlit app
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ----------------------------------------------------------------------------
# Helper: pretty section header
# ----------------------------------------------------------------------------
section() {
    local title="$1"
    local subtitle="${2:-}"

    echo
    printf '%0.s=' {1..80}; echo
    printf '  %s\n' "$title"
    if [[ -n "$subtitle" ]]; then
        printf '%0.s-' {1..80}; echo
        printf '  %s\n' "$subtitle"
    fi
    printf '%0.s=' {1..80}; echo
    echo
}

# ----------------------------------------------------------------------------
# Helper: yes/no prompt (returns 0 for yes, 1 for no)
# ----------------------------------------------------------------------------
prompt_yes() {
    local answer
    read -r -p "$1 Type \"yes\" to continue [default: no]: " answer
    answer="${answer,,}"      # to lowercase
    [[ "$answer" == "yes" || "$answer" == "y" ]]
}

# ----------------------------------------------------------------------------
# 1) VENV CHECK
# ----------------------------------------------------------------------------
section "STEP 1/5 - Python virtual environment" "Checking for .venv folder"

FOLDER=".venv"
if [[ ! -d "$FOLDER" ]]; then
    echo "[INFO] Folder missing: \"$FOLDER\""
    echo "[INFO] Creating virtual environment with: uv venv .venv"
    echo
    uv venv .venv
    echo
    echo "[INFO] Installing dependencies: uv pip install -r requirements.txt"
    echo
    uv pip install -r requirements.txt
    echo
    echo "[OK] Virtual environment ready."
else
    echo "[OK] Folder already exists: \"$FOLDER\""
fi

# ----------------------------------------------------------------------------
# 2) .ENV CHECK
# ----------------------------------------------------------------------------
section "STEP 2/5 - Environment file" "Ensuring src/.env exists"

ENV_FILE="src/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "[INFO] ENV missing: \"$ENV_FILE\""
    echo "[INFO] Creating it via: uv run src/setup_env.py"
    echo
    uv run src/setup_env.py
    echo
    echo "[OK] Env created: \"$ENV_FILE\""
else
    echo "[OK] ENV already exists: \"$ENV_FILE\""
fi

# ----------------------------------------------------------------------------
# 3) OPTIONAL GLOBAL SETUP (DB + MODELS)
# ----------------------------------------------------------------------------
section "STEP 3/5 - Optional global setup" "DB initialization and model training"

cat <<'EOF'
This optional setup can:
  - Import Steam data into MongoDB (games / reviews / users)
  - Retrain the NLGCL model
  - Retrain the GenSar model (preprocess + train)

Note:
  - These steps can be slow on first run (index creation, full training, etc.).
EOF
echo

if prompt_yes "Run full setup now (DB + models)?"; then
    :
else
    echo
    echo "[SKIP] Global setup (DB + models) skipped."
    echo "       Proceeding to service startup."
    goto_setup_done=true
fi

if [[ "${goto_setup_done:-false}" == "true" ]]; then
    :
else
    # =========================================================================
    # 3.1) DB IMPORT (MongoDB)
    # =========================================================================
    section "SETUP A - MongoDB import" "Import Steam data and optional index creation"

    cat <<'EOF'
This step will:
  - Read games.json and all review CSV files
  - Upsert into MongoDB
  - Optionally create indexes (can be SLOW on first full run)
EOF
    echo

    if prompt_yes "Initialize / update DB now (DB_import.py)?"; then
        echo
        printf '%0.s-' {1..75}; echo
        echo "  DB_import worker threads"
        printf '%0.s-' {1..75}; echo
        cat <<'EOF'
More workers:
  - Can speed up I/O-bound parts
  - Too many may overload your machine / MongoDB
Typical values: 4 - 16
EOF
        echo

        read -r -p "Number of workers [default: 4]: " DBI_WORKERS
        DBI_WORKERS="${DBI_WORKERS:-4}"

        echo
        printf '%0.s-' {1..75}; echo
        echo "  Index creation (--build-indexes)"
        printf '%0.s-' {1..75}; echo
        cat <<'EOF'
If ENABLED:
  - Creates indexes on games / reviews / users
  - SLOW on the first full import, but speeds up queries later

If DISABLED:
  - Import is faster
  - Queries and user-building might be slower until indexes exist
EOF
        echo

        DBI_INDEX_FLAG=""
        if prompt_yes "Enable heavy index creation (--build-indexes)?"; then
            DBI_INDEX_FLAG="--build-indexes"
            echo
            echo "[INFO] Index creation: ENABLED ($DBI_INDEX_FLAG)"
            echo "       Expect a longer run on first import."
        else
            echo
            echo "[INFO] Index creation: DISABLED"
            echo "       Import will be faster, but queries may be slower."
        fi

        echo
        printf '%0.s-' {1..75}; echo
        echo "  Log level"
        printf '%0.s-' {1..75}; echo
        cat <<'EOF'
Choose verbosity:
  DEBUG   - very detailed
  INFO    - recommended
  WARNING - only important notices
  ERROR   - only errors
EOF
        echo

        read -r -p "Log level [default: INFO]: " DBI_LOGLEVEL
        DBI_LOGLEVEL="${DBI_LOGLEVEL:-INFO}"

        echo
        printf '%0.s-' {1..75}; echo
        echo "  Running DB_import.py with:"
        echo "    workers    = $DBI_WORKERS"
        echo "    log-level  = $DBI_LOGLEVEL"
        if [[ -n "$DBI_INDEX_FLAG" ]]; then
            echo "    indexes    = ENABLED ($DBI_INDEX_FLAG)"
        else
            echo "    indexes    = DISABLED"
        fi
        printf '%0.s-' {1..75}; echo
        echo

        (
            cd "$SCRIPT_DIR/src"
            uv run DB_import.py --workers "$DBI_WORKERS" --log-level "$DBI_LOGLEVEL" ${DBI_INDEX_FLAG:+$DBI_INDEX_FLAG}
        )

        echo
        echo "[OK] DB_import step finished."
    else
        echo
        echo "[SKIP] DB initialization step."
    fi

    # =========================================================================
    # 3.2) NLGCL TRAINING (optional)
    # =========================================================================
    section "SETUP B - NLGCL model training" "Optional model retrain"

    cat <<'EOF'
This step will:
  - Retrain the NLGCL model
  - Command: uv run src/NLGCL/main.py
EOF
    echo

    if prompt_yes "Retrain NLGCL model now?"; then
        echo
        echo "[RUN] NLGCL training (uv run src/NLGCL/main.py)..."
        (
            cd "$SCRIPT_DIR"
            uv run src/NLGCL/main.py
        )
        echo
        echo "[OK] NLGCL training finished."
    else
        echo
        echo "[SKIP] NLGCL retraining."
    fi

    # =========================================================================
    # 3.3) GENSAR TRAINING (optional)
    # =========================================================================
    section "SETUP C - GenSar model training" "Optional preprocessing + training"

    cat <<'EOF'
This step will:
  - Preprocess data : uv run src/GenSar/Preprocesse.py
  - Train model     : uv run src/GenSar/train_gensar.py

Both steps can be time-consuming.
EOF
    echo

    if prompt_yes "Retrain GenSar model now?"; then
        echo
        echo "[RUN] GenSar preprocessing (uv run src/GenSar/Preprocesse.py)..."
        (
            cd "$SCRIPT_DIR"
            uv run src/GenSar/Preprocesse.py
            echo
            echo "[RUN] GenSar training (uv run src/GenSar/train_gensar.py)..."
            uv run src/GenSar/train_gensar.py
        )
        echo
        echo "[OK] GenSar preprocessing + training finished."
    else
        echo
        echo "[SKIP] GenSar retraining."
    fi
fi

# ----------------------------------------------------------------------------
# 4) SERVICE STARTUP (MongoDB + API + Streamlit)
# ----------------------------------------------------------------------------
section "STEP 4/5 - Service startup" "MongoDB, API backend, and Streamlit UI"

API_BASE_PORT=""

if [[ -f "src/.env" ]]; then
    while IFS='=' read -r key value; do
        key="$(echo "$key" | xargs)"   # trim
        value="$(echo "$value" | xargs)"
        if [[ "$key" == "API_BASE_PORT" ]]; then
            API_BASE_PORT="$value"
        fi
    done < "src/.env"
fi

API_BASE_PORT="${API_BASE_PORT:-27099}"

echo "[INFO] API_BASE_PORT = $API_BASE_PORT"
echo

# Try to start MongoDB using common service managers
if command -v systemctl >/dev/null 2>&1; then
    echo "[RUN] Starting MongoDB service via systemctl (mongod)..."
    sudo systemctl start mongod || echo "[WARN] systemctl start mongod failed. Ensure MongoDB is running."
elif command -v service >/dev/null 2>&1; then
    echo "[RUN] Starting MongoDB service via service (mongod)..."
    sudo service mongod start || echo "[WARN] service mongod start failed. Ensure MongoDB is running."
else
    echo "[WARN] Could not detect service manager to start MongoDB automatically."
    echo "       Please ensure MongoDB is running (e.g., 'mongod --config <path>')."
fi
echo

echo "[RUN] Starting API backend (uvicorn API_DB:app on port $API_BASE_PORT)..."
(
    cd "$SCRIPT_DIR/src"
    PYTHONUTF8=1 uv run uvicorn API_DB:app --host 0.0.0.0 --port "$API_BASE_PORT"
) &
API_PID=$!

echo "[RUN] Starting Streamlit app (src/Application/app.py)..."
(
    cd "$SCRIPT_DIR"
    uv run streamlit run src/Application/app.py
) &
STREAMLIT_PID=$!

# ----------------------------------------------------------------------------
# 5) DONE
# ----------------------------------------------------------------------------
section "STEP 5/5 - Ready" "All requested setup steps finished; services launched."

cat <<EOF
You can now:
  - Use the API at:      http://localhost:${API_BASE_PORT}
  - Access the Streamlit UI (default): http://localhost:8501

Background processes:
  - API (uvicorn)  PID: ${API_PID}
  - Streamlit      PID: ${STREAMLIT_PID}
EOF
echo

# Script exits; uvicorn and Streamlit keep running in background.
