"""
Sentence embeddings for questions.

Every distinct q_core in the master is embedded once and cached, so the
knowledge-base index, the classifier experiments and the offline evaluation
all reuse the same vectors. Vectors are L2-normalised (cosine = dot product).

    python -m src.triage.embeddings          # build or reuse the cache
"""
from __future__ import annotations

import time
from functools import lru_cache

import numpy as np
import pandas as pd

from src.triage.config import load_config, path

EMB_FILE = "question_embeddings.npy"
TEXT_FILE = "question_texts.parquet"


@lru_cache(maxsize=1)
def get_model():
    # Imported lazily: torch start-up is slow and tests do not need it.
    from sentence_transformers import SentenceTransformer

    cfg = load_config()["embedding"]
    try:
        # Cache first: avoids a slow hub round-trip on every start-up.
        model = SentenceTransformer(cfg["model"], device="cpu", local_files_only=True)
    except Exception:
        model = SentenceTransformer(cfg["model"], device="cpu")
    model.max_seq_length = cfg["max_seq_length"]
    return model


def embed_texts(texts: list[str], batch_size: int | None = None, show_progress: bool = False) -> np.ndarray:
    cfg = load_config()["embedding"]
    prefixed = [cfg["prefix"] + (t or "") for t in texts]
    vecs = get_model().encode(
        prefixed,
        batch_size=batch_size or cfg["batch_size"],
        normalize_embeddings=True,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
    )
    return vecs.astype(np.float32)


def load_question_embeddings() -> tuple[pd.Series, np.ndarray]:
    """Returns (q_core -> row index mapping, embedding matrix)."""
    art = path("artifacts")
    texts = pd.read_parquet(art / TEXT_FILE)["q_core"]
    emb = np.load(art / EMB_FILE, mmap_mode="r")
    index = pd.Series(np.arange(len(texts)), index=texts.values)
    return index, emb


def build_question_embeddings(force: bool = False) -> None:
    art = path("artifacts")
    art.mkdir(parents=True, exist_ok=True)
    emb_path, text_path = art / EMB_FILE, art / TEXT_FILE

    q = pd.read_parquet(path("master"), columns=["q_core"])["q_core"].fillna("")
    texts = sorted(set(q) - {""})

    if not force and emb_path.exists() and text_path.exists():
        cached = pd.read_parquet(text_path)["q_core"].tolist()
        if cached == texts:
            print(f"Embedding cache is current ({len(texts):,} questions); skipping.")
            return

    print(f"Embedding {len(texts):,} distinct questions with {load_config()['embedding']['model']} ...")
    start = time.time()
    # Chunked so progress is visible and a crash does not lose everything.
    chunk = 8192
    parts = []
    for i in range(0, len(texts), chunk):
        parts.append(embed_texts(texts[i : i + chunk]))
        done = min(i + chunk, len(texts))
        rate = done / (time.time() - start)
        print(f"  {done:,}/{len(texts):,}  ({rate:.0f}/s)", flush=True)

    np.save(emb_path, np.vstack(parts))
    pd.DataFrame({"q_core": texts}).to_parquet(text_path, index=False)
    print(f"Saved {emb_path} in {time.time() - start:.0f}s")


if __name__ == "__main__":
    build_question_embeddings()
