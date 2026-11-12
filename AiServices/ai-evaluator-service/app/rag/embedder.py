"""Wrap bge-m3 qua sentence-transformers: load model lan dau goi, encode theo batch, da normalize."""
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

from app.config import get_settings

# Cache model trong thu muc service (da gitignore), khong dua vao code
HF_CACHE_DIR = Path(__file__).resolve().parents[2] / ".hf_cache"


class Embedder:
    def __init__(self, model_name: Optional[str] = None, batch_size: int = 32):
        self.model_name = model_name or get_settings().rag_embedding_model
        self.batch_size = batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            # Import tai day de service khong can torch khi RAG tat
            import torch
            from sentence_transformers import SentenceTransformer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = SentenceTransformer(self.model_name, device=device, cache_folder=str(HF_CACHE_DIR))
        return self._model

    def encode(self, texts: Sequence[str], show_progress: bool = False) -> list[list[float]]:
        vectors = self._load().encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=show_progress,
        )
        return vectors.tolist()


@lru_cache
def get_default_embedder() -> Embedder:
    """1 embedder dung chung trong process, de endpoint khong load lai model o moi request."""
    return Embedder()
