import os
import json
import time
import math
import numpy as np
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple
from collections import defaultdict
from datetime import datetime

from pymongo import MongoClient

import torch
from transformers import AutoTokenizer, AutoModel

import logging
from rich.logging import RichHandler
from dotenv import load_dotenv


# ==============================================================
# 0. LOAD .env + LOGGING SETUP
# ==============================================================

load_dotenv()  # Load .env file in current directory

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)

logger = logging.getLogger("gensar_preprocess")

logger.info(f"[green]Logging initialized[/green] at level: {LOG_LEVEL}")
logger.info("[green].env variables loaded[/green] (if present)")


# ==============================================================
# 1. BUILD MONGO URI FROM .env
# ==============================================================

def build_mongo_uri() -> str:
    missing = []
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_ip = os.getenv("DB_IP")
    db_port = os.getenv("DB_PORT")

    if not db_user:
        missing.append("DB_USER")
    if not db_password:
        missing.append("DB_PASSWORD")
    if not db_ip:
        missing.append("DB_IP")
    if not db_port:
        missing.append("DB_PORT")

    if missing:
        logger.critical(
            "[bold red]Missing configuration keys in .env:[/bold red] "
            + ", ".join(missing)
        )
        raise RuntimeError(f"Missing .env keys: {missing}")

    uri = f"mongodb://{db_user}:{db_password}@{db_ip}:{db_port}/?authSource=admin"
    logger.info(
        f"[green]Mongo URI built[/green] (redacted creds) -> "
        f"host={db_ip} port={db_port}"
    )
    return uri


DB_NAME = os.getenv("DB_NAME", "Steam_Project")


# ==============================================================
# 2. DATA CLASSES
# ==============================================================

@dataclass
class Game:
    game_id: str
    name: str
    text: str


# ==============================================================
# 3. MONGO LOADING
# ==============================================================

def load_raw_games(mongo_uri: str):
    logger.info("[bold blue]Connecting to MongoDB for games...[/bold blue]")
    client = MongoClient(mongo_uri)
    db = client[DB_NAME]

    est_count = db.games.estimated_document_count()
    logger.info(f"[yellow]games.estimated_document_count()[/yellow] = {est_count}")

    t0 = time.time()
    games_cur = db.games.find()
    games = list(games_cur)
    dt = time.time() - t0

    logger.info(
        f"[green]Loaded[/green] {len(games)} raw game documents "
        f"in {dt:.1f}s (est={est_count})"
    )
    return games


def load_raw_reviews(mongo_uri: str):
    logger.info("[bold blue]Connecting to MongoDB for reviews...[/bold blue]")
    client = MongoClient(mongo_uri)
    db = client[DB_NAME]

    est_count = db.reviews.estimated_document_count()
    logger.info(f"[yellow]reviews.estimated_document_count()[/yellow] = {est_count}")

    t0 = time.time()
    reviews_cur = db.reviews.find()
    reviews = list(reviews_cur)
    dt = time.time() - t0

    logger.info(
        f"[green]Loaded[/green] {len(reviews)} raw review documents "
        f"in {dt:.1f}s (est={est_count})"
    )
    return reviews


# ==============================================================
# 4. BUILD GAME TEXT
# ==============================================================

def build_game_text(doc: dict) -> str:
    name = doc.get("name", "")
    short_desc = doc.get("short_description", "")
    about = doc.get("about_the_game", "") or doc.get("detailed_description", "")

    genres = doc.get("genres", []) or []
    categories = doc.get("categories", []) or []
    langs = doc.get("supported_languages", []) or []
    tags_obj = doc.get("tags", {}) or {}

    sorted_tags = sorted(tags_obj.items(), key=lambda kv: kv[1], reverse=True)
    top_tags = [t for t, _ in sorted_tags[:10]]

    parts = []

    if name:
        parts.append(name + ".")
    if short_desc:
        parts.append(short_desc)
    if about:
        parts.append("About: " + about)

    if genres:
        parts.append("Genres: " + ", ".join(genres) + ".")
    if categories:
        parts.append("Categories: " + ", ".join(categories) + ".")
    if top_tags:
        parts.append("Tags: " + ", ".join(top_tags) + ".")
    if langs:
        parts.append("Languages: " + ", ".join(langs) + ".")

    text = " ".join(parts)
    return text[:4000]


