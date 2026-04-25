#!/usr/bin/env bash
# Arranca el servidor FastAPI del extraction worker.
# Lee MODEL_SERVER_TOKEN y MODEL_SERVER_WORKERS de env.

set -euo pipefail

cd "$(dirname "$0")/.."

export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
export PADDLE_OCR_BASE_DIR=${PADDLE_OCR_BASE_DIR:-/workspace/models/paddleocr}
export HF_HOME=${HF_HOME:-/workspace/models/marker}
export TRANSFORMERS_CACHE=${TRANSFORMERS_CACHE:-/workspace/models/marker}

# Flags cognitivos iguales al local para idempotencia del pipeline
export USE_COGNITIVE_PIPELINE=true
export NORMALIZER_ENABLED=true
export NORMALIZER_USE_PADDLEOCR=true
export NORMALIZER_USE_MARKER=${NORMALIZER_USE_MARKER:-true}
export COGNITIVE_ENTROPY_THRESHOLD=2.2

# Auth (obligatorio)
if [ -z "${MODEL_SERVER_TOKEN:-}" ]; then
  echo "ERROR: MODEL_SERVER_TOKEN no está seteado. Exporta un secret bearer token antes de arrancar."
  echo "Ejemplo: export MODEL_SERVER_TOKEN=\$(openssl rand -hex 32)"
  exit 1
fi

WORKERS=${MODEL_SERVER_WORKERS:-2}
PORT=${MODEL_SERVER_PORT:-8000}

echo "Arrancando uvicorn en :$PORT con $WORKERS workers (token configurado)"
exec uvicorn runpod.server:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers "$WORKERS" \
    --log-level info \
    --timeout-keep-alive 120
