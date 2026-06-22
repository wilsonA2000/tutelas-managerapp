# IURIS — Setup Minimalista Escalable para Appliance Final

> Especificación técnica consolidada para deployment del appliance IURIS
> en hardware modesto cuando consigas financiación.
>
> Validado empíricamente sobre datos reales: 1346 emails, 217 cases, RunPod RTX 4090.
> Extrapolado con factores de degradación a hardware target.

---

## Filosofía del setup minimalista

1. **Lo mínimo que resuelve, sin grasa** — sin embeddings warm si no es crítico, sin VLM warm si lazy alcanza
2. **Cuantización agresiva** — Q4_K_M base, KV cache q8, flash-attn obligatorio
3. **Single warm model** — un solo LLM siempre activo, VLM lazy on-demand
4. **Pipeline determinista primero** — regex+forensic+sklearn hace 70% del trabajo, IA solo para huecos semánticos
5. **Paralelismo conservador** — workers ≤ cores físicos / 1.5
6. **Persistencia tradicional** — SQLite, sin Postgres innecesario para volúmenes < 10k casos
7. **Monitoreo pasivo** — logs estructurados, no observabilidad enterprise

---

## Hardware target (3 escalones de presupuesto)

### 🥉 Tier "Hobby/Dev" — Jetson Orin Nano Super 8GB ($249-415 USD)

```
Specs mínimas:
  CPU: 6-core ARM Cortex-A78AE
  GPU: 1024 CUDA + 32 Tensor Cores Ampere
  RAM: 8 GB LPDDR5 unified (compartida CPU+GPU)
  TOPS: 67 (Super Mode)
  Power: 7-25W
  Storage: NVMe M.2 ≥ 256 GB
```

Constraints:
- VLM solo lazy on-demand (no warm)
- 1 LoRA simultáneo
- `--parallel 1` en llama-server
- 4 workers Python max
- Latencia LLM ~2-3 s/respuesta
- Throughput sostenido: ~20 cases/h cognitivos

**Para qué sirve**: piloto, demo cliente, 1 personería con <50 tutelas/año.

### 🥈 Tier "Profesional" — Jetson Orin NX 16GB ($1,250-1,650 USD)

```
Specs:
  CPU: 8-core ARM Cortex-A78AE
  GPU: 1024 CUDA + 32 Tensor + 2 NVDLA v2
  RAM: 16 GB LPDDR5
  TOPS: 100 (157 Super Mode)
  Power: 10-40W configurable
  Storage: NVMe M.2 ≥ 256 GB
```

Headroom permitido:
- LLM warm + VLM lazy con switch <5s
- 2-3 LoRAs hot-swappable (mismo modelo base, distintos adapters)
- `--parallel 2` slots LLM
- 6-8 workers Python
- Latencia LLM ~1-1.5 s/respuesta
- Throughput sostenido: ~60 cases/h cognitivos

**Para qué sirve**: producto vendible a personerías y secretarías medianas (50-500 tutelas/año).

### 🥇 Tier "Premium" — Strix Halo 128GB ($2,599+) o Jetson AGX Orin 64GB ($1,999+)

```
Specs:
  RAM: 64-128 GB unified
  TOPS: 157+ / 275+
  Multiusuario concurrente OK
```

Permite:
- LLM 30B-A3B + VLM 7B + embeddings BGE-M3 + classifier sklearn — todos warm
- 8+ LoRAs simultáneos
- 5-10 usuarios chat concurrentes
- Latencia LLM <1 s/respuesta
- Throughput: 200+ cases/h

**Para qué sirve**: tribunales superiores, gobernaciones grandes, multi-tenant.

---

## Stack software completo (idéntico en todos los tiers)

### Sistema operativo y runtime

```
Base OS: Ubuntu 22.04 LTS (Jetson) o Debian 12 (mini PC)
Python: 3.11
CUDA: 12.4 (en hardware NVIDIA)
JetPack: 6.x (en Jetson)
nginx: 1.22+ para frontend
systemd: gestión servicios warm
```

### Servicios warm 24/7