def preprocess_games(raw_games: List[dict]):
    logger.info("[bold blue]Preprocessing games...[/bold blue]")
    games: List[Game] = []
    game2idx: Dict[str, int] = {}
    idx2game: List[str] = []

    skipped = 0
    total = len(raw_games)
    t0 = time.time()

    for i, doc in enumerate(raw_games):
        try:
            game_id = str(doc["_id"]).strip()  # Steam ID
        except KeyError:
            skipped += 1
            continue

        name = doc.get("name", f"game_{game_id}")
        text = build_game_text(doc)

        idx = len(idx2game)
        game2idx[game_id] = idx
        idx2game.append(game_id)
        games.append(Game(game_id=game_id, name=name, text=text))

        if (i + 1) % 10000 == 0 or (i + 1) == total:
            elapsed = time.time() - t0
            processed = i + 1
            rate = processed / elapsed if elapsed > 0 else 0.0
            remaining = total - processed
            eta = remaining / rate if rate > 0 else 0.0
            logger.info(
                f"[cyan]Games processed[/cyan]: {processed}/{total} "
                f"({processed/total:.1%}) | "
                f"elapsed={elapsed/60:.1f}m, rate={rate:,.1f} docs/s, "
                f"ETA={eta/60:.1f}m"
            )

    logger.info(
        f"[green]Games preprocessed[/green]: {len(games)} kept, "
        f"{skipped} skipped (missing _id). "
        f"Total time={ (time.time()-t0)/60:.1f}m"
    )
    logger.debug(f"Example game: {games[0] if games else 'NONE'}")
    return games, game2idx, idx2game


# ==============================================================
# 5. USER HISTORIES
# ==============================================================

