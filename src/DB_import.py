from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pymongo import ASCENDING, DESCENDING, InsertOne, MongoClient, UpdateOne
from pymongo.errors import BulkWriteError
from rich.logging import RichHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
from urllib.error import HTTPError, URLError
import zipfile
import shutil
import io
import os
from decimal import Decimal

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOGGER_NAME = "steam_import"
logger = logging.getLogger(LOGGER_NAME)

import boto3
import requests
import ijson

GAMES_JSON_URL = (
    "https://data.mendeley.com/public-files/datasets/jxy85cr3th/files/"
    "9fa9989d-d4f4-426a-aad3-fa9a96700332/file_downloaded"
)
REVIEWS_ZIP_URL = (
    "https://data.mendeley.com/public-files/datasets/jxy85cr3th/files/"
    "273898e9-90f1-49ff-8d62-df52e67341b3/file_downloaded"
)

S3_BUCKET = os.getenv("S3_BUCKET")
S3_GAMES_KEY = "data/games.json"
S3_REVIEWS_KEY = "data/reviews_download.zip"

def download_and_upload_to_s3(url, bucket_name, s3_key):
    """Télécharge le fichier de Mendeley et l'envoie sur S3 sans stockage local."""
    s3 = boto3.client('s3')
    logger.info(f"Démarrage du streaming vers S3: s3://{bucket_name}/{s3_key}")
    
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        # upload_fileobj accepte un flux binaire (r.raw)
        s3.upload_fileobj(r.raw, bucket_name, s3_key)
    logger.info("Transfert S3 terminé.")

def ensure_reviews_zip_on_s3(bucket_name, s3_key, download_url):
    """Vérifie si le fichier est sur S3, sinon le télécharge."""
    s3 = boto3.client('s3')
    try:
        s3.head_object(Bucket=bucket_name, Key=s3_key)
        logger.info("Le fichier ZIP est déjà présent sur S3.")
    except:
        logger.info("Fichier ZIP absent de S3. Téléchargement initial en cours...")
        download_and_upload_to_s3(download_url, bucket_name, s3_key)

def setup_logging(level_name: str = "DEBUG") -> None:
    """
    Configure Rich logging.

    level_name: one of DEBUG, INFO, WARNING, ERROR, CRITICAL
    """
    # Normalize level
    level = getattr(logging, level_name.upper(), logging.DEBUG)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )

    logger.setLevel(level)
    logger.debug("[logging] Rich logger initialized at level: %s", level_name)


# ---------------------------------------------------------------------------
# Paths (script is in src/, data in ../data)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

ENV_PATH = BASE_DIR / ".env"  # src/.env
DATA_DIR = Path("/tmp/data")
GAMES_JSON_PATH = DATA_DIR / "games.json"
REVIEWS_DIR = DATA_DIR / "Game Reviews"

# Collections
GAMES_COLLECTION = "games"
REVIEWS_COLLECTION = "reviews"
USERS_COLLECTION = "users"

# Batch size for bulk inserts
BATCH_SIZE = 1000000


# ---------------------------------------------------------------------------
# Utility: .env loading
# ---------------------------------------------------------------------------

def load_env(env_path: Path) -> Dict[str, str]:
    """
    Minimal .env parser: KEY=VALUE per line, ignore comments and empty lines.
    """
    logger.debug("[env] Loading .env from: %s", env_path)

    env_vars: Dict[str, str] = {}
    if not env_path.exists():
        logger.warning("[env] .env file not found at %s", env_path)
        return env_vars

    for line_no, line in enumerate(env_path.read_text().splitlines(), start=1):
        raw_line = line
        line = line.strip()
        if not line or line.startswith("#"):
            logger.debug("[env] Skipping line %d: %r", line_no, raw_line)
            continue
        if "=" not in line:
            logger.warning("[env] Invalid line %d (no '='): %r", line_no, raw_line)
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        value = v.strip()
        env_vars[key] = value

    masked_env = {
        k: ("***" if "PASS" in k.upper() else v) for k, v in env_vars.items()
    }
    logger.debug("[env] Loaded keys: %s", list(masked_env.keys()))
    logger.debug("[env] Values (masked): %r", masked_env)
    return env_vars


# ---------------------------------------------------------------------------
# Utility: Mongo connection
# ---------------------------------------------------------------------------

