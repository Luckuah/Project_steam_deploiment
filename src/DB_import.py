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

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOGGER_NAME = "steam_import"
logger = logging.getLogger(LOGGER_NAME)

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
DATA_DIR = PROJECT_ROOT / "data"
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

def import_games(db, build_indexes: bool = False):
    col = db[GAMES_COLLECTION]
    logger.info("[games] Target collection: %s", GAMES_COLLECTION)

    if not GAMES_JSON_PATH.exists():
        logger.error("[games] JSON file not found: %s", GAMES_JSON_PATH)
        return

    prev_count = col.estimated_document_count()
    logger.debug("[games] Existing document count before import: %d", prev_count)

    games = load_games_array(GAMES_JSON_PATH)
    if not games:
        logger.warning("[games] No documents found in JSON.")
        return

    ops: List[UpdateOne | InsertOne] = []
    for g in games:
        if "_id" in g:
            ops.append(UpdateOne({"_id": g["_id"]}, {"$set": g}, upsert=True))
        else:
            ops.append(InsertOne(g))

    logger.info("[games] Bulk writing %d operations...", len(ops))
    res = col.bulk_write(ops, ordered=False)
    upserted = getattr(res, "upserted_count", 0) or 0
    modified = getattr(res, "modified_count", 0) or 0
    inserted = getattr(res, "inserted_count", 0) or 0
    logger.info(
        "[games] Bulk write done: upserted=%d, modified=%d, inserted=%d",
        upserted,
        modified,
        inserted,
    )

    new_count = col.estimated_document_count()
    logger.debug("[games] Document count after import: %d (delta=%d)", new_count, new_count - prev_count)

    if build_indexes:
        logger.info("[games] Creating indexes (may take time)...")
        col.create_index([("name", "text")])
        logger.debug("[games] Created text index on 'name'")
        col.create_index([("price", ASCENDING)])
        logger.debug("[games] Created index on 'price'")
        logger.info("[games] Indexes ready.")
    else:
        logger.info("[games] Index creation skipped (use --build-indexes to enable).")


# ---------------------------------------------------------------------------
# Reviews import
# ---------------------------------------------------------------------------