def parse_ts(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(v)
        except Exception:
            return None
    return None


def preprocess_user_histories(
    raw_reviews,
    game2idx: Dict[str, int],
    min_playtime_hours: float = 0.3,
    only_positive: bool = False,
):
    logger.info("[bold blue]Building user histories from reviews...[/bold blue]")

    tmp: Dict[str, List[Tuple[datetime, int]]] = defaultdict(list)

    skipped_no_game = 0
    skipped_short_playtime = 0
    skipped_ts = 0

    total = len(raw_reviews)
    t0 = time.time()
    log_every = 200_000  # adjust if you want more/less logging

    for i, r in enumerate(raw_reviews):
        user = r.get("user")
        gid_raw = r.get("app_id")
        if user is None or gid_raw is None:
            continue

        gid = str(gid_raw)
        if gid not in game2idx:
            skipped_no_game += 1
            continue

        playtime = float(r.get("playtime", 0.0) or 0.0)
        if playtime < min_playtime_hours:
            skipped_short_playtime += 1
            continue

        if only_positive and not r.get("recommend", False):
            continue

        ts = parse_ts(r.get("post_date"))
        if ts is None:
            skipped_ts += 1
            continue

        game_idx = game2idx[gid]
        tmp[user].append((ts, game_idx))

        if (i + 1) % log_every == 0 or (i + 1) == total:
            elapsed = time.time() - t0
            processed = i + 1
            rate = processed / elapsed if elapsed > 0 else 0.0
            remaining = total - processed
            eta = remaining / rate if rate > 0 else 0.0
            logger.info(
                f"[cyan]Reviews processed[/cyan]: {processed}/{total} "
                f"({processed/total:.1%}) | "
                f"elapsed={elapsed/60:.1f}m, rate={rate:,.0f} docs/s, "
                f"ETA={eta/60:.1f}m"
            )

    user2idx: Dict[str, int] = {}
    idx2user: List[str] = []
    user_histories: Dict[int, List[int]] = {}

    logger.info("[cyan]Aggregating interactions per user...[/cyan]")
    t1 = time.time()

    for user, rows in tmp.items():
        if len(rows) < 2:
            continue

        rows.sort(key=lambda x: x[0])
        seq = [g for _, g in rows]

        if len(seq) < 2:
            continue

        uidx = len(idx2user)
        user2idx[user] = uidx
        idx2user.append(user)
        user_histories[uidx] = seq

    dt_agg = time.time() - t1

    logger.info(
        f"[green]User histories built[/green]: {len(user_histories)} users "
        f"(skipped: no_game={skipped_no_game}, short_playtime={skipped_short_playtime}, "
        f"bad_ts={skipped_ts}). "
        f"Building sequences took {dt_agg:.1f}s; total reviews pass { (time.time()-t0)/60:.1f}m"
    )
    if user_histories:
        sample_uidx = next(iter(user_histories.keys()))
        logger.debug(
            f"Sample user: idx={sample_uidx}, name={idx2user[sample_uidx]}, "
            f"history_len={len(user_histories[sample_uidx])}"
        )
    return user2idx, idx2user, user_histories


# ==============================================================
# 6. BGE-M3 EMBEDDINGS
# ==============================================================

def embed_games_bge_m3(
    games: List[Game],
    batch_size: int = 16,
    model_name: str = "BAAI/bge-m3",
):
    if not games:
        logger.warning("[yellow]No games to embed; returning empty array[/yellow]")
        return np.zeros((0, 0), dtype=np.float32)

    logger.info(
        f"[bold blue]Loading BGE-M3 model[/bold blue] [magenta]{model_name}[/magenta] "
        f"with batch_size={batch_size}"
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"[green]Using device[/green]: {device}")

    t0_load = time.time()
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(device)
    dt_load = time.time() - t0_load
    logger.info(f"[green]Model + tokenizer loaded[/green] in {dt_load:.1f}s")

    texts = [g.text for g in games]
    total = len(texts)
    total_batches = math.ceil(total / batch_size)
    all_embs = []

    logger.info(
        f"[cyan]Embedding games[/cyan]: total={total}, "
        f"batch_size={batch_size}, num_batches={total_batches}"
    )

    model.eval()
    t0 = time.time()
    with torch.no_grad():
        for b_idx in range(total_batches):
            start = b_idx * batch_size
            end = min((b_idx + 1) * batch_size, total)
            batch = texts[start:end]

            toks = tokenizer(
                batch,
                padding=True,
                truncation=True,
                return_tensors="pt",
            ).to(device)

            out = model(**toks)
            last = out.last_hidden_state
            mask = toks.attention_mask.unsqueeze(-1)

            summed = (last * mask).sum(dim=1)
            counts = mask.sum(dim=1)
            emb = (summed / counts).cpu().numpy()

            all_embs.append(emb)

            if (b_idx + 1) % 10 == 0 or (b_idx + 1) == total_batches:
                elapsed = time.time() - t0
                processed = end
                rate = processed / elapsed if elapsed > 0 else 0.0
                remaining = total - processed
                eta = remaining / rate if rate > 0 else 0.0
                logger.info(
                    f"[cyan]Embedding progress[/cyan]: batch {b_idx+1}/{total_batches} "
                    f"({processed}/{total}, {processed/total:.1%}) | "
                    f"elapsed={elapsed/60:.1f}m, rate={rate:,.1f} items/s, "
                    f"ETA={eta/60:.1f}m"
                )

    embs = np.vstack(all_embs)
    logger.info(
        f"[green]Computed embeddings[/green]: shape={embs.shape} "
        f"(num_games={embs.shape[0]}, dim={embs.shape[1]}). "
        f"Total embedding time={ (time.time()-t0)/60:.1f}m"
    )
    return embs


# ==============================================================
# 7. SAVE HELPERS
# ==============================================================

def save_json(obj, path):
    logger.info(f"[cyan]Saving JSON[/cyan] -> {path}")
    t0 = time.time()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    dt = time.time() - t0
    logger.info(f"[green]Saved[/green] JSON in {dt:.2f}s")


def save_jsonl(games: List[Game], path):
    logger.info(f"[cyan]Saving JSONL[/cyan] -> {path}")
    t0 = time.time()
    with open(path, "w", encoding="utf-8") as f:
        for g in games:
            f.write(json.dumps(asdict(g), ensure_ascii=False) + "\n")
    dt = time.time() - t0
    logger.info(f"[green]Saved[/green] JSONL ({len(games)} lines) in {dt:.2f}s")


# ==============================================================
# 8. MAIN
# ==============================================================

def main():
    mongo_uri = build_mongo_uri()

    logger.info("[bold blue]=== STEP 1: Load raw data ===[/bold blue]")
    raw_games = load_raw_games(mongo_uri)
    raw_reviews = load_raw_reviews(mongo_uri)

    logger.info("[bold blue]=== STEP 2: Preprocess games ===[/bold blue]")
    games, game2idx, idx2game = preprocess_games(raw_games)

    logger.info("[bold blue]=== STEP 3: Build user histories ===[/bold blue]")
    user2idx, idx2user, user_histories = preprocess_user_histories(
        raw_reviews,
        game2idx,
        min_playtime_hours=0.3,
        only_positive=False,
    )

    logger.info(
        f"[yellow]Summary[/yellow]: games={len(games)}, "
        f"users_with_history={len(user_histories)}, "
        f"raw_reviews={len(raw_reviews)}"
    )

    logger.info("[bold blue]=== STEP 4: Compute BGE-M3 semantic embeddings ===[/bold blue]")
    semantic_embeddings = embed_games_bge_m3(games)

    out_dir = "src/GenSar/preprocessed"
    os.makedirs(out_dir, exist_ok=True)

    logger.info("[bold blue]=== STEP 5: Save all artifacts ===[/bold blue]")
    save_jsonl(games, os.path.join(out_dir, "games.jsonl"))
    save_json(game2idx, os.path.join(out_dir, "game2idx.json"))
    save_json(idx2game, os.path.join(out_dir, "idx2game.json"))
    save_json(user2idx, os.path.join(out_dir, "user2idx.json"))
    save_json(idx2user, os.path.join(out_dir, "idx2user.json"))
    save_json(user_histories, os.path.join(out_dir, "user_histories.json"))

    npy_path = os.path.join(out_dir, "semantic_embeddings.npy")
    logger.info(f"[cyan]Saving embeddings[/cyan] -> {npy_path}")
    t0 = time.time()
    np.save(npy_path, semantic_embeddings)
    dt = time.time() - t0
    logger.info(
        f"[green]Saved[/green] embeddings to {npy_path} in {dt:.2f}s "
        f"(shape={semantic_embeddings.shape})"
    )

    logger.info("[bold green]Preprocessing DONE.[/bold green]")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("[bold red]Fatal error in preprocessing[/bold red]")
        raise
