import os
import json
import math
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
from sklearn.cluster import KMeans

import torch
from torch.utils.data import Dataset, DataLoader
from torch.optim import AdamW

from transformers import (
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    get_linear_schedule_with_warmup,
)

import logging
from rich.logging import RichHandler


# ==============================================================
# 0. PATHS + CONFIG + LOGGING
# ==============================================================

# Assume file is PROJECT_ROOT/src/GenSar/train_gensar.py
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]          # .../PROJECT_ROOT
SRC_DIR = PROJECT_ROOT / "src"
GENSAR_DIR = SRC_DIR / "GenSar"
PREPRO_DIR = GENSAR_DIR / "preprocessed"
MODEL_OUT_DIR = GENSAR_DIR / "models" / "gensar_t5"
MODEL_OUT_DIR.mkdir(parents=True, exist_ok=True)

# PQ config
N_SUBVECTORS = int(os.getenv("GENSAR_N_SUBVECTORS", 8))
N_CENTROIDS = int(os.getenv("GENSAR_N_CENTROIDS", 64))

# T5 config
T5_MODEL_NAME = os.getenv("GENSAR_T5_MODEL", "t5-small")  # or "t5-base"
MAX_INPUT_LEN = int(os.getenv("GENSAR_MAX_INPUT_LEN", 256))
MAX_TARGET_LEN = int(os.getenv("GENSAR_MAX_TARGET_LEN", 32))
BATCH_SIZE = int(os.getenv("GENSAR_BATCH_SIZE", 128))
NUM_EPOCHS = int(os.getenv("GENSAR_NUM_EPOCHS", 3))
LR = float(os.getenv("GENSAR_LR", 1e-5))
MAX_HISTORY = int(os.getenv("GENSAR_MAX_HISTORY", 5))
MAX_EXAMPLES_PER_USER = int(os.getenv("GENSAR_MAX_EX_PER_USER", 5))
MAX_USERS = int(os.getenv("GENSAR_MAX_USERS", 800000))
USE_FP32 = os.getenv("GENSAR_USE_FP32", "false").lower() == "true"


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
logger = logging.getLogger("gensar_train")

logger.info(
    f"[green]GenSAR training logger initialized[/green] at level: {LOG_LEVEL}"
)
logger.info(
    f"[cyan]PROJECT_ROOT[/cyan] = {PROJECT_ROOT}\n"
    f"[cyan]PREPRO_DIR[/cyan]   = {PREPRO_DIR}\n"
    f"[cyan]MODEL_OUT_DIR[/cyan]= {MODEL_OUT_DIR}"
)


# ==============================================================
# 1. DATA LOADING
# ==============================================================

@dataclass
class Game:
    game_id: str
    name: str
    text: str


def load_games() -> Tuple[List[Game], Dict[str, int], List[str]]:
    games_path = PREPRO_DIR / "games.jsonl"
    game2idx_path = PREPRO_DIR / "game2idx.json"
    idx2game_path = PREPRO_DIR / "idx2game.json"

    logger.info(f"[cyan]Loading games from[/cyan] {games_path}")
    games: List[Game] = []
    with games_path.open("r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            games.append(
                Game(
                    game_id=str(obj["game_id"]),
                    name=obj["name"],
                    text=obj["text"],
                )
            )

    with game2idx_path.open("r", encoding="utf-8") as f:
        game2idx = json.load(f)

    with idx2game_path.open("r", encoding="utf-8") as f:
        idx2game = json.load(f)

    logger.info(f"[green]Loaded[/green] {len(games)} games")
    return games, game2idx, idx2game


