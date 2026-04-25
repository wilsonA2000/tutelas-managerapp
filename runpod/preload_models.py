"""Precarga los modelos pesados para que el primer request no pague el warmup.

Ejecutar ANTES de arrancar el server uvicorn.

Modelos cargados:
  - spaCy es_core_news_lg
  - PaddleOCR (español, ángulo + reconocimiento)
  - Marker PDF converter (si NORMALIZER_USE_MARKER=true)
"""

from __future__ import annotations

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("preload")


def preload_spacy() -> None:
    t0 = time.time()
    log.info("Cargando spaCy es_core_news_lg...")
    import spacy
    nlp = spacy.load("es_core_news_lg", disable=["parser", "lemmatizer"])
    _ = list(nlp("Prueba de precalentamiento de modelo spaCy."))
    log.info("spaCy OK en %.2fs", time.time() - t0)


def preload_paddle() -> None:
    t0 = time.time()
    log.info("Cargando PaddleOCR (lang=es, use_gpu=auto)...")
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(
        use_angle_cls=True,
        lang="es",
        use_gpu=True,
        show_log=False,
    )
    # Warmup con imagen dummy
    from PIL import Image
    import numpy as np
    dummy = np.array(Image.new("RGB", (200, 50), (255, 255, 255)))
    _ = ocr.ocr(dummy, cls=True)
    log.info("PaddleOCR OK en %.2fs", time.time() - t0)


def preload_marker() -> None:
    if os.environ.get("NORMALIZER_USE_MARKER", "true").lower() != "true":
        log.info("Marker deshabilitado (NORMALIZER_USE_MARKER != true). Skip.")
        return
    t0 = time.time()
    log.info("Cargando Marker PDF converter (GPU)...")
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        artifact_dict = create_model_dict(device="cuda")
        _ = PdfConverter(
            artifact_dict=artifact_dict,
            config={"output_format": "markdown", "languages": ["es", "en"]},
        )
        log.info("Marker OK en %.2fs", time.time() - t0)
    except Exception as e:
        log.warning("Marker falló (no fatal, seguimos sin Marker): %s", e)


def main() -> int:
    try:
        preload_spacy()
        preload_paddle()
        preload_marker()
        log.info("Todos los modelos precargados. Listo para arrancar el server.")
        return 0
    except Exception as e:
        log.exception("Preload falló: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
