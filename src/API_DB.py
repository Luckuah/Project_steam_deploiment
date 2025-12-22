import sys
from pathlib import Path
SRC = Path(__file__).resolve().parents[1] / "src/NLGCL"  # ...\src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from fastapi import FastAPI,Body,HTTPException
from pydantic import BaseModel,constr,Field
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, PyMongoError,DuplicateKeyError
from bson import json_util
from typing import Any,List, Dict,Optional
import json
import time
import httpx
from urllib.parse import urlencode, quote
import logging
from logging.config import dictConfig
from rich.logging import RichHandler
from rich.traceback import install as rich_traceback_install
from rich import pretty as rich_pretty
from datetime import datetime
import numpy as np
import traceback
import os

def normalize_path(path: str) -> str:
    """
    If running on Linux, convert Windows-style backslashes to forward slashes.
    Otherwise, return the path unchanged.
    """
    if os.name == "posix":  # Linux, macOS, etc.
        return path.replace("\\", "/")
    return path

from NLGCL.recomendation_NLGCL import setup_recbole_model,recommend_topk
from GenSar.recommender_service import recommender
recommender.load()
rich_pretty.install()
rich_traceback_install(show_locals=False)
dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # Let RichHandler render; keep format minimal
        "rich": {
            "format": "%(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "rich_console": {
            "class": "rich.logging.RichHandler",
            "formatter": "rich",
            "level": "INFO",
            # RichHandler kwargs:
            "rich_tracebacks": True,
            "markup": True,          # allow [bold], [green], etc. in messages
            "show_path": True,       # show module:line
            "enable_link_path": True # clickable paths in some terminals
        },
    },
    "loggers": {
        # Root logger (your app)
        "": {"handlers": ["rich_console"], "level": "INFO"},
        # Make uvicorn logs go through Rich too
        "uvicorn":         {"handlers": ["rich_console"], "level": "INFO", "propagate": False},
        "uvicorn.error":   {"handlers": ["rich_console"], "level": "INFO", "propagate": False},
        "uvicorn.access":  {"handlers": ["rich_console"], "level": "INFO", "propagate": False},
    },
})
logger = logging.getLogger(__name__)
env_vars = {
    k.strip(): v.strip()
    for k, v in (
        line.split("=", 1)
        for line in Path(".env").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
}

# ---------- MongoDB CONFIG ----------
username = env_vars.get("DB_USER", "user")
password = env_vars.get("DB_PASSWORD", "pass")
db_ip = env_vars.get("DB_IP", "localhost")
db_port = env_vars.get("DB_PORT", "27017")
db_name = env_vars.get("DB_NAME", "Steam_Project")
uri = f"mongodb://{username}:{password}@{db_ip}:{db_port}/?authSource=admin"

# Short timeout so we don't block forever if Mongo is down
client = MongoClient(uri, serverSelectionTimeoutMS=2000)
db = client[db_name]

#Load the model
try:
    model_path = normalize_path("NLGCL\\saved\\NLGCL-Dec-02-2025_17-09-34.pth")
    config_file_list = [normalize_path("NLGCL\\properties\\game.yaml")]
    print(model_path,config_file_list)
    NLGCL_model, NLGCL_dataset, NLGCL_train_data, NLGCL_device = setup_recbole_model(
        model_path=model_path,
        dataset_name="game",
        config_file_list=config_file_list
    )
except Exception as e:
    print(f"\n--- ERREUR --- \nImpossible de charger les composants Recbole: {e}")
    traceback.print_exc()

# ---------- FASTAPI APP ----------

app = FastAPI()

class CommandRequest(BaseModel):
    command: dict  # raw MongoDB command as a JSON object
class ApiResponse(BaseModel):
    message: Any
    Status: bool
NameStr = constr(strip_whitespace=True, min_length=1, max_length=64)
class UserCreate(BaseModel):
    name: NameStr
class UserDelete(BaseModel):
    name: NameStr
class UserRename(BaseModel):
    old_name: NameStr
    new_name: NameStr
class GameSearchRequest(BaseModel):
    limit: int = Field(10, ge=1, le=200)

    max_price: Optional[float] = None
    name_contains: Optional[str] = None

    categories: Optional[List[str]] = None
    genres: Optional[List[str]] = None

    min_negative: Optional[int] = None
    max_negative: Optional[int] = None
    min_positive: Optional[int] = None
    max_positive: Optional[int] = None

    release_date_from: Optional[datetime] = None
    release_date_to: Optional[datetime] = None

    min_required_age: Optional[int] = None
    max_required_age: Optional[int] = None

    required_tags: Optional[List[str]] = None 
class ReviewSearchRequest(BaseModel):
    app_id: int
    limit: int = Field(10, ge=1, le=200)

    min_playtime: Optional[float] = None
    min_helpfulness: Optional[int] = None

    post_date_from: Optional[datetime] = None
    post_date_to: Optional[datetime] = None

    recommended: Optional[bool] = None
    early_access: Optional[bool] = None

    username: Optional[str] = None
class GamesRequest(BaseModel):
    appids: List[int]
class RecommendRequest(BaseModel):
    username: str
    top_k: int = 5
    max_history: int = 20
class Recommendation(BaseModel):
    game_id: str
    name: str
    game_idx: int
    hamming_dist: int
class RecommendResponse(BaseModel):
    username: str
    recommendations: List[Recommendation]
class RecommendRequest_genral(BaseModel):
    username: str
    top_k_Gensar: int = 12
    top_k_NLGCL: int = 200
    max_history: int = 20
    verbose: bool = False


def is_mongo_up() -> tuple[bool, str | None]:
    """
    Check if MongoDB is reachable.
    Returns (ok, error_message).
    """
    try:
        client.admin.command("ping")
        return True, None
    except ServerSelectionTimeoutError as e:
        return False, f"Cannot reach MongoDB (timeout): {e}"
    except PyMongoError as e:
        return False, f"MongoDB error: {e}"
    except Exception as e:
        return False, f"Unexpected error while pinging MongoDB: {e}"

GETITEMS_URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1"  # no trailing slash
CDN_BASE = "https://shared.steamstatic.com/store_item_assets/"

def _chunked(seq: List[int], n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]
def _build_url(fmt: str, v: str) -> str:
    """Turn an asset filename into a full CDN URL using asset_url_format."""
    if not isinstance(v, str) or not v:
        return ""
    if v.startswith("http://") or v.startswith("https://"):
        return v
    # if it's clearly a filename/path, resolve via the format; else leave as-is
    if "${FILENAME}" in fmt and ("/" in v or "." in v):
        return CDN_BASE + fmt.replace("${FILENAME}", v)
    if "/" in v or "." in v:
        return CDN_BASE + v
    # e.g., bare hashes like community_icon -> leave as the raw value
    return v
def _extract_items(obj: Dict[str, Any]) -> list[dict]:
    resp = obj.get("response", {}) if isinstance(obj, dict) else {}
    items = resp.get("store_items")
    if isinstance(items, list):
        return items
    # legacy fallback
    items = resp.get("items")
    return items if isinstance(items, list) else []
def _extract_appid(item: Dict[str, Any]) -> int | None:
    if isinstance(item.get("appid"), int):
        return item["appid"]
    if isinstance(item.get("id"), dict) and isinstance(item["id"].get("appid"), int):
        return item["id"]["appid"]
    if isinstance(item.get("id"), int):
        return item["id"]
    return None
def _extract_assets(item: Dict[str, Any]) -> Dict[str, Any] | None:
    a = item.get("assets")
    if isinstance(a, dict):
        return a
    inner = item.get("item")
    if isinstance(inner, dict) and isinstance(inner.get("assets"), dict):
        return inner["assets"]
    return None
def _call_getitems(client: httpx.Client, payload: dict) -> dict:
    # Try POST (form-encoded) first
    r = client.post(
        GETITEMS_URL,
        data={"input_json": json.dumps(payload)},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "assets-fetcher/1.0",
        },
    )
    if r.status_code == 200:
        return r.json()
    # Fallback to GET with URL-encoded input_json
    q = urlencode({"input_json": json.dumps(payload)})
    r = client.get(f"{GETITEMS_URL}?{q}", headers={"User-Agent": "assets-fetcher/1.0"})
    r.raise_for_status()
    return r.json()