def load_user_histories() -> Tuple[Dict[str, int], List[str], Dict[int, List[int]]]:
    user2idx_path = PREPRO_DIR / "user2idx.json"
    idx2user_path = PREPRO_DIR / "idx2user.json"
    hist_path = PREPRO_DIR / "user_histories.json"

    logger.info(f"[cyan]Loading user mappings and histories from[/cyan] {PREPRO_DIR}")
    with user2idx_path.open("r", encoding="utf-8") as f:
        user2idx = json.load(f)

    with idx2user_path.open("r", encoding="utf-8") as f:
        idx2user = json.load(f)

    with hist_path.open("r", encoding="utf-8") as f:
        raw_hist = json.load(f)

    user_histories: Dict[int, List[int]] = {
        int(uidx): seq for uidx, seq in raw_hist.items()
    }

    logger.info(f"[green]Loaded[/green] {len(user_histories)} user histories")
    return user2idx, idx2user, user_histories


def load_embeddings() -> np.ndarray:
    emb_path = PREPRO_DIR / "semantic_embeddings.npy"
    logger.info(f"[cyan]Loading semantic embeddings from[/cyan] {emb_path}")
    embs = np.load(emb_path)
    logger.info(f"[green]Embeddings shape[/green]: {embs.shape}")
    return embs


# ==============================================================
# 2. PQ IDENTIFIER BUILDER
# ==============================================================

class PQIdentifier:
    def __init__(self, n_subvectors: int, n_centroids: int):
        self.n_subvectors = n_subvectors
        self.n_centroids = n_centroids
        self.dim = None
        self.kmeans_list: List[KMeans] = []

    def fit(self, X: np.ndarray):
        self.dim = X.shape[1]
        assert self.dim % self.n_subvectors == 0, (
            f"Embedding dim {self.dim} must be divisible by "
            f"n_subvectors={self.n_subvectors}"
        )
        sub_dim = self.dim // self.n_subvectors

        self.kmeans_list = []
        logger.info(
            f"[cyan]Fitting PQ[/cyan]: dim={self.dim}, n_subvectors={self.n_subvectors}, "
            f"n_centroids={self.n_centroids}, sub_dim={sub_dim}"
        )

        t0 = time.time()
        for i in range(self.n_subvectors):
            sub = X[:, i * sub_dim : (i + 1) * sub_dim]
            logger.info(
                f"[cyan]  Subspace {i+1}/{self.n_subvectors}[/cyan]: shape={sub.shape}"
            )
            km = KMeans(
                n_clusters=self.n_centroids,
                random_state=42,
                n_init="auto",
            )
            km.fit(sub)
            self.kmeans_list.append(km)
        logger.info(f"[green]PQ fitted[/green] in {(time.time() - t0) / 60:.1f}m")

    def encode(self, X: np.ndarray) -> np.ndarray:
        assert self.dim is not None, "PQIdentifier must be fit before encode"
        N = X.shape[0]
        sub_dim = self.dim // self.n_subvectors
        codes = np.empty((N, self.n_subvectors), dtype=np.int32)

        t0 = time.time()
        for i in range(self.n_subvectors):
            km = self.kmeans_list[i]
            sub = X[:, i * sub_dim : (i + 1) * sub_dim]
            codes[:, i] = km.predict(sub)
            if (i + 1) % 2 == 0 or (i + 1) == self.n_subvectors:
                logger.info(
                    f"[cyan]Encoded subspace {i+1}/{self.n_subvectors}[/cyan]"
                )

        logger.info(
            f"[green]All PQ codes computed[/green] for {N} items "
            f"in {time.time() - t0:.1f}s"
        )
        return codes

    def codes_to_tokens(self, codes_1d: np.ndarray) -> List[str]:
        tokens = [f"<c{i}_{int(codes_1d[i])}>" for i in range(self.n_subvectors)]
        return tokens


# ==============================================================
# 3. BUILD IDENTIFIER TOKENS FOR ALL GAMES
# ==============================================================

def build_identifiers_for_games(
    embeddings: np.ndarray,
) -> Tuple[np.ndarray, Dict[int, List[str]]]:
    pq = PQIdentifier(N_SUBVECTORS, N_CENTROIDS)
    pq.fit(embeddings)
    codes = pq.encode(embeddings)

    game_idx_to_tokens: Dict[int, List[str]] = {}
    for game_idx in range(embeddings.shape[0]):
        tokens = pq.codes_to_tokens(codes[game_idx])
        game_idx_to_tokens[game_idx] = tokens

    return codes, game_idx_to_tokens