```
1. iuris-llm.service        → llama-server :8765 (Qwen3 4B + LoRA)
2. iuris-backend.service    → FastAPI + uvicorn :8000
3. iuris-frontend.service   → nginx :80 (sirve build React)
4. iuris-gmail-monitor      → cron cada 5 min, sync_inbox
```

### Servicios lazy on-demand

```
1. iuris-vlm                → llama-server :8766 (Qwen2-VL 2B + mmproj)
                              activa cuando document_normalizer detecta
                              imagen problemática, descarga 5 min idle
2. iuris-batch-extract      → tarea programada nocturna 3 AM,
                              re-procesa casos REVISION o sospechosos
```

### Modelos GGUF requeridos (en `/opt/iuris/models/`)

```
qwen3-4b-q4-iuris.gguf              ~3.0 GB  (LLM base)
iuris-lora-juridico-co.gguf         ~70 MB   (LoRA adapter)
qwen2-vl-2b-instruct-q4.gguf        ~1.5 GB  (VLM)
mmproj-qwen2-vl-2b-f16.gguf         ~1.3 GB  (VLM projector)
```

Total disco: ~6 GB modelos + ~2 GB datos cuantizados sklearn = ~8 GB.

---

## Configuración llama-server por tier

### Tier 1 — Nano 8GB (`--parallel 1`)

```bash
/opt/iuris/bin/llama-server \
    --model /opt/iuris/models/qwen3-4b-q4-iuris.gguf \
    --lora /opt/iuris/models/iuris-lora-juridico-co.gguf \
    --port 8765 --host 127.0.0.1 \
    --ctx-size 4096 \
    --n-gpu-layers 999 \
    --threads 4 \
    --parallel 1 \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --flash-attn on \
    --mlock \
    --chat-template chatml
```

RAM warm esperada: 4.2 GB

### Tier 2 — Orin NX 16GB (`--parallel 2`)

```bash
/opt/iuris/bin/llama-server \
    --model /opt/iuris/models/qwen3-4b-q4-iuris.gguf \
    --lora /opt/iuris/models/iuris-lora-juridico-co.gguf \
    --port 8765 --host 127.0.0.1 \
    --ctx-size 16384 \
    --n-gpu-layers 999 \
    --threads 6 \
    --parallel 2 \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --flash-attn on \
    --mlock \
    --chat-template chatml
```

RAM warm esperada: 6.5 GB

### Tier 3 — Premium (`--parallel 4`)

```bash
/opt/iuris/bin/llama-server \
    --model /opt/iuris/models/qwen3-4b-q4-iuris.gguf \
    --lora-init-without-apply \
    --lora /opt/iuris/models/iuris-lora-juridico-co.gguf \
    --port 8765 --host 127.0.0.1 \
    --ctx-size 32768 \
    --n-gpu-layers 999 \
    --threads 8 \
    --parallel 4 \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --flash-attn on \
    --mlock \
    --chat-template chatml
```

RAM warm esperada: 12 GB

---

## Configuración Backend Python por tier

### `.env` — variables críticas

```bash
# Common
USE_COGNITIVE_PIPELINE=true
LLM_LOCAL_PRIMARY=true
LLM_LOCAL_URL=http://127.0.0.1:8765
LOCAL_ONLY=true                         # nunca llamar APIs externas
USE_AI_EXTRACTION=true
LLM_LOCAL_MODEL_ID=qwen3-4b-iuris

# Tier 1 (Nano 8GB)
EXTRACTION_MAX_WORKERS=4
SYNC_BATCH_SIZE=50

# Tier 2 (Orin NX 16GB)
EXTRACTION_MAX_WORKERS=6
SYNC_BATCH_SIZE=100

# Tier 3 (Premium)
EXTRACTION_MAX_WORKERS=12
SYNC_BATCH_SIZE=200

# F2 confidence scoring (todos los tiers)
USE_FIELD_CONFIDENCE=true
CONFIDENCE_OK_THRESHOLD=0.85
CONFIDENCE_REVIEW_THRESHOLD=0.50

# PII modes
PII_MODE_DEFAULT=selective
```

---

## Servicio systemd para llama-server (boot automático)

`/etc/systemd/system/iuris-llm.service`:

