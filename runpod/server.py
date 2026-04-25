"""FastAPI server del extraction worker.

Endpoints:
    GET  /health                    → ping básico
    GET  /models/status             → verifica que los modelos están cargados
    POST /cognitive/extract-case    → procesa un caso (multipart: meta.json + docs.zip)

El server NO persiste nada a disco. Cada request es stateless.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from runpod.auth import require_bearer
from runpod.extraction_worker import process_case


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("tutelas.pod.server")


# ============================================================
# App
# ============================================================

app = FastAPI(
    title="Tutelas Extraction Worker",
    version="1.0.0",
    description="Pipeline cognitivo v6.0 ejecutándose stateless en GPU pod.",
)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "tutelas-extraction-worker"}


@app.get("/models/status", dependencies=[Depends(require_bearer)])
def models_status() -> dict:
    """Reporta qué modelos están cargados (útil para health checks antes de batch)."""
    status_report: dict = {"ok": True, "models": {}}

    # spaCy
    try:
        import spacy
        nlp = spacy.load("es_core_news_lg", disable=["parser", "lemmatizer"])
        status_report["models"]["spacy"] = {
            "loaded": True,
            "model": "es_core_news_lg",
            "pipe_names": nlp.pipe_names,
        }
    except Exception as e:
        status_report["ok"] = False
        status_report["models"]["spacy"] = {"loaded": False, "error": str(e)}

    # Paddle
    try:
        import paddle
        status_report["models"]["paddle"] = {
            "loaded": True,
            "cuda": paddle.device.is_compiled_with_cuda(),
        }
    except Exception as e:
        status_report["ok"] = False
        status_report["models"]["paddle"] = {"loaded": False, "error": str(e)}

    # GPU
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        status_report["gpu"] = result.stdout.strip() or "N/A"
    except Exception as e:
        status_report["gpu"] = f"error: {e}"

    return status_report


@app.post(
    "/cognitive/extract-case",
    dependencies=[Depends(require_bearer)],
    status_code=status.HTTP_200_OK,
)
async def extract_case(
    meta: UploadFile = File(..., description="JSON con {case, documents, emails}"),
    docs: UploadFile = File(..., description="ZIP con los archivos de los documentos"),
) -> JSONResponse:
    """Procesa un caso completo.

    Request:
        multipart/form-data con dos partes:
          - meta:  application/json  (payload del caso)
          - docs:  application/zip   (archivos)

    Response:
        JSON con case_updates, documents_updates, audit_logs, stats.
    """
    t0 = time.time()

    # Parsear meta.json
    try:
        meta_bytes = await meta.read()
        case_meta = json.loads(meta_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"meta.json inválido: {e}",
        )

    if "case" not in case_meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="meta.json debe contener la clave 'case'",
        )

    # Leer ZIP (streaming a bytes; para casos >1 GB habría que streamear a disco)
    zip_bytes = await docs.read()
    log.info(
        "extract-case in: case_id=%s docs=%d zip_size=%.1fMB",
        case_meta.get("case", {}).get("id"),
        len(case_meta.get("documents", [])),
        len(zip_bytes) / 1_048_576,
    )

    try:
        result = process_case(case_meta, zip_bytes)
    except Exception as e:
        log.exception("process_case falló: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction falló: {e}",
        )

    elapsed = time.time() - t0
    log.info(
        "extract-case out: case_id=%s elapsed=%.1fs docs_returned=%d",
        case_meta.get("case", {}).get("id"),
        elapsed,
        len(result.documents_updates),
    )

    return JSONResponse(content=result.to_dict())