def get_db_from_env(env: Dict[str, str]):
    """
    Build MongoClient from .env content.
    Priority:
      - MONGO_URI if present
      - else DB_USER/DB_PASSWORD + DB_IP/DB_PORT + DB_AUTH_SOURCE
      - DB_NAME from env, default "Steam_Project" if missing
    """
    db_name = env.get("DB_NAME", "Steam_Project")
    logger.debug("[mongo] Target DB_NAME: %s", db_name)

    mongo_uri = env.get("MONGO_URI")
    if mongo_uri:
        logger.info("[mongo] Connecting using MONGO_URI (masked) to DB '%s'...", db_name)
        logger.debug("[mongo] Raw MONGO_URI length: %d chars", len(mongo_uri))
        client = MongoClient(mongo_uri)
        return client[db_name]

    db_user = env.get("DB_USER")
    db_password = env.get("DB_PASSWORD")
    db_ip = env.get("DB_IP", "localhost")
    db_port = env.get("DB_PORT", "27017")
    auth_source = env.get("DB_AUTH_SOURCE", "admin")

    if db_user and db_password:
        logger.info(
            "[mongo] Connecting to MongoDB at %s:%s as '%s' (authSource=%s)...",
            db_ip,
            db_port,
            db_user,
            auth_source,
        )
        uri = f"mongodb://{db_user}:{db_password}@{db_ip}:{db_port}/?authSource={auth_source}"
        logger.debug("[mongo] Built URI length: %d chars", len(uri))
    else:
        logger.warning(
            "[mongo] DB_USER/DB_PASSWORD not fully set, connecting without credentials to %s:%s...",
            db_ip,
            db_port,
        )
        uri = f"mongodb://{db_ip}:{db_port}/"

    client = MongoClient(uri)
    logger.debug("[mongo] MongoClient created")
    return client[db_name]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_date_mdy_long(s: Optional[str]) -> Optional[datetime]:
    """
    Parse date strings like:
      - 'October 22, 2024'
      - 'Oct 22, 2024'
      - '2024-10-22'
    -> datetime or None
    """
    if not s:
        return None
    s = s.strip()
    formats = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d")
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            logger.debug("[parse_date] Parsed %r with format %r -> %s", s, fmt, dt.isoformat())
            return dt
        except ValueError:
            continue
    logger.debug("[parse_date] Could not parse date: %r", s)
    return None

def coerce_bool_recommend(s: Optional[str]) -> Optional[bool]:
    if s is None:
        return None
    t = s.strip().lower()
    if t == "recommended":
        return True
    if t == "not recommended":
        return False
    logger.debug("[recommend] Unexpected value for recommend: %r", s)
    return None


def coerce_bool_early_access(s: Optional[str]) -> bool:
    # Null/empty -> False; "Early Access Review" -> True
    if not s:
        return False
    result = s.strip().lower() == "early access review"
    logger.debug("[early_access] %r -> %s", s, result)
    return result


# ---------------------------------------------------------------------------
# Games import
# ---------------------------------------------------------------------------

def load_games_array(games_json_path: Path) -> List[dict]:
    """
    Load games from JSON. Accepts either:
      - an array of documents, or
      - a {id: {...}, id2: {...}} map and converts to array with _id set.
    Also tries to parse release_date if it's a human-readable string.
    """
    logger.info("[games] Loading JSON from %s", games_json_path)

    with games_json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        logger.debug("[games] JSON is object; converting to array with _id from keys")
        data = [
            {**v, "_id": int(k) if str(k).isdigit() else k}
            for k, v in data.items()
        ]
    else:
        logger.debug("[games] JSON is array; documents count: %d", len(data))

    for i, doc in enumerate(data):
        rd = doc.get("release_date")
        if isinstance(rd, str):
            parsed = parse_date_mdy_long(rd)
            if parsed:
                doc["release_date"] = parsed
        if i < 3:
            logger.debug("[games] Sample doc[%d] keys: %s", i, list(doc.keys()))

    logger.info("[games] Loaded %d game documents from JSON", len(data))
    return data

