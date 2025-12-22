@echo off
setlocal

REM ============================================================================
REM  PROJECT BOOTSTRAP SCRIPT
REM  - Creates virtual environment (.venv)
REM  - Ensures src\.env exists (via setup_env.py)
REM  - Optional: DB import, NLGCL training, GenSar training
REM  - Starts MongoDB, API (uvicorn) and Streamlit app
REM ============================================================================

REM Jump over helper label definitions
goto :main

REM ----------------------------------------------------------------------------
REM Helper: pretty section header
REM ----------------------------------------------------------------------------
:section
echo.
echo ===============================================================================
echo  %~1
if not "%~2"=="" (
    echo ----------------------------------------------------------------------------
    echo  %~2
)
echo ===============================================================================
echo.
goto :eof


:main
REM ----------------------------------------------------------------------------
REM 1) VENV CHECK
REM ----------------------------------------------------------------------------
call :section "STEP 1/5 - Python virtual environment" "Checking for .venv folder"

set "FOLDER=.venv"
if not exist "%FOLDER%\" (
    echo [INFO] Folder missing: "%FOLDER%"
    echo [INFO] Creating virtual environment with:  uv venv .venv
    echo.
    uv venv .venv
    echo.
    echo [INFO] Installing dependencies:  uv pip install -r requirements.txt
    echo.
    uv pip install -r requirements.txt
    echo.
    echo [OK] Virtual environment ready.
) else (
    echo [OK] Folder already exists: "%FOLDER%"
)

REM ----------------------------------------------------------------------------
REM 2) .ENV CHECK
REM ----------------------------------------------------------------------------
call :section "STEP 2/5 - Environment file" "Ensuring src\.env exists"

set "ENV=src\.env"
if not exist "%ENV%" (
    echo [INFO] ENV missing: "%ENV%"
    echo [INFO] Creating it via:  uv run src/setup_env.py
    echo.
    uv run src/setup_env.py
    echo.
    echo [OK] Env created: "%ENV%"
) else (
    echo [OK] ENV already exists: "%ENV%"
)

REM ----------------------------------------------------------------------------
REM 3) OPTIONAL GLOBAL SETUP (DB + MODELS)
REM ----------------------------------------------------------------------------
call :section "STEP 3/5 - Optional global setup" "DB initialization and model training"

echo This optional setup can:
echo   - Import Steam data into MongoDB (games / reviews / users)
echo   - Retrain the NLGCL model
echo   - Retrain the GenSar model (preprocess + train)
echo.
echo Note:
echo   - These steps can be slow on first run (index creation, full training, etc.).
echo.

set "SETUP_RUN="
set /p SETUP_RUN=Run full setup now (DB + models)? Type "yes" to continue [default: no]: 

if /I "%SETUP_RUN%"=="yes" goto DO_SETUP
if /I "%SETUP_RUN%"=="y"   goto DO_SETUP

echo.
echo [SKIP] Global setup (DB + models) skipped.
echo        Proceeding to service startup.
goto SETUP_DONE


:DO_SETUP
REM ============================================================================
REM 3.1) DB IMPORT (MongoDB)
REM ============================================================================
call :section "SETUP A - MongoDB import" "Import Steam data and optional index creation"

echo This step will:
echo   - Read games.json and all review CSV files
echo   - Upsert into MongoDB
echo   - Optionally create indexes (can be SLOW on first full run)
echo.

set "DBI_RUN="
set /p DBI_RUN=Initialize / update DB now (DB_import.py)? Type "yes" to continue [default: no]: 

if /I "%DBI_RUN%"=="yes" goto DO_DB_IMPORT
if /I "%DBI_RUN%"=="y"   goto DO_DB_IMPORT

echo.
echo [SKIP] DB initialization step.
goto AFTER_DB_IMPORT


:DO_DB_IMPORT
echo.
echo ---------------------------------------------------------------------------
echo  DB_import worker threads
echo ---------------------------------------------------------------------------
echo  More workers:
echo    - Can speed up I/O-bound parts
echo    - Too many may overload your machine / MongoDB
echo  Typical values: 4 - 16
echo.

set "DBI_WORKERS="
set /p DBI_WORKERS=Number of workers [default: 4]: 
if "%DBI_WORKERS%"=="" set "DBI_WORKERS=4"

echo.
echo ---------------------------------------------------------------------------
echo  Index creation (--build-indexes)
echo ---------------------------------------------------------------------------
echo  If ENABLED:
echo    - Creates indexes on games / reviews / users
echo    - SLOW on the first full import, but speeds up queries later
echo.
echo  If DISABLED:
echo    - Import is faster
echo    - Queries and user-building might be slower until indexes exist
echo.

set "DBI_INDEX="
set /p DBI_INDEX=Enable heavy index creation (--build-indexes)? Type "yes" to enable [default: no]: 

set "DBI_INDEX_FLAG="
if /I "%DBI_INDEX%"=="yes" set "DBI_INDEX_FLAG=--build-indexes"
if /I "%DBI_INDEX%"=="y"   set "DBI_INDEX_FLAG=--build-indexes"

