"""Singleton lazy del encoder BGE-M3.

GPU memoria: ~2.3 GB. Se carga una sola vez por proceso (thread-safe).
Throughput medido en RTX A4500: ~40 textos/s en batch 32.

Variables de entorno:
    BGE_M3_PATH    ruta local del modelo (default /workspace/models/bge-m3)
    BGE_M3_DEVICE  cuda | cpu (default cuda)
    BGE_M3_BATCH   batch size por defecto (default 32)
"""
from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Iterable

import numpy as np

logger = logging.getLogger("tutelas.ml.embeddings.encoder")

MODEL_PATH = os.environ.get("BGE_M3_PATH", "/workspace/models/bge-m3")
DEFAULT_DEVICE = os.environ.get("BGE_M3_DEVICE", "cuda")
DEFAULT_BATCH = int(os.environ.get("BGE_M3_BATCH", "32"))

_model = None
_lock = Lock()


def get_encoder():
    """Devuelve el SentenceTransformer cargado en GPU. Lazy + thread-safe."""
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer
        logger.info("Cargando BGE-M3 desde %s en %s", MODEL_PATH, DEFAULT_DEVICE)
        _model = SentenceTransformer(MODEL_PATH, device=DEFAULT_DEVICE)
        return _model


def encode_texts(
    texts: Iterable[str],
    batch_size: int = DEFAULT_BATCH,
    show_progress: bool = False,
) -> np.ndarray:
    """Codifica textos a vectores L2-normalizados (cosine-ready).

    Returns:
        ndarray (n, 1024) float32, normalizado L2.
    """
    enc = get_encoder()
    arr = enc.encode(
        list(texts),
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
    )
    return arr.astype("float32")