def fetch_assets_for_appids(
    appids: List[int],
    country: str = "US",
    language: str = "english",
    batch_size: int = 100,
    timeout: float = 15.0,
    sleep_between_batches: float = 0.1,
) -> Dict[int, Dict[str, str]]:
    by_app: Dict[int, Dict[str, str]] = {}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for group in _chunked(appids, batch_size):
            payload = {
                "ids": [{"appid": a} for a in group],
                "context": {"country_code": country, "language": language},
                "data_request": {"include_assets": True},
            }
            raw = _call_getitems(client, payload)
            items = _extract_items(raw)

            for it in items:
                appid = _extract_appid(it)
                assets = _extract_assets(it)
                if appid is None or not isinstance(assets, dict):
                    continue

                fmt = assets.get("asset_url_format", "")
                urls: Dict[str, str] = {}
                for k, v in assets.items():
                    if k == "asset_url_format":
                        continue
                    if isinstance(v, str) and v:
                        u = _build_url(fmt, v)
                        if u:
                            urls[k] = u
                by_app[appid] = urls

            if sleep_between_batches:
                time.sleep(sleep_between_batches)

    # Return in the exact same order as input; missing apps -> {}
    return {appid: by_app.get(appid, {}) for appid in appids}

@app.get("/recommandation", response_model=ApiResponse)
def recommandation():
    """
    Run a MongoDB command sent by the client and return our wrapped JSON:
    {
      "message": <mongo_result or error>,
      "Status": true/false
    }
    """
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    try:
        # Example: { "ping": 1 } or { "serverStatus": 1 }
        result = db.games.find({},{}).sort({ "positive": -1, "_id": 1 }).limit(200)
        missing_asset = []
        result = [game for game in result]
        for game in result:
            if "assets" not in game or not game["assets"]:
                missing_asset.append(game["_id"])
        if missing_asset:
            logger.info(f"Fetching assets for missing appids: {missing_asset}")
            assets = fetch_assets_for_appids(missing_asset)
            for game in result:
                appid = game["_id"]
                if appid in assets:
                    game["assets"] = assets[appid]
                    db.games.update_one(
                        {"_id": appid},
                        {"$set": {"assets": assets[appid]}}
                    )
        
        return ApiResponse(message=result, Status=True)

    except Exception as e:
        # No HTTPException: we always return our own JSON envelope
        return ApiResponse(message=f"Error executing command: {e}", Status=False)

