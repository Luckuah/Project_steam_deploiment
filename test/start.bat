set "FOLDER=.venv"
rem
if not exist "%FOLDER%\" (
    echo Folder missing: "%FOLDER%"
    rem Example actions:
    uv venv .venv
    uv pip install -r requirements.txt
    echo Setup complete.
) else (
    echo Folder already exists: "%FOLDER%"
)

set "ENV=src\.env"
rem
if not exist "%ENV%" (
    echo ENV missing: "%ENV%"
    rem
    uv run src/setup_env.py
    echo Env Created.
) else (
    echo ENV already exists: "%ENV%"
)

REM ========================= GLOBAL SETUP BLOCK ========================== (Done by chat GPT because I was lazy today...)
echo.
echo ====================================================================
echo  OPTIONAL SETUP: DB initialization and model training
echo ====================================================================
echo  This setup can:
echo    - Import Steam data into MongoDB (games / reviews / users)
echo    - Retrain the NLGCL model
echo    - Retrain the GenSar model (preprocess + train)
echo.
echo  NOTE: These steps can take a long time, especially with:
echo    - Index creation on the DB
echo    - Full model training runs
echo.

set "SETUP_RUN="
set /p SETUP_RUN=Run full setup now (DB + models)? Type "yes" to continue [default: no]: 

if /I "%SETUP_RUN%"=="yes" goto DO_SETUP
if /I "%SETUP_RUN%"=="y" goto DO_SETUP

echo.
echo Skipping setup (DB + models). Proceeding to main run.
echo ====================================================================
goto SETUP_DONE


:DO_SETUP
echo.
echo ====================================================================
echo  SETUP: DB import (MongoDB)
echo ====================================================================
echo  This step will:
echo    - Read games.json and all review CSV files
echo    - Upsert into MongoDB
echo    - Optionally create indexes (can be SLOW on first full run)
echo.

set "DBI_RUN="
set /p DBI_RUN=Initialize / update DB now (DB_import.py)? Type "yes" to continue [default: no]: 

if /I "%DBI_RUN%"=="yes" goto DO_DB_IMPORT
if /I "%DBI_RUN%"=="y" goto DO_DB_IMPORT

echo.
echo Skipping DB initialization step.
echo ====================================================================
goto AFTER_DB_IMPORT


:DO_DB_IMPORT
echo.
echo ----------------------------------------------------------------
echo  DB_import will run.
echo  Choose how many worker threads to use for reviews import.
echo  More workers can speed up I/O-bound parts, but too many may
echo  overload your machine or MongoDB. Typical values: 4 - 16.
echo ----------------------------------------------------------------

set "DBI_WORKERS="
set /p DBI_WORKERS=Number of workers [default: 4]: 
if "%DBI_WORKERS%"=="" set "DBI_WORKERS=4"

echo.
echo ----------------------------------------------------------------
echo  Index creation (--build-indexes)
echo ----------------------------------------------------------------
echo  If you enable this:
echo    - The script will create indexes on games/reviews/users.
echo    - This can be SLOW on the first full import, but speeds up
echo      queries and user aggregation later.
echo.
echo  If you disable it:
echo    - Import is faster.
echo    - Queries and user-building may be slower until you build
echo      indexes.
echo.

set "DBI_INDEX="
set /p DBI_INDEX=Enable heavy index creation (--build-indexes)? Type "yes" to enable [default: no]: 

set "DBI_INDEX_FLAG="
if /I "%DBI_INDEX%"=="yes" set "DBI_INDEX_FLAG=--build-indexes"
if /I "%DBI_INDEX%"=="y"   set "DBI_INDEX_FLAG=--build-indexes"

if not "%DBI_INDEX_FLAG%"=="" (
    echo.
    echo Index creation ENABLED. Expect this run to take more time.
) else (
    echo.
    echo Index creation DISABLED. This run will be faster, but
    echo queries may be slower.
)

