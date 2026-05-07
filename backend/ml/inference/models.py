"""Carga de modelos sklearn entrenados + predict_field con fallback k-NN.

Capa 4.5 v9.0 — dos niveles encadenados:

  [1] sklearn TF-IDF (rápido, léxico, entrenado con Excel):
        si confidence ≥ MIN_CONFIDENCE_PER_TARGET → return
        si confidence < threshold → cae al fallback
  [2] k-NN consensus sobre BGE-M3 embeddings (semántico):
        busca k=5 vecinos en historical_cases
        voto mayoritario; si agreement ≥ KNN_MIN_AGREEMENT → return
        si no hay consenso → return None (admite "no sé")

API:
    pred = predict_field("tema_normalized", text="<observaciones+tema...>")
    if pred:
        case.tema = pred.value          # value
        case.tema_conf = pred.confidence # 0..1
        case.tema_src = pred.source      # "sklearn" | "knn_consensus"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import joblib

logger = logging.getLogger("tutelas.ml.inference")

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"

# Threshold mínimo de confidence sklearn por target. Más bajo cuanto más clases.
MIN_CONFIDENCE_PER_TARGET: dict[str, float] = {
    "tipo": 0.65,                 # binario
    "direccion": 0.65,            # 5 clases L1
    "dependencia": 0.40,          # 17 clases L2
    "tema_normalized": 0.40,      # 25 clases
}
MIN_CONFIDENCE_DEFAULT = 0.5

# Threshold de acuerdo k-NN para aceptar fallback. 0.6 = 3 de 5 vecinos coinciden.
KNN_MIN_AGREEMENT = 0.6
KNN_K = 5

# Mapping target sklearn → target k-NN (columnas en meta.sqlite de embeddings).
_TARGET_TO_KNN: dict[str, str] = {
    "tema_normalized": "tema",
    "dependencia": "dependencia",
    "direccion": "direccion",
    "tipo": "tipo",
}


@dataclass
class Prediction:
    target: str
    value: str
    confidence: float
    source: str = "sklearn"            # "sklearn" | "knn_consensus"
    model_version: str = "v9.0"


_models: dict[str, object] = {}
_lock = Lock()


def _load_model(target: str):
    """Lazy load + cache del modelo joblib."""
    if target in _models:
        return _models[target]
    with _lock:
        if target in _models:
            return _models[target]
        path = ARTIFACTS / f"{target}.joblib"
        if not path.exists():
            logger.warning("Modelo %s no encontrado en %s", target, path)
            _models[target] = None
            return None
        try:
            model = joblib.load(path)
            _models[target] = model
            logger.info("Modelo %s cargado desde %s", target, path)
            return model
        except Exception as e:
            logger.exception("Error cargando %s: %s", target, e)
            _models[target] = None
            return None


def _try_sklearn(target: str, text: str) -> Prediction | None:
    """Predicción sklearn primaria. None si modelo ausente o conf < threshold."""
    model = _load_model(target)
    if model is None:
        return None
    try:
        text_clean = text[:5000].lower()
        probas = model.predict_proba([text_clean])[0]
        idx = probas.argmax()
        confidence = float(probas[idx])
        threshold = MIN_CONFIDENCE_PER_TARGET.get(target, MIN_CONFIDENCE_DEFAULT)
        if confidence < threshold:
            logger.debug("[%s] sklearn conf %.3f < %.2f", target, confidence, threshold)
            return None
        return Prediction(
            target=target,
            value=str(model.classes_[idx]),
            confidence=confidence,
            source="sklearn",
        )
    except Exception as e:
        logger.warning("[%s] sklearn falló: %s", target, e)
        return None


def _try_knn(target: str, text: str) -> Prediction | None:
    """Fallback semántico vía BGE-M3 + k-NN consensus."""
    knn_target = _TARGET_TO_KNN.get(target)
    if not knn_target:
        return None
    try:
        # Import lazy: solo cuando hace falta (BGE-M3 cuesta GPU)
        from backend.ml.embeddings import knn_consensus
        cp = knn_consensus(
            text=text,
            target=knn_target,
            k=KNN_K,
            min_agreement=KNN_MIN_AGREEMENT,
            source="historical",
        )
        if cp is None:
            return None
        return Prediction(
            target=target,
            value=cp.value,
            confidence=cp.confidence,
            source="knn_consensus",
        )
    except FileNotFoundError:
        logger.warning("[%s] FAISS index no construido — sin fallback k-NN", target)
        return None
    except Exception as e:
        logger.warning("[%s] knn fallback falló: %s", target, e)
        return None


def predict_field(target: str, text: str) -> Prediction | None:
    """Predice un valor para `target`.

    Cadena: sklearn → k-NN consensus → None.

    Args:
      target: 'tema_normalized' | 'direccion' | 'dependencia' | 'tipo'
      text:   texto del caso (asunto + pretensiones + accionados + ...)

    Returns:
      Prediction con `source` indicando qué nivel produjo la predicción,
      o None si ningún nivel alcanzó confianza suficiente.
    """
    if not text or len(text.strip()) < 10:
        return None

    pred = _try_sklearn(target, text)
    if pred is not None:
        return pred

    pred = _try_knn(target, text)
    if pred is not None:
        logger.info("[%s] knn fallback usado: %s (conf=%.2f)",
                    target, pred.value, pred.confidence)
        return pred

    return None


def is_available(target: str) -> bool:
    """True si el modelo sklearn está cargado correctamente."""
    return _load_model(target) is not None


def all_targets() -> list[str]:
    """Lista de targets con modelo entrenado."""
    return [p.stem for p in ARTIFACTS.glob("*.joblib")]