def save_identifiers(
    codes: np.ndarray,
    game_idx_to_tokens: Dict[int, List[str]],
):
    codes_path = PREPRO_DIR / "game_codes.npy"
    tokens_path = PREPRO_DIR / "game_code_tokens.json"

    logger.info(f"[cyan]Saving game PQ codes[/cyan] -> {codes_path}")
    np.save(codes_path, codes)

    logger.info(f"[cyan]Saving game code tokens[/cyan] -> {tokens_path}")
    with tokens_path.open("w", encoding="utf-8") as f:
        json.dump(
            {str(k): v for k, v in game_idx_to_tokens.items()},
            f,
            indent=2,
            ensure_ascii=False,
        )

    logger.info(
        f"[green]Saved identifiers[/green]: codes shape={codes.shape}, "
        f"{len(game_idx_to_tokens)} token sequences"
    )


# ==============================================================
# 4. DATASET: Beh2ID (history -> next game tokens)
# ==============================================================

class Beh2IDDataset(Dataset):
    def __init__(
        self,
        user_histories: Dict[int, List[int]],
        game_idx_to_tokens: Dict[int, List[str]],
        tokenizer,
        max_history: int = 20,
        max_examples_per_user: int = 50,
        max_input_len: int = 256,
        max_target_len: int = 32,
    ):
        self.tokenizer = tokenizer
        self.max_input_len = max_input_len
        self.max_target_len = max_target_len
        self.examples: List[Tuple[str, str]] = []

        logger.info("[cyan]Building Beh2ID training examples...[/cyan]")
        t0 = time.time()
        for uidx, seq in user_histories.items():
            n = len(seq)
            if n < 2:
                continue

            start_t = max(1, n - max_examples_per_user)
            for t in range(start_t, n):
                hist_ids = seq[max(0, t - max_history) : t]
                target_id = seq[t]
                if not hist_ids:
                    continue

                hist_strs = []
                for gid in hist_ids:
                    code_tokens = game_idx_to_tokens[gid]
                    hist_strs.append(" ".join(code_tokens))

                history_text = "; ".join(hist_strs)
                target_tokens = game_idx_to_tokens[target_id]
                target_text = " ".join(target_tokens)

                src = (
                    "Below is the list of games the user interacted with, "
                    "as identifier codes: "
                    f"{history_text}. Predict the identifier codes of the next game."
                )
                self.examples.append((src, target_text))

        dt = time.time() - t0
        logger.info(
            f"[green]Beh2ID examples built[/green]: {len(self.examples)} examples "
            f"in {dt/60:.1f}m"
        )

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        src, tgt = self.examples[idx]

        enc = self.tokenizer(
            src,
            padding="max_length",
            truncation=True,
            max_length=self.max_input_len,
            return_tensors="pt",
        )

        with self.tokenizer.as_target_tokenizer():
            dec = self.tokenizer(
                tgt,
                padding="max_length",
                truncation=True,
                max_length=self.max_target_len,
                return_tensors="pt",
            )

        return {
            "input_ids": enc["input_ids"].squeeze(0),
            "attention_mask": enc["attention_mask"].squeeze(0),
            "labels": dec["input_ids"].squeeze(0),
        }


# ==============================================================
# 5. TRAINING LOOP
# ==============================================================

def add_code_tokens_to_tokenizer(tokenizer):
    extra_tokens = []
    for i in range(N_SUBVECTORS):
        for j in range(N_CENTROIDS):
            extra_tokens.append(f"<c{i}_{j}>")
    logger.info(
        f"[cyan]Adding[/cyan] {len(extra_tokens)} identifier tokens to tokenizer vocab"
    )
    added = tokenizer.add_tokens(extra_tokens)
    logger.info(f"[green]Tokenizer extended[/green] with {added} new tokens")
    return tokenizer


