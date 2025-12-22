# src/GenSar/recommender_service.py

import os
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

import logging
from rich.logging import RichHandler


# ==============================================================
# PATHS + CONFIG + LOGGING
# ==============================================================

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]          # .../PROJECT_ROOT
SRC_DIR = PROJECT_ROOT / "src"
GENSAR_DIR = SRC_DIR / "GenSar"
PREPRO_DIR = GENSAR_DIR / "preprocessed"
MODEL_OUT_DIR = GENSAR_DIR / "models" / "gensar_t5"

MAX_INPUT_LEN = int(os.getenv("GENSAR_MAX_INPUT_LEN", 256))
MAX_TARGET_LEN = int(os.getenv("GENSAR_MAX_TARGET_LEN", 32))
N_SUBVECTORS = int(os.getenv("GENSAR_N_SUBVECTORS", 8))    # must match training
N_CENTROIDS = int(os.getenv("GENSAR_N_CENTROIDS", 64))     # must match training

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
# logger = logging.getLogger("gensar_service")


@dataclass
class Game:
    game_id: str
    name: str
    text: str


class GenSarRecommender:
    """
    Stateful service:
      - load() once at startup
      - recommend_for_user() on each request
    """

    def __init__(self):
        self._loaded = False

        self.games: List[Game] = []
        self.game2idx: Dict[str, int] = {}
        self.idx2game: List[str] = []

        self.user2idx: Dict[str, int] = {}
        self.idx2user: List[str] = []
        self.user_histories: Dict[int, List[int]] = {}

        self.codes: np.ndarray | None = None
        self.game_idx_to_tokens: Dict[int, List[str]] = {}

        self.games_by_idx: Dict[int, Game] = {}

        self.model: AutoModelForSeq2SeqLM | None = None
        self.tokenizer: AutoTokenizer | None = None
        self.device: str = "cpu"

    # ---------------------------
    # Internal loaders
    # ---------------------------

    def _load_games(self) -> None:
        games_path = PREPRO_DIR / "games.jsonl"
        game2idx_path = PREPRO_DIR / "game2idx.json"
        idx2game_path = PREPRO_DIR / "idx2game.json"

        # logger.info(f"[cyan]Loading games from[/cyan] {games_path}")
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

        self.games = games
        self.game2idx = game2idx
        self.idx2game = idx2game

        # index by game_idx for quick lookup
        self.games_by_idx = {}
        for g in self.games:
            gi = self.game2idx[str(g.game_id)]
            self.games_by_idx[gi] = g

        # logger.info(f"[green]Loaded[/green] {len(self.games)} games")

    def _load_user_histories(self) -> None:
        user2idx_path = PREPRO_DIR / "user2idx.json"
        idx2user_path = PREPRO_DIR / "idx2user.json"
        hist_path = PREPRO_DIR / "user_histories.json"

        # logger.info(f"[cyan]Loading user mappings and histories from[/cyan] {PREPRO_DIR}")
        with user2idx_path.open("r", encoding="utf-8") as f:
            user2idx = json.load(f)

        with idx2user_path.open("r", encoding="utf-8") as f:
            idx2user = json.load(f)

        with hist_path.open("r", encoding="utf-8") as f:
            raw_hist = json.load(f)

        user_histories: Dict[int, List[int]] = {
            int(uidx): seq for uidx, seq in raw_hist.items()
        }

        self.user2idx = user2idx
        self.idx2user = idx2user
        self.user_histories = user_histories

        # logger.info(f"[green]Loaded[/green] {len(self.user_histories)} user histories")

    def _load_codes_and_tokens(self) -> None:
        codes_path = PREPRO_DIR / "game_codes.npy"
        tokens_path = PREPRO_DIR / "game_code_tokens.json"

        # logger.info(f"[cyan]Loading PQ codes from[/cyan] {codes_path}")
        codes = np.load(codes_path)
        # logger.info(f"[green]Codes shape[/green]: {codes.shape}")

        # logger.info(f"[cyan]Loading game code tokens from[/cyan] {tokens_path}")
        with tokens_path.open("r", encoding="utf-8") as f:
            game_idx_to_tokens = {int(k): v for k, v in json.load(f).items()}

        self.codes = codes
        self.game_idx_to_tokens = game_idx_to_tokens

    def _load_model(self) -> None:
        # logger.info(f"[cyan]Loading trained model from[/cyan] {MODEL_OUT_DIR}")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_OUT_DIR)
        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_OUT_DIR)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        model.eval()

        self.model = model
        self.tokenizer = tokenizer
        self.device = device

        # logger.info(f"[green]Model loaded on device[/green]: {device}")

    # ---------------------------
    # Public API
    # ---------------------------

    def load(self):
        """
        Load all artifacts into memory.
        Call once at FastAPI startup.
        """
        if self._loaded:
            # logger.info("[yellow]GenSarRecommender.load() called again; ignoring[/yellow]")
            return

        # logger.info("[bold blue]=== Loading GenSAR recommender artifacts ===[/bold blue]")
        t0 = time.time()
        self._load_games()
        self._load_user_histories()
        self._load_codes_and_tokens()
        self._load_model()
        self._loaded = True
        # logger.info(
        #     f"[bold green]GenSAR recommender ready[/bold green] "
        #     f"in {(time.time() - t0):.1f}s"
        # )

    @staticmethod
    def _parse_generated_codes(tokens: List[str]) -> List[int]:
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
        self,
        username: str,
        top_k: int = 5,
        max_history: int = 20,
    ) -> List[Dict]:
        """
        Returns a list of dicts:
          {
            "game_id": str,
            "name": str,
            "game_idx": int,
            "hamming_dist": int,
          }
        """

        if not self._loaded:
            raise RuntimeError("GenSarRecommender not loaded. Call load() first.")

        if username not in self.user2idx:
            raise ValueError(f"Unknown user: {username}")

        uidx = self.user2idx[username]
        history = self.user_histories.get(uidx, [])
        if not history:
            raise ValueError(f"User {username} has no history")

        hist_ids = history[-max_history:]
        hist_strs = []
        for gid in hist_ids:
            code_tokens = self.game_idx_to_tokens[gid]
            hist_strs.append(" ".join(code_tokens))
        history_text = "; ".join(hist_strs)

        prompt = (
            "Below is the list of games the user interacted with, as identifier codes: "
            f"{history_text}. Predict the identifier codes of the next game."
        )

        enc = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_INPUT_LEN,
        ).to(self.device)

        # logger.info(f"[cyan]Running inference for user[/cyan] {username}")
        with torch.no_grad():
            gen_ids = self.model.generate(
                **enc,
                max_length=MAX_TARGET_LEN,
                num_beams=4,
                early_stopping=True,
            )

        decoded = self.tokenizer.batch_decode(gen_ids, skip_special_tokens=True)[0]
        gen_tokens = decoded.strip().split()
        gen_codes = self._parse_generated_codes(gen_tokens)

        if len(gen_codes) != N_SUBVECTORS:
            # logger.warning(
            #     f"[yellow]Generated code length {len(gen_codes)} "
            #     f"!= N_SUBVECTORS={N_SUBVECTORS}. Will pad/truncate.[/yellow]"
            # )
            if len(gen_codes) < N_SUBVECTORS:
                gen_codes += [0] * (N_SUBVECTORS - len(gen_codes))
            else:
                gen_codes = gen_codes[:N_SUBVECTORS]

        gen_codes_arr = np.array(gen_codes, dtype=np.int32)

        # logger.info("[cyan]Computing Hamming distances to all games...[/cyan]")
        diffs = (self.codes != gen_codes_arr[None, :]).astype(np.int32)
        dist = diffs.sum(axis=1)

        best_indices = np.argsort(dist)[:top_k]

        results = []
        # logger.info("[green]Top recommendations:[/green]")
        for gi in best_indices:
            game = self.games_by_idx.get(gi)
            game_id = game.game_id if game is not None else self.idx2game[gi]
            name = game.name if game else "UNKNOWN"
            d = int(dist[gi])
            # logger.info(f"  {game_id} | idx={gi} | dist={d} | name={name}")
            results.append({
                    "game_id": int(game_id),
                    "name": str(name),
                    "game_idx": int(gi),
                    "hamming_dist": int(d),
                })

        return results


# Global singleton recommender
recommender = GenSarRecommender()