def import_games_from_s3(db, build_indexes: bool = False):
    """Importe les jeux en streaming direct depuis S3 vers MongoDB."""
    s3 = boto3.client('s3')
    col = db[GAMES_COLLECTION]
    
    logger.info(f"[games] Streaming de games.json depuis S3 (s3://{S3_BUCKET}/{S3_GAMES_KEY})...")
    
    try:
        response = s3.get_object(Bucket=S3_BUCKET, Key=S3_GAMES_KEY)
        # response['Body'] est un flux binaire que ijson peut lire petit à petit
        # On utilise kvitems car votre JSON est un dictionnaire { "id": {data} }
        parser = ijson.kvitems(response['Body'], '')
        
        batch = []
        batch_size = 1000
        total_inserted = 0
        
        for k, v in parser:
            # Reconstitution du document avec son ID
            doc = {**v, "_id": int(k) if str(k).isdigit() else k}

            # --- AJOUT DE LA CORRECTION ICI ---
            # On convertit le prix de Decimal à float pour MongoDB
            if "price" in doc and isinstance(doc["price"], Decimal):
                doc["price"] = float(doc["price"])
            # ----------------------------------
            
            # Parsing de la date (réutilisation de votre helper)
            rd = doc.get("release_date")
            if isinstance(rd, str):
                parsed_dt = parse_date_mdy_long(rd)
                if parsed_dt:
                    doc["release_date"] = parsed_dt
            
            # On utilise UpdateOne avec upsert pour éviter les doublons
            batch.append(UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
            
            if len(batch) >= batch_size:
                col.bulk_write(batch, ordered=False)
                total_inserted += len(batch)
                logger.info(f"🎮 {total_inserted} jeux traités...")
                batch = []
        
        if batch:
            col.bulk_write(batch, ordered=False)
            total_inserted += len(batch)

        logger.info(f"✅ Importation des jeux terminée : {total_inserted} documents.")

        if build_indexes:
            logger.info("[games] Création des index...")
            col.create_index([("name", "text")])
            col.create_index([("price", 1)])

    except Exception as e:
        logger.error(f"❌ Erreur pendant le streaming S3 des jeux: {e}")


# ---------------------------------------------------------------------------
# Reviews import (Version optimisée pour App Runner)
# ---------------------------------------------------------------------------

from smart_open import open as smart_open

def import_reviews(db, build_indexes: bool = False):
    col = db[REVIEWS_COLLECTION]
    col.drop()
    
    s3_url = f"s3://{S3_BUCKET}/{S3_REVIEWS_KEY}"
    logger.info(f"[reviews] Streaming de TOUS les fichiers du ZIP S3...")

    total_inserted = 0

    try:
        with smart_open(s3_url, 'rb') as s3_stream:
            with zipfile.ZipFile(s3_stream) as z:
                # 1. On récupère la liste de TOUS les CSV
                csv_files = [f for f in z.namelist() if f.endswith('.csv')]
                
                batch = []
                # 2. BOUCLE SUR CHAQUE FICHIER (Indispensable !)
                for csv_filename in csv_files:
                    
                    # 3. EXTRACTION DE L'APP_ID DEPUIS LE NOM (Logique locale)
                    # "Game Reviews/1000000_37.csv" -> "1000000"
                    try:
                        pure_name = csv_filename.split('/')[-1] # Enlever le dossier
                        file_app_id = int(pure_name.split('_')[0])
                    except:
                        file_app_id = 0

                    with z.open(csv_filename) as f:
                        reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
                        
                        for row in reader:
                            user = (row.get("user") or row.get("author_steamid") or "").strip()
                            review_text = (row.get("review") or row.get("review_text") or "").strip()
                            
                            if not user or not review_text:
                                continue

                            doc = {
                                "app_id": file_app_id, # On utilise l'ID extrait du nom
                                "user": user,
                                "playtime": float(row.get("playtime") or row.get("author_playtime_forever") or 0),
                                "review_text": review_text,
                                "recommend": row.get("recommend") == "Recommended" or row.get("recommended") == "True",
                                "source_file": csv_filename
                            }

                            batch.append(InsertOne(doc))

                            if len(batch) >= 5000:
                                col.bulk_write(batch, ordered=False)
                                total_inserted += len(batch)
                                batch = []

                if batch:
                    col.bulk_write(batch, ordered=False)
                    total_inserted += len(batch)

        logger.info(f"✅ Terminé : {total_inserted} documents importés.")

    except Exception as e:
        logger.error(f"❌ Erreur : {e}")
# ---------------------------------------------------------------------------
# Users build (from reviews)
# ---------------------------------------------------------------------------

def build_users_from_reviews(db, build_indexes: bool = False):
    """
    Build 'users' collection from 'reviews' using aggregation with $merge.

    Each user document:
      {
        _id: <string>,          # username (primary key, unique)
        name: <string>,         # same as _id (for convenience)
        owned_app_ids: [<int>],
        review_count: <int>
      }

    We merge on _id (MongoDB's primary key), so we rely on the built-in
    unique index on _id and do NOT need a custom unique index for $merge
    to be happy.

    Any additional user indexes respect the build_indexes flag.
    """
    reviews_col = db[REVIEWS_COLLECTION]
    users_col = db[USERS_COLLECTION]

    logger.info(
        "[users] Building users from '%s' into '%s' (merge on _id)...",
        REVIEWS_COLLECTION,
        USERS_COLLECTION,
    )

    prev_count = users_col.estimated_document_count()
    logger.debug("[users] Existing user doc count before build: %d", prev_count)

    pipeline = [
        # Ignore reviews without a user
        {"$match": {"user": {"$ne": None}}},

        # Group by username
        {
            "$group": {
                "_id": "$user",  # username becomes _id
                "owned_app_ids": {"$addToSet": "$app_id"},
                "review_count": {"$sum": 1},
            }
        },

        # Shape final document
        {
            "$project": {
                "_id": "$_id",          # keep _id as username
                "name": "$_id",         # convenience field
                "owned_app_ids": 1,
                "review_count": 1,
            }
        },

        # Merge into 'users' on _id (default when 'on' is omitted)
        {
            "$merge": {
                "into": USERS_COLLECTION,
                # 'on' omitted -> defaults to "_id"
                "whenMatched": "replace",
                "whenNotMatched": "insert",
            }
        },
    ]

    logger.debug("[users] Aggregation pipeline: %r", pipeline)

    # Force pipeline execution
    list(reviews_col.aggregate(pipeline))
    logger.info("[users] Aggregation + merge completed.")

    new_count = users_col.estimated_document_count()
    logger.info(
        "[users] Users collection doc count after build: %d (delta=%d)",
        new_count,
        new_count - prev_count,
    )

    # Optional extra indexes controlled by --build-indexes
    if build_indexes:
        logger.info("[users] Creating optional indexes on 'users' collection...")
        # Example: index on name for queries (doesn't need to be unique now)
        users_col.create_index("name")
        logger.debug("[users] Created index on 'name'")
        logger.info("[users] Optional user indexes ready.")
    else:
        logger.info("[users] Skipping optional user indexes (only _id index is used for merge).")


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def ask_yes_no(question: str, default: bool = False) -> bool:
    """
    Ask a yes/no question on stdin and return True/False.
    default=True -> [Y/n], default=False -> [y/N]
    """
    prompt = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = input(question + prompt).strip().lower()
        logger.debug("[prompt] Question: %r, answer raw: %r", question, answer)

        if not answer:
            logger.debug("[prompt] Using default=%s", default)
            return default
        if answer in ("y", "yes"):
            logger.debug("[prompt] Interpreted 'yes'")
            return True
        if answer in ("n", "no"):
            logger.debug("[prompt] Interpreted 'no'")
            return False
        logger.warning("[prompt] Invalid answer: %r (expected y/n)", answer)
        print("Please answer y or n.")

# ----------------------------------------------------------------------------
# Dataset Downloader
# ----------------------------------------------------------------------------


def _download_file(url: str, dest_path: Path) -> None:
    """
    Download a file from url to dest_path.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("[data] Downloading %s -> %s", url, dest_path)

    # Pretend to be a normal browser (some servers block default Python clients).
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0 Safari/537.36"
            )
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            content_length = resp.getheader("Content-Length")
            if content_length:
                try:
                    size_mb = int(content_length) / (1024 * 1024)
                    logger.info("[data] Remote file size: %.2f MB", size_mb)
                except ValueError:
                    logger.debug("[data] Could not parse Content-Length: %r", content_length)

            with dest_path.open("wb") as f_out:
                shutil.copyfileobj(resp, f_out)

    except HTTPError as e:
        logger.error("[data] HTTP error while downloading %s: %s %s", url, e.code, e.reason)
        if e.code == 403:
            logger.error(
                "[data] Server returned 403 Forbidden.\n"
                "       This usually means the site blocks direct downloads or "
                "requires you to be logged in.\n"
                "       Please download the file manually in your browser and "
                "save it as:\n"
                "         %s",
                dest_path,
            )
        raise
    except URLError as e:
        logger.error("[data] URL error while downloading %s: %s", url, e)
        raise
    except Exception as e:
        logger.exception("[data] Failed to download %s: %s", url, e)
        raise

    logger.info("[data] Download completed: %s", dest_path)

def _extract_reviews_zip_flat(zip_path: Path, dest_dir: Path) -> None:
    """
    Extract only CSV files from a zip into dest_dir, flattening any folders.

    That is, if the ZIP has 'Game Reviews/file1.csv' we end up with:
       dest_dir/file1.csv
    """
    logger.info("[data] Extracting CSVs from %s into %s", zip_path, dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    extracted_count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # Skip directories
            if info.is_dir():
                continue
            # Only care about CSVs
            if not info.filename.lower().endswith(".csv"):
                continue

            filename = Path(info.filename).name  # strip parent folders
            target_path = dest_dir / filename
            logger.debug("[data] Extracting %s -> %s", info.filename, target_path)

            with zf.open(info, "r") as src, target_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted_count += 1

    logger.info("[data] Extracted %d CSV file(s) into %s", extracted_count, dest_dir)

    if extracted_count == 0:
        logger.warning("[data] No CSV files were found in %s", zip_path)

def ensure_games_json_present() -> None:
    """
    Ensure games.json is present in DATA_DIR.
    If missing, download it.
    """
    if GAMES_JSON_PATH.exists() and GAMES_JSON_PATH.stat().st_size > 0:
        logger.info("[data] games.json trouvé dans /tmp")
        return

    logger.info("[data] Téléchargement de games.json depuis Mendeley vers /tmp...")
    DATA_DIR.mkdir(parents=True, exist_ok=True) # Crée /tmp/data
    _download_file(GAMES_JSON_URL, GAMES_JSON_PATH)


def ensure_reviews_present() -> None:
    """
    S'assure que le ZIP des reviews est présent.
    Sur App Runner, on ne décompresse PAS le ZIP sur le disque pour éviter le 'No space left on device'.
    """
    tmp_zip_path = DATA_DIR / "reviews_download.zip"
    
    # Si le ZIP existe déjà, on ne fait rien
    if tmp_zip_path.exists():
        logger.info("[data] ZIP de reviews déjà présent à %s", tmp_zip_path)
        return

    # Sinon, on télécharge le ZIP
    logger.info("[data] Téléchargement du ZIP des reviews depuis Mendeley...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _download_file(REVIEWS_ZIP_URL, tmp_zip_path)

def ensure_data_files_present() -> None:
    """S'assure que les jeux ET les reviews sont sur S3."""
    if not S3_BUCKET:
        logger.warning("[s3] S3_BUCKET non défini. Utilisation du mode local.")
        ensure_games_json_present()
        ensure_reviews_present()
        return

    logger.info(f"[s3] Vérification des fichiers sur le bucket : {S3_BUCKET}")
    # Vérifie et upload sur S3 si absent (pour les deux fichiers)
    ensure_reviews_zip_on_s3(S3_BUCKET, S3_GAMES_KEY, GAMES_JSON_URL)
    ensure_reviews_zip_on_s3(S3_BUCKET, S3_REVIEWS_KEY, REVIEWS_ZIP_URL)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # --- CONFIGURATION & LOGS ---
    parser = argparse.ArgumentParser(description="Import Steam Data")
    parser.add_argument("--build-indexes", action="store_true")
    parser.add_argument("--log-level", default="INFO") # Passer en INFO pour éviter de saturer les logs CloudWatch
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    setup_logging(args.log_level)

    logger.info("[main] Starting import script")

    # --- SÉCURITÉ ANTI-CORRUPTION (IMPORTANT pour App Runner) ---
    # Si games.json fait 0 octet, on le supprime pour forcer le retéléchargement
    if GAMES_JSON_PATH.exists() and GAMES_JSON_PATH.stat().st_size == 0:
        logger.warning("[main] games.json est vide, suppression pour retéléchargement...")
        GAMES_JSON_PATH.unlink()

    ensure_data_files_present() # Vérifie S3 pour les deux fichiers
    
    env = load_env(ENV_PATH)
    db = get_db_from_env(env)
    existing = set(db.list_collection_names())

    # 1. GAMES (Nouveau mode S3 Streaming)
    if GAMES_COLLECTION not in existing:
        if S3_BUCKET:
            import_games_from_s3(db, build_indexes=args.build_indexes)
        else:
            import_games(db, build_indexes=args.build_indexes) # Fallback local
    else:
        logger.info("[games] Collection exists, skipping.")

    import_reviews(db, build_indexes=args.build_indexes)

    # ----------------------------------------------------------------------
    # 3. USERS
    # ----------------------------------------------------------------------
    if USERS_COLLECTION not in set(db.list_collection_names()):
        build_users_from_reviews(db, build_indexes=args.build_indexes)

    logger.info("[main] All done. Nettoyage final...")
    # Optionnel: supprimer games.json à la fin pour libérer encore plus de place
    # GAMES_JSON_PATH.unlink(missing_ok=True)

if __name__ == "__main__":
    main()