def import_reviews(db, build_indexes: bool = False, workers: int = 1):
    col = db[REVIEWS_COLLECTION]
    logger.info("[reviews] Target collection: %s", REVIEWS_COLLECTION)

    reviews_dir = REVIEWS_DIR
    logger.debug("[reviews] Looking for CSVs in: %s", reviews_dir)

    if not reviews_dir.exists():
        logger.error("[reviews] Directory not found: %s", reviews_dir)
        return

    files = sorted(reviews_dir.glob("*.csv"))
    logger.info("[reviews] Found %d CSV file(s)", len(files))

    if not files:
        logger.warning("[reviews] No CSV files found.")
        return

    prev_count = col.estimated_document_count()
    logger.debug("[reviews] Existing document count before import: %d", prev_count)

    def process_file(csv_path: Path) -> int:
        """Import a single CSV file into the reviews collection. Returns inserted count."""
        stem = csv_path.stem  # "<app_id>_<review_Count>"
        try:
            app_id = int(stem.split("_", 1)[0])
        except Exception:
            logger.warning("[reviews] Skip (cannot parse app_id) from file name: %s", csv_path.name)
            return 0

        logger.info("[reviews] Importing %s (app_id=%d)...", csv_path.name, app_id)
        batch: List[InsertOne] = []
        inserted_for_file = 0
        line_count = 0

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            logger.debug("[reviews] CSV header fields for %s: %s", csv_path.name, reader.fieldnames)
            for row in reader:
                line_count += 1

                # user: str
                user = (row.get("user") or "").strip() or None

                # playtime: float
                playtime = None
                raw_playtime = row.get("playtime")
                if raw_playtime not in (None, ""):
                    try:
                        playtime = float(raw_playtime)
                    except ValueError:
                        logger.debug(
                            "[reviews] Invalid playtime %r in file %s line %d",
                            raw_playtime,
                            csv_path.name,
                            line_count + 1,
                        )
                        playtime = None

                # post_date: parse "October 22, 2024"
                post_date = parse_date_mdy_long(row.get("post_date"))

                # helpfulness: int
                helpfulness = None
                raw_help = row.get("helpfulness")
                if raw_help not in (None, ""):
                    try:
                        helpfulness = int(raw_help)
                    except ValueError:
                        logger.debug(
                            "[reviews] Invalid helpfulness %r in file %s line %d",
                            raw_help,
                            csv_path.name,
                            line_count + 1,
                        )
                        helpfulness = None

                # review: str
                review_text = (row.get("review") or "").strip() or None

                # recommend: "Recommended"/"Not Recommended" -> bool
                recommend = coerce_bool_recommend(row.get("recommend"))

                # early_access_review: Null or "Early Access Review" -> bool
                early_access = coerce_bool_early_access(row.get("early_access_review"))

                doc = {
                    "app_id": app_id,
                    "user": user,
                    "playtime": playtime,
                    "post_date": post_date,
                    "helpfulness": helpfulness,
                    "review_text": review_text,
                    "recommend": recommend,
                    "early_access": early_access,
                    "source_file": csv_path.name,
                }
                # strip None values for cleanliness
                doc = {k: v for k, v in doc.items() if v is not None}

                if line_count <= 3:
                    logger.debug(
                        "[reviews] Sample doc from %s line %d: keys=%s",
                        csv_path.name,
                        line_count,
                        list(doc.keys()),
                    )

                batch.append(InsertOne(doc))
                if len(batch) >= BATCH_SIZE:
                    logger.debug("[reviews] Writing batch of %d docs for file %s", len(batch), csv_path.name)
                    try:
                        res = col.bulk_write(batch, ordered=False)
                        inserted_now = getattr(res, "inserted_count", 0) or 0
                        inserted_for_file += inserted_now
                        logger.debug(
                            "[reviews] Batch write for %s: inserted=%d (running total for file=%d)",
                            csv_path.name,
                            inserted_now,
                            inserted_for_file,
                        )
                    except BulkWriteError as bwe:
                        logger.error("[reviews] Bulk write error for %s: %s", csv_path.name, bwe.details)
                    batch = []

        if batch:
            logger.debug("[reviews] Writing final batch of %d docs for file %s", len(batch), csv_path.name)
            try:
                res = col.bulk_write(batch, ordered=False)
                inserted_now = getattr(res, "inserted_count", 0) or 0
                inserted_for_file += inserted_now
                logger.debug(
                    "[reviews] Final batch write for %s: inserted=%d (total for file=%d)",
                    csv_path.name,
                    inserted_now,
                    inserted_for_file,
                )
            except BulkWriteError as bwe:
                logger.error("[reviews] Bulk write error (final batch) for %s: %s", csv_path.name, bwe.details)

        logger.info(
            "[reviews] %s: inserted ≈%d docs (rows read=%d)",
            csv_path.name,
            inserted_for_file,
            line_count,
        )
        return inserted_for_file

    total_inserted = 0

    if workers <= 1 or len(files) == 1:
        logger.info("[reviews] Running single-threaded import (workers=%d, files=%d)", workers, len(files))
        for f in files:
            total_inserted += process_file(f)
    else:
        logger.info(
            "[reviews] Running multi-threaded import with %d workers over %d files",
            workers,
            len(files),
        )
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_file = {executor.submit(process_file, f): f for f in files}
            for future in as_completed(future_to_file):
                f = future_to_file[future]
                try:
                    inserted = future.result()
                    total_inserted += inserted
                except Exception as e:
                    logger.exception("[reviews] Unhandled exception while processing %s: %s", f.name, e)
    col.create_index([("user", ASCENDING), ("app_id", ASCENDING)])
    if build_indexes:
        logger.info("[reviews] Creating indexes (may take time)...")
        col.create_index([("app_id", ASCENDING), ("post_date", DESCENDING)])
        logger.debug("[reviews] Created index on (app_id, post_date DESC)")
        col.create_index([("app_id", ASCENDING), ("recommend", ASCENDING)])
        logger.debug("[reviews] Created index on (app_id, recommend)")
        col.create_index([("review_text", "text")])
        logger.debug("[reviews] Created text index on 'review_text'")
        logger.info("[reviews] Indexes ready.")
    else:
        logger.info("[reviews] Index creation skipped (use --build-indexes to enable).")

    new_count = col.estimated_document_count()
    logger.info(
        "[reviews] Import complete. Total inserted ≈%d, new doc count=%d (delta=%d)",
        total_inserted,
        new_count,
        new_count - prev_count,
    )

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

GAMES_JSON_URL = (
    "https://data.mendeley.com/public-files/datasets/jxy85cr3th/files/"
    "9fa9989d-d4f4-426a-aad3-fa9a96700332/file_downloaded"
)
REVIEWS_ZIP_URL = (
    "https://data.mendeley.com/public-files/datasets/jxy85cr3th/files/"
    "273898e9-90f1-49ff-8d62-df52e67341b3/file_downloaded"
)

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
    if GAMES_JSON_PATH.exists():
        logger.info("[data] Found games JSON at %s", GAMES_JSON_PATH)
        return

    logger.warning("[data] games.json not found at %s", GAMES_JSON_PATH)
    logger.info("[data] Attempting to download games JSON from Mendeley...")
    _download_file(GAMES_JSON_URL, GAMES_JSON_PATH)
    logger.info("[data] games.json is now available at %s", GAMES_JSON_PATH)