```ini
[Unit]
Description=IURIS LLM Compilador (Qwen3 4B + LoRA)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=iuris
WorkingDirectory=/opt/iuris
ExecStart=/opt/iuris/start_llm.sh
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/iuris/llm.log
StandardError=append:/var/log/iuris/llm.log
LimitMEMLOCK=infinity
Nice=-5

[Install]
WantedBy=multi-user.target
```

Activar:
```bash
systemctl enable iuris-llm
systemctl start iuris-llm
journalctl -u iuris-llm -f    # monitoreo en vivo
```

---

## Layout filesystem appliance

```
/opt/iuris/
├── bin/
│   ├── llama-server                    # binario CUDA
│   ├── llama-cli                       # CLI debug
│   └── start_llm.sh                    # entrypoint con flags por tier
├── models/                             # GGUFs cuantizados
│   ├── qwen3-4b-q4-iuris.gguf
│   ├── iuris-lora-juridico-co.gguf
│   ├── qwen2-vl-2b-q4.gguf             # solo si tier ≥ 2
│   └── mmproj-qwen2-vl-2b-f16.gguf
├── tutelas-app/                        # backend Python
│   ├── backend/
│   ├── frontend/dist/                  # React build estático
│   ├── data/
│   │   ├── tutelas.db                  # SQLite (cifrada con LUKS)
│   │   ├── lora-models/                # adapters HF reentrenamiento
│   │   └── backups/
│   └── logs/
├── tutelas-data/                       # carpetas físicas casos
│   └── 2026-XXXXX [ACCIONANTE]/
└── system/
    ├── iuris-llm.service
    ├── iuris-backend.service
    ├── iuris-frontend.service
    └── iuris-gmail-monitor.timer

/etc/iuris/
├── env                                 # variables runtime
└── license.key                         # validación servidor central

/var/log/iuris/                         # rotated weekly
├── llm.log
├── backend.log
└── monitor.log
```

---

## Métricas de performance medidas (RunPod RTX 4090) y extrapoladas

| Operación | Pod RTX 4090 | Tier 2 NX 16GB est. | Tier 1 Nano 8GB est. |
|-----------|---------------|----------------------|------------------------|
| Ingest 1346 emails (paralelo) | 3.5 min | 8-12 min | 12-18 min |
| LLM 1 respuesta (Qwen3 4B Q4) | 0.4 s | 1.2-1.5 s | 2-3 s |
| Extracción cognitiva 1 caso | 14-18 s | 45-60 s | 60-90 s |
| VLM análisis 1 página | 1-2 s | 3-5 s | 6-10 s |
| Pipeline regex+forensic | <1 s | <1 s | <1 s |
| Throughput sostenido cases/h | 200+ | 60-80 | 20-30 |

---

## Empaquetado deployment (one-shot install)

### Script `install_iuris.sh` (ejecutable post-flash JetPack)

```bash
#!/bin/bash
set -e
INSTALL_DIR=/opt/iuris
sudo mkdir -p $INSTALL_DIR/{bin,models,tutelas-app,system}

# 1. Compilar llama.cpp con CUDA
cd /tmp && git clone --depth 1 https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=ON -DGGML_NATIVE=ON
cmake --build build -j 4 --target llama-server llama-cli
sudo cp build/bin/llama-server build/bin/llama-cli $INSTALL_DIR/bin/

# 2. Descargar modelos
cd $INSTALL_DIR/models
huggingface-cli download Qwen/Qwen3-4B-GGUF Qwen3-4B-Q4_K_M.gguf --local-dir .
mv Qwen3-4B-Q4_K_M.gguf qwen3-4b-q4-iuris.gguf
# LoRA: copiar desde wilsona@central:/iuris/lora/iuris-lora-qwen3-4b.gguf

# 3. Backend
cd $INSTALL_DIR/tutelas-app
git clone <iuris-repo> .
pip install -r requirements.txt

# 4. Schema DB
python3 -c "from backend.database.database import init_db; init_db()"

# 5. Activar servicios
sudo cp system/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable iuris-llm iuris-backend iuris-frontend
sudo systemctl start iuris-llm iuris-backend iuris-frontend

echo "✓ IURIS instalado y corriendo"
echo "  Frontend: http://localhost"
echo "  API:      http://localhost:8000"
echo "  LLM:      http://localhost:8765"
```