@app.post("/Game", response_model=ApiResponse)
def get_Game(game_id: int):
    """
    Run a MongoDB command sent by the client and return our wrapped JSON:
    {
      "message": <mongo_result or error>,
      "Status": true/false
    }
    """
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    try:
        result = db.games.find_one({"_id": game_id})
        if "assets" not in result or not result["assets"]:
            assets = fetch_assets_for_appids([result["_id"]])
            result["assets"] = assets[result["_id"]]
            db.games.update_one(
                {"_id": result["_id"]},
                {"$set": {"assets": assets[result["_id"]]}}
            )
        
        return ApiResponse(message=result, Status=True)

    except Exception as e:
        # No HTTPException: we always return our own JSON envelope
        return ApiResponse(message=f"Error executing command: {e}", Status=False)

@app.post("/Games", response_model=ApiResponse)
def get_Games_list(payload: GamesRequest):
    """
    Fetch information for a list of games by their app IDs.
    For any game missing 'assets', fetch them in batch (like /recommandation)
    and update the database.
    """
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    try:
        game_ids = payload.appids or []

        if not game_ids:
            # Nothing to fetch, return empty list
            return ApiResponse(message=[], Status=True)

        # Find all games matching the list of IDs
        cursor = db.games.find({"_id": {"$in": game_ids}}, {})
        result = [game for game in cursor]

        # Detect games missing assets
        missing_asset = []
        for game in result:
            if "assets" not in game or not game["assets"]:
                missing_asset.append(game["_id"])

        # Batch fetch assets for all missing appids (same logic as /recommandation)
        if missing_asset:
            logger.info(f"Fetching assets for missing appids: {missing_asset}")
            assets = fetch_assets_for_appids(missing_asset)
            print(assets.keys())
            for game in result:
                appid = game["_id"]
                if appid in assets:
                    game["assets"] = assets[appid]
                    db.games.update_one(
                        {"_id": appid},
                        {"$set": {"assets": assets[appid]}}
                    )

        return ApiResponse(message=result, Status=True)

    except Exception as e:
        return ApiResponse(message=f"Error executing command: {e}", Status=False)