def ensure_reviews_present() -> None:
    """
    Ensure review CSVs are present in REVIEWS_DIR.
    If no CSVs are found, download the ZIP and extract them flat into REVIEWS_DIR.
    """
    if REVIEWS_DIR.exists():
        csv_files = list(REVIEWS_DIR.glob("*.csv"))
        if csv_files:
            logger.info(
                "[data] Found %d review CSV file(s) in %s",
                len(csv_files),
                REVIEWS_DIR,
            )
            return
        else:
            logger.warning("[data] 'Game Reviews' directory exists but contains no CSV files.")
    else:
        logger.warning("[data] Reviews directory not found: %s", REVIEWS_DIR)

    # Need to download + extract
    logger.info("[data] Attempting to download review ZIP from Mendeley...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip_path = DATA_DIR / "reviews_download.zip"

    _download_file(REVIEWS_ZIP_URL, tmp_zip_path)
    _extract_reviews_zip_flat(tmp_zip_path, REVIEWS_DIR)

    # Optional: clean up ZIP after successful extraction
    try:
        tmp_zip_path.unlink()
        logger.debug("[data] Removed temporary ZIP file %s", tmp_zip_path)
    except FileNotFoundError:
        pass
def ensure_data_files_present() -> None:
    """
    Ensure both games.json and review CSVs exist.
    Download / extract them if missing.
    """
    logger.info("[data] Checking presence of required data files...")
    ensure_games_json_present()
    ensure_reviews_present()
    logger.info("[data] Data files check complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Import games, reviews and build users into MongoDB (with Rich logging)."
    )
    parser.add_argument(
        "--build-indexes",
        action="store_true",
        help="Create indexes on collections (can be slow on large datasets).",
    )
    parser.add_argument(
        "--log-level",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: DEBUG).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker threads for reviews import (default: 1).",
    )
    args = parser.parse_args()
    logger.info("[main] Parsed arguments: %r", args)

    setup_logging(args.log_level)

    logger.info("[main] Starting import script")
    logger.debug("[main] Arguments: build_indexes=%s, log_level=%s", args.build_indexes, args.log_level)

    ensure_data_files_present()
    env = load_env(ENV_PATH)
    db = get_db_from_env(env)

    logger.debug("[main] Available collections before import: %s", db.list_collection_names())

    # ----------------------------------------------------------------------
    # Games collection
    # ----------------------------------------------------------------------
    existing = set(db.list_collection_names())
    if GAMES_COLLECTION in existing:
        logger.info("[games] Collection '%s' already exists.", GAMES_COLLECTION)
        if ask_yes_no(f"[games] Collection '{GAMES_COLLECTION}' already exists. Drop and re-import?", default=False):
            logger.info("[games] Dropping collection '%s'...", GAMES_COLLECTION)
            db.drop_collection(GAMES_COLLECTION)
            import_games(db, build_indexes=args.build_indexes)
        else:
            logger.info("[games] Skipping import; collection '%s' left unchanged.", GAMES_COLLECTION)
    else:
        logger.info("[games] Collection '%s' does not exist; importing...", GAMES_COLLECTION)
        import_games(db, build_indexes=args.build_indexes)

    # ----------------------------------------------------------------------
    # Reviews collection
    # ----------------------------------------------------------------------
    existing = set(db.list_collection_names())
    if REVIEWS_COLLECTION in existing:
        logger.info("[reviews] Collection '%s' already exists.", REVIEWS_COLLECTION)
        if ask_yes_no(f"[reviews] Collection '{REVIEWS_COLLECTION}' already exists. Drop and re-import?", default=False):
            logger.info("[reviews] Dropping collection '%s'...", REVIEWS_COLLECTION)
            db.drop_collection(REVIEWS_COLLECTION)
            import_reviews(db, build_indexes=args.build_indexes,workers=args.workers)
        else:
            logger.info("[reviews] Skipping import; collection '%s' left unchanged.", REVIEWS_COLLECTION)
    else:
        logger.info("[reviews] Collection '%s' does not exist; importing...", REVIEWS_COLLECTION)
        import_reviews(db, build_indexes=args.build_indexes,workers=args.workers)

    # ----------------------------------------------------------------------
    # Users collection (built from reviews)
    # ----------------------------------------------------------------------
    existing = set(db.list_collection_names())
    reviews_exists = REVIEWS_COLLECTION in existing

    if not reviews_exists:
        logger.error("[users] Cannot build 'users': '%s' collection does not exist.", REVIEWS_COLLECTION)
    else:
        if USERS_COLLECTION in existing:
            logger.info("[users] Collection '%s' already exists.", USERS_COLLECTION)
            if ask_yes_no(
                f"[users] Collection '{USERS_COLLECTION}' already exists. Drop and rebuild from '{REVIEWS_COLLECTION}'?",
                default=False,
            ):
                logger.info("[users] Dropping collection '%s'...", USERS_COLLECTION)
                db.drop_collection(USERS_COLLECTION)
                build_users_from_reviews(db, build_indexes=args.build_indexes)
            else:
                logger.info("[users] Skipping rebuild; collection '%s' left unchanged.", USERS_COLLECTION)
        else:
            logger.info("[users] Collection '%s' does not exist; building from '%s'...", USERS_COLLECTION, REVIEWS_COLLECTION)
            build_users_from_reviews(db, build_indexes=args.build_indexes)

    logger.debug("[main] Final collections: %s", db.list_collection_names())
    logger.info("[main] All done.")


if __name__ == "__main__":
    main()
