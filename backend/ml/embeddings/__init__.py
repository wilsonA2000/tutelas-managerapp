"""Capa 2 v9.0 — Embeddings semánticos sobre corpus jurídico.

Modelo: BAAI/bge-m3 (multilingüe, 8192 tokens, 1024 dim, MIT).
Índice: FAISS IndexFlatIP + IndexIDMap2 sobre vectores L2-normalizados.

Uso típico:
    from backend.ml.embeddings import search_similar, knn_consensus

    # k-NN simple
    neigh = search_similar("texto de la tutela...", k=5)

    # Consensus voting (fallback de predict_field)
    pred = knn_consensus(text, target="tema", k=5, min_agreement=0.6)
"""
from .encoder import get_encoder, encode_texts
from .query import search_similar, knn_consensus, Neighbor, ConsensusPrediction

__all__ = [
    "get_encoder",
    "encode_texts",
    "search_similar",
    "knn_consensus",
    "Neighbor",
    "ConsensusPrediction",
]