def train_model(
    dataset: Beh2IDDataset,
    tokenizer,
):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"[green]Training on device[/green]: {device}")
    logger.info(f"[cyan]Loading T5 model[/cyan]: [magenta]{T5_MODEL_NAME}[/magenta]")

    model = AutoModelForSeq2SeqLM.from_pretrained(T5_MODEL_NAME)
    model.resize_token_embeddings(len(tokenizer))
    model.to(device)

    dataloader = DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=0,
        pin_memory=(device == "cuda"),
    )

    steps_per_epoch = len(dataloader)
    total_steps = steps_per_epoch * NUM_EPOCHS

    logger.info(
        f"[cyan]Training config[/cyan]: "
        f"epochs={NUM_EPOCHS}, batch_size={BATCH_SIZE}, "
        f"steps_per_epoch={steps_per_epoch}, total_steps={total_steps}, "
        f"lr={LR}, use_fp32={USE_FP32}"
    )

    optimizer = AdamW(model.parameters(), lr=LR)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(0.1 * total_steps),
        num_training_steps=total_steps,
    )

    # AMP / fp32 toggle
    use_amp = (device == "cuda") and (not USE_FP32)
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    global_step = 0
    t0 = time.time()

    MAX_LOSS = 50.0  # clamp to avoid huge explosions

    model.train()
    for epoch in range(NUM_EPOCHS):
        logger.info(f"[blue]=== Starting epoch {epoch+1}/{NUM_EPOCHS} ===[/blue]")

        epoch_loss = 0.0
        epoch_t0 = time.time()
        nan_skipped = 0

        for step, batch in enumerate(dataloader):
            global_step += 1
            batch = {k: v.to(device) for k, v in batch.items()}

            # ----------------------------
            # Forward pass (AMP if enabled)
            # ----------------------------
            with torch.cuda.amp.autocast(enabled=use_amp):
                outputs = model(
                    input_ids=batch["input_ids"],
                    attention_mask=batch["attention_mask"],
                    labels=batch["labels"],
                )
                loss = outputs.loss

            # ----------------------------
            # NaN / Inf guard
            # ----------------------------
            if torch.isnan(loss) or torch.isinf(loss):
                nan_skipped += 1
                logger.warning(
                    f"[yellow]NaN/Inf loss detected at step {global_step} "
                    f"(epoch={epoch+1}, batch={step+1}). Skipping this batch.[/yellow]"
                )
                optimizer.zero_grad(set_to_none=True)
                continue

            # ----------------------------
            # Loss clamp
            # ----------------------------
            loss = torch.clamp(loss, max=MAX_LOSS)

            # ----------------------------
            # Backward + grad clipping
            # ----------------------------
            scaler.scale(loss).backward()

            # unscale and clip gradients to avoid explosions
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)

            epoch_loss += loss.item()

            # ----------------------------
            # Logging
            # ----------------------------
            if global_step % 100 == 0 or step == steps_per_epoch - 1:
                elapsed = time.time() - t0
                steps_per_sec = global_step / elapsed if elapsed > 0 else 0.0
                remaining = total_steps - global_step
                eta = remaining / steps_per_sec if steps_per_sec > 0 else 0.0

                logger.info(
                    f"[cyan]Step[/cyan] {global_step}/{total_steps} | "
                    f"epoch={epoch+1}/{NUM_EPOCHS}, "
                    f"batch={step+1}/{steps_per_epoch}, "
                    f"loss={loss.item():.4f} | "
                    f"elapsed={elapsed/60:.1f}m, "
                    f"steps/s={steps_per_sec:.2f}, "
                    f"ETA={eta/60:.1f}m"
                )

        # ----------------------------
        # Epoch summary
        # ----------------------------
        effective_steps = max(steps_per_epoch - nan_skipped, 1)
        avg_loss = epoch_loss / effective_steps
        epoch_time = (time.time() - epoch_t0) / 60

        logger.info(
            f"[green]Epoch {epoch+1} finished[/green] | "
            f"avg_loss={avg_loss:.4f}, "
            f"epoch_time={epoch_time:.1f}m, "
            f"skipped_nan={nan_skipped} "
            f"({nan_skipped/steps_per_epoch*100:.3f}% of batches)"
        )

    logger.info(f"[cyan]Saving trained model[/cyan] -> {MODEL_OUT_DIR}")
    model.save_pretrained(MODEL_OUT_DIR)
    tokenizer.save_pretrained(MODEL_OUT_DIR)
    logger.info("[green]Model + tokenizer saved[/green]")

    return model, tokenizer