if not "%DBI_INDEX_FLAG%"=="" (
    echo.
    echo [INFO] Index creation: ENABLED (%DBI_INDEX_FLAG%)
    echo        Expect a longer run on first import.
) else (
    echo.
    echo [INFO] Index creation: DISABLED
    echo        Import will be faster, but queries may be slower.
)

echo.
echo ---------------------------------------------------------------------------
echo  Log level
echo ---------------------------------------------------------------------------
echo  Choose verbosity:
echo    DEBUG   - very detailed
echo    INFO    - recommended
echo    WARNING - only important notices
echo    ERROR   - only errors
echo.

set "DBI_LOGLEVEL="
set /p DBI_LOGLEVEL=Log level [default: INFO]: 
if "%DBI_LOGLEVEL%"=="" set "DBI_LOGLEVEL=INFO"

echo.
echo ---------------------------------------------------------------------------
echo  Running DB_import.py with:
echo    workers    = %DBI_WORKERS%
echo    log-level  = %DBI_LOGLEVEL%
if not "%DBI_INDEX_FLAG%"=="" (
    echo    indexes    = ENABLED (%DBI_INDEX_FLAG%)
) else (
    echo    indexes    = DISABLED
)
echo ---------------------------------------------------------------------------
echo.

pushd "%~dp0"
cd src
uv run DB_import.py --workers %DBI_WORKERS% --log-level %DBI_LOGLEVEL% %DBI_INDEX_FLAG%
cd ..
popd

echo.
echo [OK] DB_import step finished.

:AFTER_DB_IMPORT


REM ============================================================================
REM 3.2) NLGCL TRAINING (optional)
REM ============================================================================
call :section "SETUP B - NLGCL model training" "Optional model retrain"

echo This step will:
echo   - Retrain the NLGCL model
echo   - Command: uv run src/NLGCL/main.py
echo.

set "NLGCL_RUN="
set /p NLGCL_RUN=Retrain NLGCL model now? Type "yes" to continue [default: no]: 

if /I "%NLGCL_RUN%"=="yes" goto DO_NLGCL
if /I "%NLGCL_RUN%"=="y"   goto DO_NLGCL

echo.
echo [SKIP] NLGCL retraining.
goto AFTER_NLGCL


:DO_NLGCL
echo.
echo [RUN] NLGCL training (uv run src/NLGCL/main.py)...
pushd "%~dp0"
uv run src/NLGCL/main.py
popd
echo.
echo [OK] NLGCL training finished.

:AFTER_NLGCL


REM ============================================================================
REM 3.3) GENSAR TRAINING (optional)
REM ============================================================================
call :section "SETUP C - GenSar model training" "Optional preprocessing + training"

echo This step will:
echo   - Preprocess data : uv run src/GenSar/Preprocesse.py
echo   - Train model     : uv run src/GenSar/train_gensar.py
echo.
echo Both steps can be time-consuming.
echo.

set "GENSAR_RUN="
set /p GENSAR_RUN=Retrain GenSar model now? Type "yes" to continue [default: no]: 

if /I "%GENSAR_RUN%"=="yes" goto DO_GENSAR
if /I "%GENSAR_RUN%"=="y"   goto DO_GENSAR

echo.
echo [SKIP] GenSar retraining.
goto AFTER_GENSAR


:DO_GENSAR
echo.
echo [RUN] GenSar preprocessing (uv run src/GenSar/Preprocesse.py)...
pushd "%~dp0"
uv run src/GenSar/Preprocesse.py
echo.
echo [RUN] GenSar training (uv run src/GenSar/train_gensar.py)...
uv run src/GenSar/train_gensar.py
popd
echo.
echo [OK] GenSar preprocessing + training finished.

:AFTER_GENSAR

:SETUP_DONE
REM ============================================================================
REM 4) SERVICE STARTUP (MongoDB + API + Streamlit)
REM ============================================================================
call :section "STEP 4/5 - Service startup" "MongoDB, API backend, and Streamlit UI"

setlocal

REM --- Read API_BASE_PORT from src\.env ---
set "API_BASE_PORT="

if exist "src\.env" (
    for /f "usebackq tokens=1,2 delims==" %%A in ("src\.env") do (
        if /I "%%A"=="API_BASE_PORT" set "API_BASE_PORT=%%B"
    )
)

REM Fallback if not found
if not defined API_BASE_PORT set "API_BASE_PORT=27099"

echo [INFO] API_BASE_PORT = %API_BASE_PORT%
echo.

echo [RUN] Starting MongoDB service...
net start MongoDB
echo.

echo [RUN] Starting API backend (uvicorn API_DB:app on port %API_BASE_PORT%)...
start "" cmd /k "cd /d src && set \"PYTHONUTF8=1\" && uv run uvicorn API_DB:app --host 0.0.0.0 --port %API_BASE_PORT%"

echo [RUN] Starting Streamlit app (src\Application\app.py)...
start "" uv run streamlit run src\Application\app.py

endlocal

REM ----------------------------------------------------------------------------
REM 5) DONE
REM ----------------------------------------------------------------------------
call :section "STEP 5/5 - Ready" "All requested setup steps finished; services launched."

echo You can now:
echo   - Use the API at: http://localhost:%API_BASE_PORT%
echo   - Access the Streamlit UI (default: http://localhost:8501)
echo.

endlocal
exit /b