echo.
echo ----------------------------------------------------------------
echo  Log level
echo ----------------------------------------------------------------
echo  Choose how verbose the output should be:
echo    DEBUG   = extremely detailed (slow and noisy)
echo    INFO    = recommended (good balance)
echo    WARNING = fewer logs, only important notices
echo    ERROR   = only errors
echo.

set "DBI_LOGLEVEL="
set /p DBI_LOGLEVEL=Log level [default: INFO]: 
if "%DBI_LOGLEVEL%"=="" set "DBI_LOGLEVEL=INFO"

echo.
echo ----------------------------------------------------------------
echo  Running DB_import.py with:
echo    workers   = %DBI_WORKERS%
echo    log-level = %DBI_LOGLEVEL%
if not "%DBI_INDEX_FLAG%"=="" (
    echo    indexes   = ENABLED (%DBI_INDEX_FLAG%)
) else (
    echo    indexes   = DISABLED
)
echo ----------------------------------------------------------------
echo.

pushd "%~dp0"
cd src
uv run DB_import.py --workers %DBI_WORKERS% --log-level %DBI_LOGLEVEL% %DBI_INDEX_FLAG%
cd ..
popd

echo.
echo DB_import step finished.
echo ====================================================================

:AFTER_DB_IMPORT


echo.
echo ====================================================================
echo  SETUP: NLGCL model training (optional)
echo ====================================================================
echo  This step will:
echo    - Retrain the NLGCL model
echo    - Command: uv run src/NLGCL/main.py
echo.

set "NLGCL_RUN="
set /p NLGCL_RUN=Retrain NLGCL model now? Type "yes" to continue [default: no]: 

if /I "%NLGCL_RUN%"=="yes" goto DO_NLGCL
if /I "%NLGCL_RUN%"=="y" goto DO_NLGCL

echo.
echo Skipping NLGCL retrain.
echo ====================================================================
goto AFTER_NLGCL


:DO_NLGCL
echo.
echo Running NLGCL training (uv run src/NLGCL/main.py)...
pushd "%~dp0"
uv run src/NLGCL/main.py
popd
echo.
echo NLGCL training finished.
echo ====================================================================

:AFTER_NLGCL


echo.
echo ====================================================================
echo  SETUP: GenSar model training (optional)
echo ====================================================================
echo  This step will:
echo    - Preprocess data: uv run src/GenSar/Preprocesse.py
echo    - Train model   : uv run src/GenSar/train_gensar.py
echo.
echo  Both steps can be time-consuming (data prep + training).
echo.

set "GENSAR_RUN="
set /p GENSAR_RUN=Retrain GenSar model now? Type "yes" to continue [default: no]: 

if /I "%GENSAR_RUN%"=="yes" goto DO_GENSAR
if /I "%GENSAR_RUN%"=="y" goto DO_GENSAR

echo.
echo Skipping GenSar retrain.
echo ====================================================================
goto AFTER_GENSAR


:DO_GENSAR
echo.
echo Running GenSar preprocessing (uv run src/GenSar/Preprocesse.py)...
pushd "%~dp0"
uv run src/GenSar/Preprocesse.py
echo.
echo Running GenSar training (uv run src/GenSar/train_gensar.py)...
uv run src/GenSar/train_gensar.py
popd
echo.
echo GenSar preprocessing + training finished.
echo ====================================================================

:AFTER_GENSAR

:SETUP_DONE
REM ====================== END GLOBAL SETUP BLOCK =========================



setlocal
REM --- Read API_BASE_PORT from .env ---
for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
    if /I "%%A"=="API_BASE_PORT" set "API_BASE_PORT=%%B"
)

REM Fallback if not found
if not defined API_BASE_PORT set "API_BASE_PORT=27099"

REM --- Start services ---
net start MongoDB
@REM start "" cmd /k "cd /d src && set \"PYTHONUTF8=1\" && uv run uvicorn API_DB:app --host 0.0.0.0 --port %API_BASE_PORT% --reload"
start "" cmd /k "cd /d src && set \"PYTHONUTF8=1\" && uv run uvicorn API_DB:app --host 0.0.0.0 --port %API_BASE_PORT%"
start "" uv run streamlit run src\Application\app.py
endlocal