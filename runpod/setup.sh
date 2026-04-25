#!/usr/bin/env bash
# Bootstrap del pod RunPod A4500 para tutelas-extraction worker.
# Corre desde /workspace/tutelas-app/ (repo clonado o subido vía scp).
#
# Uso dentro del pod:
#   cd /workspace/tutelas-app
#   bash runpod/setup.sh
#   python runpod/preload_models.py
#   bash runpod/start_server.sh

set -euo pipefail

echo "=========================================="
echo "Tutelas Extraction Worker — bootstrap"
echo "=========================================="

# -----------------------------------------------------------
# 1. Paquetes de sistema
# -----------------------------------------------------------
echo "[1/5] Paquetes apt..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-spa \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    antiword \
    libreoffice \
    curl \
    git
rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------
# 2. Python deps (sin paddle)
# -----------------------------------------------------------
echo "[2/5] pip install deps generales..."
pip install --upgrade pip
pip install --no-cache-dir -r runpod/requirements.txt

# -----------------------------------------------------------
# 2b. PaddlePaddle-GPU desde index oficial (wheels para CUDA 12.x)
#     PyPI público solo tiene 2.5.x-2.6.x para CUDA 11.x.
#     El pod tiene CUDA 12.4/12.8, necesitamos el index de paddle.
# -----------------------------------------------------------
echo "[2b/5] PaddlePaddle-GPU (CUDA 12)..."
# Auto-detectar CUDA major.minor (12.6, 12.4, etc.) para elegir wheel
CUDA_MAJOR_MINOR=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)
echo "  Driver CUDA major detectado: $CUDA_MAJOR_MINOR"

# Probar índices oficiales de paddle en orden (cu126 → cu123 → cu118)
PADDLE_INDICES=(
  "https://www.paddlepaddle.org.cn/packages/stable/cu126/"
  "https://www.paddlepaddle.org.cn/packages/stable/cu123/"
  "https://www.paddlepaddle.org.cn/packages/stable/cu118/"
)
PADDLE_OK=0
for idx in "${PADDLE_INDICES[@]}"; do
  echo "  Intentando $idx ..."
  if pip install --no-cache-dir paddlepaddle-gpu -i "$idx"; then
    PADDLE_OK=1
    echo "  ✅ paddlepaddle-gpu instalado desde $idx"
    break
  fi
  echo "  ⚠️  Falló con $idx, probando siguiente"
done
if [ "$PADDLE_OK" -ne 1 ]; then
  echo "  ⚠️  Todos los índices oficiales fallaron. Instalando paddlepaddle CPU como fallback."
  pip install --no-cache-dir paddlepaddle
fi

echo "[2c/5] PaddleOCR..."
pip install --no-cache-dir "paddleocr>=2.10,<3.0"

# -----------------------------------------------------------
# 3. Modelos spaCy
# -----------------------------------------------------------
echo "[3/5] spaCy es_core_news_lg..."
python -m spacy download es_core_news_lg

# -----------------------------------------------------------
# 4. Directorio persistente para modelos PaddleOCR/Marker
# -----------------------------------------------------------
echo "[4/5] Directorios persistentes..."
mkdir -p /workspace/models/paddleocr
mkdir -p /workspace/models/marker
mkdir -p /workspace/cache

# Variables que PaddleOCR y Marker leen para persistir modelos
export PADDLE_OCR_BASE_DIR=/workspace/models/paddleocr
export HF_HOME=/workspace/models/marker
export TRANSFORMERS_CACHE=/workspace/models/marker

# -----------------------------------------------------------
# 5. Sanity check GPU
# -----------------------------------------------------------
echo "[5/5] GPU sanity check..."
python -c "import paddle; print('Paddle GPU:', paddle.device.is_compiled_with_cuda())"
nvidia-smi | head -15 || echo "WARNING: nvidia-smi no disponible"

echo ""
echo "=========================================="
echo "Setup OK. Siguiente:"
echo "  python runpod/preload_models.py"
echo "  bash runpod/start_server.sh"
echo "=========================================="
