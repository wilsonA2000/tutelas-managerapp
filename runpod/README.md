# Tutelas Extraction Worker — RunPod A4500

Servidor HTTP que ejecuta el pipeline cognitivo v6.0 (Capas 0-5) en una GPU
RunPod. El backend local sigue siendo la fuente de verdad (DB SQLite, UI,
Gmail monitor); el pod es un "extraction compute worker" stateless.

## Arquitectura

```
Backend local (WSL)                  RunPod A4500 (20GB VRAM, 62GB RAM)
┌────────────────────┐              ┌────────────────────────────┐
│  API REST          │              │  FastAPI server (:8000)    │
│  DB SQLite         │   POST       │  ┌──────────────────────┐  │
│  Gmail monitor     │ ────────►    │  │ SQLite in-memory     │  │
│  unified_cognitive │   ZIP+meta   │  │ unified_cognitive    │  │
│  ┌───────────────┐ │              │  │   Capas 0-5          │  │
│  │ remote_client │ │   JSON       │  │   (OCR, NER, IR,     │  │
│  └───────────────┘ │ ◄────────    │  │    bayesian, ...)    │  │
│  Capas 6-7 local:  │   updates    │  └──────────────────────┘  │
│   consolidator     │              │  Modelos precargados:      │
│   persist          │              │   - PaddleOCR (GPU)        │
│  DB writes         │              │   - spaCy es_core_news_lg  │
└────────────────────┘              │   - Marker (GPU)           │
                                    └────────────────────────────┘
```

## Deploy paso a paso

### 1. Crear pod en RunPod

1. runpod.io → Deploy → GPU Cloud.
2. Elegir **RTX A4500** (20 GB VRAM) en tier **Community**.
3. Template: **"RunPod PyTorch 2.1"** (Ubuntu 22.04 + CUDA 12.1 + Python 3.10).
4. Container disk: **30 GB**. Network Volume: **50 GB** en `/workspace` (persiste entre reinicios).
5. **Expose HTTP Port: 8000**.
6. Deploy. Anotar:
   - Pod ID (ej. `ab12cd34xyz`)
   - URL pública: `https://<pod-id>-8000.proxy.runpod.net`
   - Web Terminal (para shell)

### 2. Subir el código al pod

Desde tu máquina local:

```bash
cd "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app"
bash scripts/package_for_pod.sh
# → genera /tmp/tutelas_pod_<timestamp>.tar.gz (~50-80 MB)
```

Subir al pod (opción A: web terminal con `wget` desde tu Drive/S3; opción B: `scp`
si el pod exponé SSH; opción C: drag-and-drop en la UI de Jupyter).

En el pod (web terminal):

```bash
cd /workspace
mkdir -p tutelas-app
tar -xzf tutelas_pod_*.tar.gz -C tutelas-app
cd tutelas-app
```

### 3. Instalar dependencias y precargar modelos

```bash
bash runpod/setup.sh                   # ~8-10 min primera vez
python runpod/preload_models.py        # ~2-3 min (descarga modelos a /workspace/models)
```

### 4. Generar y guardar el token bearer

```bash
export MODEL_SERVER_TOKEN=$(openssl rand -hex 32)
echo "Token: $MODEL_SERVER_TOKEN"        # ⚠️ Guárdalo, lo necesitas en el local
```

Para que persista entre reinicios del pod:

```bash
echo "export MODEL_SERVER_TOKEN=$MODEL_SERVER_TOKEN" >> ~/.bashrc
```

### 5. Arrancar el server

```bash
bash runpod/start_server.sh
```

O en background:

```bash
nohup bash runpod/start_server.sh > /workspace/server.log 2>&1 &
```

### 6. Verificar desde tu máquina local

```bash
# Health (sin auth)
curl https://<pod-id>-8000.proxy.runpod.net/health

# Models status (con auth)
curl -H "Authorization: Bearer $TOKEN" \
     https://<pod-id>-8000.proxy.runpod.net/models/status
```

Respuesta esperada:
```json
{"ok": true, "models": {"spacy": {"loaded": true, ...}, "paddle": {"loaded": true, "cuda": true}}, "gpu": "..."}
```

### 7. Activar el switch remoto en el local

Editar `.env.experiment_b`:

```bash
USE_REMOTE_EXTRACTION=true
REMOTE_EXTRACTION_URL=https://<pod-id>-8000.proxy.runpod.net
REMOTE_EXTRACTION_TOKEN=<el token generado en paso 4>
REMOTE_EXTRACTION_TIMEOUT=600
```

Reiniciar el backend local:

```bash
cd "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app"
pkill -f "uvicorn backend.main" || true
TUTELAS_ENV_FILE=$(pwd)/.env.experiment_b \
  nohup python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 \
  --log-level info > logs/backend_remote.log 2>&1 &
```

Ahora subir `EXTRACTION_MAX_WORKERS` a 4 (la RAM local ya no es cuello):

```bash
# En .env.experiment_b
EXTRACTION_MAX_WORKERS=4
```

## Flujo de un caso

1. Usuario lanza `/api/extraction/batch` en local.
2. Orquestador local llama `unified_cognitive_extract(db, case)`.
3. El orquestador detecta `USE_REMOTE_EXTRACTION=true` → llama `run_remote_extract`.
4. `remote_client.py` empaqueta archivos del caso + metadata → POST al pod.
5. Pod recibe, crea SQLite in-memory, ejecuta Capas 0-5, retorna JSON.
6. Local aplica los updates a la DB real.
7. Local ejecuta Capas 6 (consolidator cross-case) y 7 (persist + entropy gate).
8. DB local queda actualizada con audit_log trazable (`REMOTE_*` entries).

## Fallback automático

Si el pod falla (timeout, 5xx, DNS, etc.), `run_remote_extract` retorna `None`
y el orquestador continúa con el pipeline 100% local. **Cortes de RunPod no
bloquean el trabajo.**

## Costos (orientativo)

- RTX A4500 Community: ~$0.25/hr.
- Sprint completo (76 casos pendientes × 60s/caso con 4 workers en paralelo): **< $1 USD**.
- Apaga el pod cuando termines (`runpod stop <pod-id>` o UI) para no gastar.

## Troubleshooting

| Síntoma | Diagnóstico |
|---------|-------------|
| `/health` OK pero `/models/status` da 503 | `MODEL_SERVER_TOKEN` no está exportado antes de arrancar el server |
| POST devuelve 500 con "process_case falló" | Revisa `/workspace/server.log` en el pod, probablemente falta tesseract-ocr-spa o un model no precargó |
| Upload lento (>60s para 50MB) | Cambiar a volumen compartido via rclone (Fase 2) |
| Backend local dice "Remote falló, fallback local" | El pod está caído/reiniciando. Revisar `curl /health` desde fuera |
| Audit logs en DB local aparecen duplicados | Esperado: `REMOTE_V6_COGNITIVE_PERSIST` del pod + `V6_COGNITIVE_PERSIST` local. Puedes filtrar por prefijo en queries |

## Seguridad

- El token se envía por HTTPS (RunPod proxy termina TLS).
- No incluir `.env`, `data/tutelas.db`, ni credenciales reales en el tarball.
- El pod NO tiene acceso a tu Gmail ni a la DB real.
- Al destruir el pod, los archivos ZIP temporales se borran con él.