@app.post("/user", response_model=ApiResponse)
def create_user(payload: UserCreate):
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    name = payload.name
    doc = {"name": name, "created_at": datetime.utcnow()}

    try:
        res = db.users.insert_one(doc)
        out = {"_id": str(res.inserted_id), "name": name}
        return ApiResponse(message=out, Status=True)
    except DuplicateKeyError:
        return ApiResponse(message=f"User '{name}' already exists.", Status=False)
    except Exception as e:
        return ApiResponse(message=f"Error creating user: {e}", Status=False)
@app.delete("/user", response_model=ApiResponse)
def delete_user(payload: UserDelete):
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    name = payload.name
    try:
        res = db.users.delete_one({"name": name})
        if res.deleted_count == 0:
            return ApiResponse(message=f"User '{name}' not found.", Status=False)
        return ApiResponse(message=f"User '{name}' deleted.", Status=True)
    except Exception as e:
        return ApiResponse(message=f"Error deleting user: {e}", Status=False)
    
@app.patch("/user", response_model=ApiResponse)
def rename_user(payload: UserRename):
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    if payload.old_name == payload.new_name:
        return ApiResponse(message="Old and new names are identical.", Status=False)

    try:
        res = db.users.update_one(
            {"name": payload.old_name},
            {"$set": {"name": payload.new_name, "updated_at": datetime.utcnow()}}
        )
        if res.matched_count == 0:
            return ApiResponse(message=f"User '{payload.old_name}' not found.", Status=False)
        # If unique index exists, DuplicateKeyError would have been raised before matched_count>0,
        # but in some race cases it can be thrown—handle it explicitly above if needed.
        return ApiResponse(
            message=f"User '{payload.old_name}' renamed to '{payload.new_name}'.",
            Status=True
        )
    except DuplicateKeyError:
        return ApiResponse(
            message=f"User '{payload.new_name}' already exists.",
            Status=False
        )
    except Exception as e:
        return ApiResponse(message=f"Error renaming user: {e}", Status=False)
@app.get("/user", response_model=ApiResponse)
def get_user(name: NameStr):
    """
    Fetch a user document by name.
    Returns { "message": <user_doc>, "Status": true } when found,
    else { "message": "...not found", "Status": false }.
    """
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    try:
        doc = db.users.find_one({"name": name})
        if not doc:
            return ApiResponse(message=f"User '{name}' not found.", Status=False)

        # Convert ObjectId to str for JSON-compat
        doc["_id"] = str(doc["_id"])
        return ApiResponse(message=doc, Status=True)

    except Exception as e:
        return ApiResponse(message=f"Error fetching user: {e}", Status=False)
@app.put("/user", response_model=ApiResponse)
def update_user_object(user: Dict[str, Any] = Body(...)):
    """
    Update an existing user document using the JSON body as the new data.
    The 'name' field is treated as the unique ID.
    - If user with that name exists -> it's updated.
    - If not -> return error (no user is created).
    """
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    name = user.get("name")
    if not name:
        return ApiResponse(message="Field 'name' is required in the user object.", Status=False)

    user["updated_at"] = datetime.now()

    res = db.users.update_one({"name": name}, {"$set": user}, upsert=False)

    if res.matched_count == 0:
        return ApiResponse(message=f"User '{name}' not found.", Status=False)

    doc = db.users.find_one({"name": name})
    if not doc:
        return ApiResponse(message=f"User '{name}' not found after update.", Status=False)

    doc["_id"] = str(doc["_id"])
    return ApiResponse(message=doc, Status=True)
@app.get("/health", response_model=ApiResponse)

