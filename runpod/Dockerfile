# Tutelas Extraction Worker — imagen Docker opcional.
# Útil si quieres reproducir el entorno del pod en otro provider.
# En RunPod es más simple usar el template "RunPod PyTorch 2.1" y correr setup.sh.

FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    python3.10-venv \
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
    git \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /workspace/tutelas-app

COPY runpod/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt
RUN python -m spacy download es_core_news_lg

# El código fuente se monta con -v o se copia al construir con tu build pipeline.
# Aquí solo el esqueleto; `docker run -v .:/workspace/tutelas-app ...` es lo habitual.

ENV PYTHONPATH=/workspace/tutelas-app
ENV PADDLE_OCR_BASE_DIR=/workspace/models/paddleocr
ENV HF_HOME=/workspace/models/marker
ENV TRANSFORMERS_CACHE=/workspace/models/marker
ENV USE_COGNITIVE_PIPELINE=true
ENV NORMALIZER_ENABLED=true
ENV NORMALIZER_USE_PADDLEOCR=true
ENV NORMALIZER_USE_MARKER=true

EXPOSE 8000

CMD ["bash", "runpod/start_server.sh"]