---

## Hardening producción

### 1. Cifrado at-rest

```bash
# DB en partición LUKS
cryptsetup luksFormat /dev/nvme0n1p2
mount /dev/mapper/iuris-data /opt/iuris/tutelas-app/data
```

### 2. Licenciamiento por MAC address

```python
# backend/auth/license_validator.py
import uuid, requests
mac = uuid.getnode()
license_status = requests.get(
    f"https://central.iuris.co/validate?mac={mac:012x}",
    timeout=5
).json()
if not license_status.get("valid"):
    sys.exit("License not valid")
```

### 3. Sello tornillería voiding

Sticker rojo manipulación en uno de los tornillos. Si cliente rompe → pierde garantía.

### 4. Auto-update controlado

```bash
# /etc/cron.weekly/iuris-update
curl -fsSL https://central.iuris.co/update.sh | bash
```

---

## Validación pre-entrega (checklist QA)

```
[ ] Ingest 100 emails sin errores
[ ] Extract 20 cases con ≥70% campos llenos
[ ] LLM responde <3s en hardware target
[ ] VLM lazy carga/descarga en <15s
[ ] Frontend Dashboard accesible :80
[ ] Chat agent responde queries naturales
[ ] systemctl status muestra todos verde
[ ] Burn-in 24h sin OOM ni crashes
[ ] DB cifrada con LUKS
[ ] License server contactable
[ ] Logs rotados configurados
[ ] Backup automático diario configurado
```

---

## Bill of Materials (BOM) Tier 2 — Orin NX 16GB

| Componente | Modelo | Costo USD | Proveedor |
|------------|--------|-----------|-----------|
| Computadora | Seeed reComputer J4012 (Orin NX 16GB + carrier + 128GB NVMe) | $1,250 | Seeed Studio |
| Carcasa branding | CNC aluminio mecanizado custom + grabado láser logo IURIS | $80-120 | Taller BMA |
| Cooler activo | (incluido en J4012) | $0 | — |
| SSD adicional | Samsung 980 PRO 256GB M.2 NVMe | $45 | MercadoLibre BMA |
| Cable HDMI + teclado setup | basic | $15 | local |
| Stickers branding | lote 50 | $20 | imprenta digital |
| Tornillería + cables | M3 inox + sello rojo | $15 | ferretería |
| Manual + caja premium | impresión digital | $25 | imprenta |
| **TOTAL BOM** | | **~$1,470** | |
| Envío internacional + nacionalización | DHL DDP a Bucaramanga | $250-350 | |
| **COSTO TOTAL nacionalizado** | | **~$1,720-1,820 USD** | **~$7-7.5M COP** |

**PVP recomendado**: $2,800 USD = $11.5M COP
**Margen bruto**: ~$1,000 USD = $4M COP por unidad (54%)

---

## Roadmap evolución del setup

| Versión | Hardware | Capacidad | Cuándo |
|---------|----------|-----------|--------|
| v1.0 | Pod RunPod RTX 4090 | Demo + tesis | **Ahora** (mientras valides ventas) |
| v1.1 | Pod + custom domain + SSL | Demo profesional | Pre-venta |
| v2.0 | Jetson Orin Nano Super 8GB | 1ra unidad piloto | Tras 1er cliente confirmado |
| v3.0 | Jetson Orin NX 16GB | Producto comercial | Tras financiación o 3 ventas |
| v4.0 | Strix Halo 128GB | Tier enterprise | Cliente gobernación grande |

---

## Mantenimiento del documento

Este doc se actualiza cada vez que:
- Cambien specs de hardware target (NVIDIA libera nuevo modelo)
- Cambie modelo LLM base (Qwen 3.5, 4B → 7B, etc.)
- Se descubran problemas de capacity en producción
- Se agreguen features que cambien el budget RAM/GPU

Última revisión: 2026-05-03 (sesión RunPod E2E)
Próxima revisión: tras 1er cliente piloto entregado