def serialize_game(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    # ObjectId -> str
    if "_id" in out:
        out["_id"] = str(out["_id"])

    # convert datetimes to isoformat
    for key in ("release_date", "created_at", "updated_at"):
        if key in out and isinstance(out[key], datetime):
            out[key] = out[key].isoformat()

    return out
@app.post("/games/search", response_model=ApiResponse)
def search_games(payload: GameSearchRequest):
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    query: Dict[str, Any] = {}

    # --- price ---
    if payload.max_price is not None:
        query["price"] = {"$lte": payload.max_price}

    # --- name substring (case-insensitive) ---
    if payload.name_contains:
        query["name"] = {"$regex": payload.name_contains, "$options": "i"}

    # --- categories (array) ---
    if payload.categories:
        query["categories"] = {"$all": payload.categories}

    # --- genres (array) ---
    if payload.genres:
        query["genres"] = {"$all": payload.genres}

    # --- negative reviews ---
    if payload.min_negative is not None or payload.max_negative is not None:
        neg_range: Dict[str, Any] = {}
        if payload.min_negative is not None:
            neg_range["$gte"] = payload.min_negative
        if payload.max_negative is not None:
            neg_range["$lte"] = payload.max_negative
        if neg_range:
            query["negative"] = neg_range

    # --- positive reviews ---
    if payload.min_positive is not None or payload.max_positive is not None:
        pos_range: Dict[str, Any] = {}
        if payload.min_positive is not None:
            pos_range["$gte"] = payload.min_positive
        if payload.max_positive is not None:
            pos_range["$lte"] = payload.max_positive
        if pos_range:
            query["positive"] = pos_range

    # --- release date range ---
    if payload.release_date_from is not None or payload.release_date_to is not None:
        date_range: Dict[str, Any] = {}
        if payload.release_date_from is not None:
            date_range["$gte"] = payload.release_date_from
        if payload.release_date_to is not None:
            date_range["$lte"] = payload.release_date_to
        if date_range:
            query["release_date"] = date_range

    # --- age requirement ---
    if payload.min_required_age is not None or payload.max_required_age is not None:
        age_range: Dict[str, Any] = {}
        if payload.min_required_age is not None:
            age_range["$gte"] = payload.min_required_age
        if payload.max_required_age is not None:
            age_range["$lte"] = payload.max_required_age
        if age_range:
            query["required_age"] = age_range

    # --- required tags: tags.<tag> must exist ---
    if payload.required_tags:
        for tag in payload.required_tags:
            query[f"tags.{tag}"] = {"$exists": True}

    try:
        cursor = (
            db.games
            .find(query)
            .sort("positive", -1)
            .limit(payload.limit)
        )

        # Materialize the cursor so we can inspect/update docs
        games = [doc for doc in cursor]

        # ---- detect games missing assets ----
        missing_asset = []
        for game in games:
            if "assets" not in game or not game["assets"]:
                missing_asset.append(game["_id"])

        # ---- batch fetch assets for missing appids (same logic as /Games) ----
        if missing_asset:
            logger.info(f"[search_games] Fetching assets for missing appids: {missing_asset}")
            assets = fetch_assets_for_appids(missing_asset)

            for game in games:
                appid = game["_id"]
                if appid in assets:
                    game["assets"] = assets[appid]
                    db.games.update_one(
                        {"_id": appid},
                        {"$set": {"assets": assets[appid]}}
                    )

        # Now serialize with assets included
        docs = [serialize_game(game) for game in games]

        result = {
            "count": len(docs),
            "games": docs,
        }
        return ApiResponse(message=result, Status=True)

    except Exception as e:
        return ApiResponse(message=f"Error searching games: {e}", Status=False)

def serialize_review(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    if "post_date" in out and isinstance(out["post_date"], datetime):
        out["post_date"] = out["post_date"].isoformat()
    return out
@app.post("/reviews/search", response_model=ApiResponse)
def search_reviews(payload: ReviewSearchRequest):
    """
    Search reviews for a given app_id with optional filters.
    """
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    query: Dict[str, Any] = {"app_id": payload.app_id}

    # min playtime
    if payload.min_playtime is not None:
        query["playtime"] = {"$gte": payload.min_playtime}

    # min helpfulness
    if payload.min_helpfulness is not None:
        query["helpfulness"] = {"$gte": payload.min_helpfulness}

    # post_date range
    if payload.post_date_from is not None or payload.post_date_to is not None:
        date_range: Dict[str, Any] = {}
        if payload.post_date_from is not None:
            date_range["$gte"] = payload.post_date_from
        if payload.post_date_to is not None:
            date_range["$lte"] = payload.post_date_to
        if date_range:
            query["post_date"] = date_range

    # recommended
    if payload.recommended is not None:
        query["recommend"] = payload.recommended

    # early access
    if payload.early_access is not None:
        query["early_access"] = payload.early_access

    # username (case-insensitive)
    if payload.username:
        query["user"] = {"$regex": payload.username, "$options": "i"}

    try:
        cursor = (
            db.reviews
            .find(query)
            .sort([("helpfulness", -1), ("post_date", -1)])
            .limit(payload.limit)
        )

        docs = [serialize_review(doc) for doc in cursor]
        result = {
            "count": len(docs),
            "reviews": docs,
        }
        return ApiResponse(message=result, Status=True)

    except Exception as e:
        return ApiResponse(message=f"Error searching reviews: {e}", Status=False)
@app.get("/UniqueTagsCategories", response_model=ApiResponse)
def get_unique_tags_categories():
    """
    Return all unique tag keys and all unique categories.

    Response message:
    {
        "tags": [...],        # list[str]
        "categories": [...]   # list[str]
    }
    """
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    try:
        # ----- Unique tags (keys of the "tags" dict) -----
        unique_tags = set()

        cursor = db.games.find(
            {"tags": {"$exists": True}},
            {"tags": 1, "_id": 0}
        )

        for doc in cursor:
            tags_field = doc.get("tags")
            if isinstance(tags_field, dict):
                unique_tags.update(tags_field.keys())

        tags_list = sorted(unique_tags)

        # ----- Unique categories (array of strings) -----
        categories_list = db.games.distinct("categories")
        categories_list = sorted(categories_list)

        payload = {
            "tags": tags_list,
            "categories": categories_list,
        }

        return ApiResponse(message=payload, Status=True)

    except Exception as e:
        return ApiResponse(message=f"Error collecting tags/categories: {e}", Status=False)

def health():
    """
    Health check endpoint using the same JSON envelope.
    """
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    return ApiResponse(
        message={"fastapi": "ok", "mongodb": "ok"},
        Status=True
    )


class RecommendationRequest(BaseModel):
    user_id: str
    topk: int = 30

@app.post("/recomandation/NLGCL", response_model=ApiResponse)
def make_recomandation(request: RecommendationRequest):
    ok, err = is_mongo_up()
    if not ok:
        return ApiResponse(message=err, Status=False)

    try:
        pass
        # 1) Get recommendation appids from NLGCL
        recomandation = recommend_topk(
            model=NLGCL_model, 
            dataset=NLGCL_dataset, 
            train_data=NLGCL_train_data, 
            user_id=request.user_id,
            topk=request.topk,
            device=NLGCL_device
        )

        appids = [int(x) for x in recomandation]

        # 2) Re-use existing /Games logic via its core function
        games_request = GamesRequest(appids=appids)
        # get_Games_list already returns an ApiResponse
        games_response: ApiResponse = get_Games_list(games_request)

        # Just return that ApiResponse directly
        return games_response

    except Exception as e:
        logger.exception("Error in /recomandation/NLGCL")
        return ApiResponse(message=f"Error in recommendation: {e}", Status=False)

@app.post("/recomandation/GenSar", response_model=ApiResponse)
def recommend_games(req: RecommendRequest):
    try:
        recs = recommender.recommend_for_user(
            username=req.username,
            top_k=req.top_k,
            max_history=req.max_history,
        )
        # recs is already a list[dict]; FastAPI + Pydantic will coerce to Recommendation
        return ApiResponse(message=recs, Status=True)
    except ValueError as e:
        # e.g., unknown user or no history
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal GenSAR error")

  