# ==============================================================
# 6. INFERENCE: recommend_for_user(top_k=N)
# ==============================================================

def load_trained_model_and_artifacts():
    games, game2idx, idx2game = load_games()
    user2idx, idx2user, user_histories = load_user_histories()
    logger.info(f"Size of User_histories before limiting: {len(user_histories)}")
    # Map game_idx -> Game object for nice output
    games_by_idx: Dict[int, Game] = {}
    for game in games:
        gi = game2idx[str(game.game_id)]
        games_by_idx[gi] = game

    codes_path = PREPRO_DIR / "game_codes.npy"
    tokens_path = PREPRO_DIR / "game_code_tokens.json"
    codes = np.load(codes_path)
    with tokens_path.open("r", encoding="utf-8") as f:
        game_idx_to_tokens = {int(k): v for k, v in json.load(f).items()}

    logger.info(f"[cyan]Loading trained model from[/cyan] {MODEL_OUT_DIR}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_OUT_DIR)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_OUT_DIR)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()

    return (
        model,
        tokenizer,
        games_by_idx,
        game2idx,
        idx2game,
        user2idx,
        idx2user,
        user_histories,
        codes,
        game_idx_to_tokens,
    )


def parse_generated_codes(tokens: List[str]) -> List[int]:
    codes: List[int] = []
    for tok in tokens:
        if tok.startswith("<c") and "_" in tok and tok.endswith(">"):
            try:
                inner = tok[1:-1]
                _, idx_str = inner.split("_", 1)
                codes.append(int(idx_str))
            except Exception:
                continue
    return codes


def recommend_for_user(
    username: str,
    top_k: int = 5,
    max_history: int = 20,
):
    """
    Returns a list of up to `top_k` recommended games for `username`.

    Each element is a dict:
      {
        "game_id": str,
        "name": str,
        "game_idx": int,
        "hamming_dist": int,
      }
    """
    (
        model,
        tokenizer,
        games_by_idx,
        game2idx,
        idx2game,
        user2idx,
        idx2user,
        user_histories,
        codes,
        game_idx_to_tokens,
    ) = load_trained_model_and_artifacts()

    device = "cuda" if torch.cuda.is_available() else "cpu"

    if username not in user2idx:
        raise ValueError(f"Unknown user: {username}")

    uidx = user2idx[username]
    history = user_histories.get(uidx, [])
    if not history:
        raise ValueError(f"User {username} has no history")

    hist_ids = history[-max_history:]
    hist_strs = []
    for gid in hist_ids:
        code_tokens = game_idx_to_tokens[gid]
        hist_strs.append(" ".join(code_tokens))
    history_text = "; ".join(hist_strs)

    prompt = (
        "Below is the list of games the user interacted with, as identifier codes: "
        f"{history_text}. Predict the identifier codes of the next game."
    )

    enc = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_INPUT_LEN,
    ).to(device)

    logger.info(f"[cyan]Running inference for user[/cyan] {username}")
    with torch.no_grad():
        gen_ids = model.generate(
            **enc,
            max_length=MAX_TARGET_LEN,
            num_beams=4,
            early_stopping=True,
        )

    decoded = tokenizer.batch_decode(gen_ids, skip_special_tokens=True)[0]
    gen_tokens = decoded.strip().split()
    gen_codes = parse_generated_codes(gen_tokens)

    if len(gen_codes) != N_SUBVECTORS:
        logger.warning(
            f"[yellow]Generated code length {len(gen_codes)} "
            f"!= N_SUBVECTORS={N_SUBVECTORS}. Will pad/truncate.[/yellow]"
        )
        if len(gen_codes) < N_SUBVECTORS:
            gen_codes += [0] * (N_SUBVECTORS - len(gen_codes))
        else:
            gen_codes = gen_codes[:N_SUBVECTORS]

    gen_codes_arr = np.array(gen_codes, dtype=np.int32)

    logger.info("[cyan]Computing Hamming distances to all games...[/cyan]")
    diffs = (codes != gen_codes_arr[None, :]).astype(np.int32)
    dist = diffs.sum(axis=1)

    best_indices = np.argsort(dist)[:top_k]

    results = []
    logger.info("[green]Top recommendations:[/green]")
    for gi in best_indices:
        game = games_by_idx.get(gi)
        game_id = game.game_id if game is not None else idx2game[gi]
        d = int(dist[gi])
        logger.info(f"  {game_id} | idx={gi} | dist={d} | name={game.name if game else 'UNKNOWN'}")
        results.append(
            {
                "game_id": game_id,
                "name": game.name if game else "UNKNOWN",
                "game_idx": gi,
                "hamming_dist": d,
            }
        )

    return results


# ==============================================================
# 7. MAIN ENTRYPOINT
# ==============================================================

def main():
    logger.info("[bold blue]=== STEP 1: Load preprocessed data ===[/bold blue]")
    games, game2idx, idx2game = load_games()
    _, _, user_histories = load_user_histories()
    if MAX_USERS > 0:
        user_histories = {uid: seq for uid, seq in list(user_histories.items())[:MAX_USERS]}
    embeddings = load_embeddings()

    logger.info("[bold blue]=== STEP 2: Build PQ identifiers ===[/bold blue]")
    codes, game_idx_to_tokens = build_identifiers_for_games(embeddings)
    save_identifiers(codes, game_idx_to_tokens)

    logger.info("[bold blue]=== STEP 3: Prepare Beh2ID dataset ===[/bold blue]")
    logger.info(
        f"[cyan]Loading tokenizer and adding identifier tokens[/cyan] for {T5_MODEL_NAME}"
    )
    tokenizer = AutoTokenizer.from_pretrained(T5_MODEL_NAME)
    tokenizer = add_code_tokens_to_tokenizer(tokenizer)

    dataset = Beh2IDDataset(
        user_histories=user_histories,
        game_idx_to_tokens=game_idx_to_tokens,
        tokenizer=tokenizer,
        max_history=MAX_HISTORY,
        max_examples_per_user=MAX_EXAMPLES_PER_USER,
        max_input_len=MAX_INPUT_LEN,
        max_target_len=MAX_TARGET_LEN,
    )

    logger.info("[bold blue]=== STEP 4: Train T5 Beh2ID model ===[/bold blue]")
    train_model(dataset, tokenizer)

    logger.info("[bold green]GenSAR-style training complete.[/bold green]")

    # ==================================================================
    # QUICK TEST: run recommend_for_user() on one sample user
    # ==================================================================
    try:
        logger.info("[bold blue]=== QUICK TEST: recommend_for_user ===[/bold blue]")

        # Reload full user mappings (not subsampled) to pick a username
        user2idx, idx2user, _ = load_user_histories()

        if not user2idx:
            logger.warning("[yellow]No users found for quick test; skipping.[/yellow]")
            return

        # Pick first user (or you can randomize)
        sample_username = idx2user[0]
        logger.info(f"[cyan]Testing recommendations for user[/cyan] '{sample_username}'")

        recs = recommend_for_user(sample_username, top_k=5)

        logger.info("[green]Quick test recommendations:[/green]")
        for r in recs:
            logger.info(
                f"  game_id={r['game_id']} | name={r['name']} | "
                f"idx={r['game_idx']} | dist={r['hamming_dist']}"
            )
    except Exception:
        logger.exception("[bold red]Quick test recommend_for_user failed[/bold red]")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("[bold red]Fatal error in GenSAR training[/bold red]")
        raise
