# IURIS — Guía paso a paso RunPod LoRA training (versión optimizada)

> Objetivo: entrenar adapter LoRA `iuris-juridico-co` sobre Qwen3 4B en ~60-120 min, costo **$0.50-0.80 USD primera vez**, **$0.60-0.80 USD reentrenamientos** (con Network Volume cache).
>
> Output: archivo GGUF que se carga directo en `llama-server` local (warm 24/7).

---

## 🎯 Configuración óptima Wilson (revisada 2026-05-03)

| Item | Decisión | Razón |
|------|----------|-------|
| Cloud | **Community Cloud (spot)** | $0.34-0.44/hr vs $0.69-0.74/hr Secure (50% off) |
| GPU | **RTX 4090 24GB** | Suficiente para Qwen3 4B + LoRA con Unsloth, más barata que A40 |
| Tipo deploy | **Spot** | LoRA training es checkpoint-friendly. Si interrumpe, tmux + save_strategy=epoch te resucita |
| Storage | **Network Volume 50 GB** | $0.07/GB/mo, persiste para futuros LoRAs, S3 API sin pod activo |
| Datacenter | **US-KS-2 o US-CA-2** | S3-compatible API para gestión sin pod corriendo |
| Container disk | **20 GB temp** | Solo para OS + workspace temporal |
| Template | `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` | Pre-instala torch CUDA, ahorra 5 min |
| Script | **runpod_train_lora.sh + Unsloth** | 2× más rápido que TRL puro, ahorra 30-60 min compute |
| Ejecución | **dentro de tmux** | Permite cerrar laptop, resume si te desconectas |

**Costo total estimado primera vez**: ~$0.78 (training $0.59 + storage 1 día $0.01 + buffer setup)
**Costo reentrenamiento** (Network Volume ya tiene cache): ~$0.59 training only.

---

## ⛔ Lo que NO debes elegir

| Opción | Por qué no |
|--------|------------|
| **Managed Fine-Tuning service** ($199/mes) | 300× más caro. Sin Unsloth (más lento). Sin control de hyperparams. |
| **Secure Cloud RTX 4090** ($0.69/hr) | 50% más caro. Solo justifica si producción enterprise. |
| **Volume Disk** | $0.10/GB running, **$0.20 stopped** (peor). No reusable. |
| **Serverless H100s** ($5.59/hr) | 20× markup vs on-demand. Solo para inferencia, NO training. |
| **Datacenter Asia o EU para tu caso** | Más latency desde Colombia, sin ventaja precio. |
| **Pod sin tmux** | Cerrar terminal = matar training. Plata perdida. |
| **GPU H100** ($2.69-2.99/hr) | Overkill para Qwen3 4B + LoRA. RTX 4090 alcanza. |

---

## ⏱️ Timeline esperado

| Fase | Tiempo | Costo |
|------|--------|-------|
| Spin up pod + setup | 5-10 min | $0.05 |
| Upload dataset (2.6 MB) | 1-3 min | $0.01 |
| Install deps Unsloth | 5-10 min | $0.05 |
| Training (3 epochs) | 60-120 min | $0.30-0.70 |
| Export GGUF + tarball | 5 min | $0.03 |
| Download tarball | 1-3 min | $0.01 |
| **TOTAL** | **~80-150 min** | **~$0.50-0.90** |

---

## Paso 0 — Crear Network Volume PRIMERO (antes que el pod)

Esto es key: el volumen debe existir antes de spinear el pod, porque el volumen NO se puede attach después.

1. Ir a https://www.runpod.io/console/user/storage
2. Click **+ New Network Volume**
3. Configuración:
   - **Datacenter**: US-KS-2 (Kansas) o US-CA-2 (California) — tienen **S3 API** que sirve para futuro
   - **Size**: 50 GB
   - **Name**: `iuris-lora-vol`
4. Click **Create Volume**
5. Costo: $0.07/GB/mo × 50 = **$3.50/mes** mientras lo conserves (cancelable cuando ya no lo necesites)

## Paso 1 — Spin up pod

1. Ir a https://runpod.io/console/pods
2. Click **Deploy**
3. **CRÍTICO**: filtrar **Community Cloud** (no Secure Cloud) para precio spot
4. Configuración:
   - **GPU**: RTX 4090 24GB → debería mostrar **$0.34-0.44/hr** (Community Cloud)
   - **Region**: misma del Network Volume (US-KS-2 o US-CA-2)
   - **Template**: `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`
     - Si no lo encuentra, buscar "PyTorch 2.4 CUDA 12.4"
   - **Container Disk**: 20 GB (temp, suficiente para OS)
   - **Network Volume**: seleccionar `iuris-lora-vol` (creado en Paso 0)
   - **NO seleccionar Volume Disk** (es la opción cara)
5. Click **Deploy** (será spot, no on-demand — pagas solo lo que usas)
6. Esperar status "Running" (1-3 min)
7. **Verificar precio**: la pantalla "Pricing summary" debería decir **GPU cost $0.34-0.44/hr** (no $0.69/hr)

---

## Paso 2 — Conectar al pod

**Opción A: Web Terminal** (más fácil)
1. En la página del pod, click **Connect** → **Start Web Terminal**
2. Se abre terminal en navegador

**Opción B: SSH** (más robusto, recomendado)
1. Click **Connect** → copy SSH command (algo como `ssh root@123.456.78.90 -p 12345 -i ~/.ssh/id_ed25519`)
2. Asegurate que tu pubkey esté agregada en RunPod settings (Tu pubkey ya está guardada según memoria: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...wilsonderecho1@gmail.com`)
3. En tu local: pegar el ssh command. Te conecta como root al pod.

---

## Paso 3 — Subir dataset

Tienes 3 opciones, elige una:

### Opción A — SCP desde tu local (más simple)

En **otra terminal local** (no en el pod), corré:

```bash
cd "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app"

# Copia el comando SSH del pod, reemplaza port y IP
scp -P <pod_port> data/iuris_lora_dataset.jsonl root@<pod_ip>:/workspace/
scp -P <pod_port> data/iuris_lora_dataset_val.jsonl root@<pod_ip>:/workspace/
scp -P <pod_port> scripts/runpod_train_lora.sh root@<pod_ip>:/workspace/
```

Tamaño: 2.9 MB total. Tarda 5-30 segundos según conexión.

### Opción B — HuggingFace Hub (más limpio, persiste)

```bash
# En tu local
huggingface-cli login   # solo primera vez
huggingface-cli upload-large-folder \
    wilsonarguello/iuris-lora-data \
    data/ \
    --repo-type=dataset \
    --private

# En el pod (en Paso 4)
huggingface-cli download wilsonarguello/iuris-lora-data \
    --repo-type=dataset \
    --local-dir /workspace/
```

### Opción C — wget desde URL pública (rápido pero datos quedan abiertos)

Solo si datos no son sensibles. NO recomendado para corpus jurídico.

---

## Paso 4 — Ejecutar training

En el pod (web terminal o SSH):

```bash
cd /workspace
chmod +x runpod_train_lora.sh
bash runpod_train_lora.sh 2>&1 | tee training.log
```

El script hace:
1. Verifica GPU
2. Verifica dataset
3. Instala Unsloth + dependencias (5-10 min)
4. Carga Qwen3 4B en 4-bit
5. Entrena LoRA (60-120 min)
6. Exporta GGUF para llama-server
7. Empaqueta tarball para descarga

**Ojo**: cerrar la terminal MATA el proceso. Si usas web terminal, **mantenelo abierto**.

**Mejor**: usar `tmux` o `screen` para que el training corra en background:

```bash
tmux new -s iuris
# dentro de tmux:
bash runpod_train_lora.sh 2>&1 | tee training.log
# Ctrl+B luego D para "detach" — podés cerrar el navegador
# tmux attach -t iuris   ← para volver a ver
```

---

## Paso 5 — Monitorear training

En el pod, en otra terminal (o tmux pane):

```bash
tail -f /workspace/training.log
```

Vas a ver algo como:
```
{'loss': 1.234, 'learning_rate': 1.95e-04, 'epoch': 0.05}
{'loss': 0.987, 'learning_rate': 1.85e-04, 'epoch': 0.15}
...
{'eval_loss': 0.654, 'eval_runtime': 12.3, 'epoch': 1.0}
```

**Loss debería bajar progresivamente**. Si se estanca o sube, problema con el dataset o config.

---

## Paso 6 — Descargar adapter

Una vez completado, en tu local:

```bash
cd "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app"
mkdir -p data/lora-models

# SCP desde pod
scp -P <pod_port> root@<pod_ip>:/workspace/iuris-lora-qwen3-4b.tar.gz data/lora-models/

# Extraer
cd data/lora-models
tar xzf iuris-lora-qwen3-4b.tar.gz
ls -lh iuris-lora-qwen3-4b/
ls -lh iuris-lora-qwen3-4b_gguf/
```

Tamaño esperado: 100-300 MB (LoRA es ligero).

---

## Paso 7 — APAGAR el pod (importante para no quemar plata)

```bash
# En la consola RunPod:
# Click pod → Stop
```

O en el pod mismo:
```bash
runpodctl stop pod  # si está instalado
```

**Costo si te olvidas: $0.34-0.39 por hora corriendo en idle.** Apagá el pod cuando termine.

---

## Paso 8 — Cargar LoRA en llama-server local

Una vez tengas el GGUF descargado:

```bash
# Compilar llama.cpp moderno (si no lo tienes)
cd ~
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=OFF -DGGML_NATIVE=ON
cmake --build build -j 4 --config Release

# Descargar Qwen3 4B base GGUF
cd ~/iuris-models
huggingface-cli download Qwen/Qwen3-4B-GGUF Qwen3-4B-Q4_K_M.gguf --local-dir qwen3-4b/

# Lanzar llama-server warm con LoRA
~/llama.cpp/build/bin/llama-server \
    --model ~/iuris-models/qwen3-4b/Qwen3-4B-Q4_K_M.gguf \
    --lora ./iuris-lora-qwen3-4b_gguf/iuris-lora.gguf \
    --port 8765 \
    --host 127.0.0.1 \
    --ctx-size 8192 \
    --threads 4 \
    --flash-attn \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --mlock \
    --chat-template chatml
```

Test del endpoint:
```bash
curl http://localhost:8765/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "messages": [
            {"role": "system", "content": "Eres asistente jurídico colombiano."},
            {"role": "user", "content": "¿Cuál es el sentido del fallo si dice NEGAR? Una palabra."}
        ],
        "max_tokens": 20
    }'
```

Esperado: `NIEGA` o similar respuesta corta.

---

## Troubleshooting

### "CUDA out of memory" durante training
- Bajar `BATCH=1` y `GRAD_ACCUM=8` (mismo effective batch)
- O bajar `MAX_LEN=1024`
- O usar A40 48GB en vez de RTX 4090 24GB

### Loss no baja
- Verificar dataset está bien formateado (`head -1 dataset.jsonl | jq`)
- Subir `LR=3e-4` (más agresivo)
- Bajar `LORA_R=8` (menos params, evita overfit)

### Pod RunPod corre interrumpido
- Usar **on-demand** en vez de spot/community
- Usar tmux para que el training sobreviva desconexión

### GGUF export falla
- No problem, el adapter HF queda en `iuris-lora-qwen3-4b/`
- Convertir manualmente con `llama.cpp/convert_lora_to_gguf.py`

---

## Costo total esperado (Community Cloud spot)

| Concepto | USD |
|----------|-----|
| Pod RTX 4090 spot × 2h × $0.39/hr | **$0.78** |
| Network Volume 50GB × 2h | $0.01 |
| Bandwidth download | $0.00 (zero egress fees) |
| Setup install pre-cache | $0.10 (una vez) |
| **TOTAL primera vez** | **~$0.90** |
| **Reentrenamiento (volumen ya tiene cache)** | **~$0.79** |

Storage mensual continuo (después del training, mientras conserves el volumen):
- 50 GB × $0.07/GB/mo = **$3.50/mes**

Si querés CERO costo recurrente:
- Después del training, descargar el adapter, **borrar el Network Volume**
- Próxima vez recreás todo (10 min extra de setup)

---

## 🔑 Optimizaciones avanzadas (después del primer training exitoso)

### 1. Pre-cache modelo + deps en Network Volume

Después del primer training exitoso, el Network Volume ya tiene:
- Qwen3 4B base (~2.5 GB descargado de HuggingFace)
- Unsloth + dependencies (~3 GB pip cache)
- Tu dataset

**En futuras corridas** (otro LoRA, reentrenamiento), simplemente:
1. Spin up nuevo pod con el mismo Network Volume
2. `cd /workspace && bash runpod_train_lora.sh`
3. Los pip install ya están cacheados, el modelo ya descargado
4. Training arranca en 30 segundos en vez de 10 minutos

**Ahorro**: ~$0.10 por reentrenamiento (10 min × $0.39/hr).

### 2. Spot interruption recovery

Si el spot pod te interrumpe a mitad del training (raro pero posible):
1. tmux + `save_strategy="epoch"` ya guardan checkpoint cada epoch
2. Spin nuevo pod con mismo volumen
3. Modify `train.py` agregar `resume_from_checkpoint=True`
4. Resume desde último epoch guardado

### 3. S3 API para gestionar archivos sin pod corriendo

Cuando el pod está apagado, podés:
- Subir archivos al volumen
- Bajar el adapter sin pagar GPU idle
- Backup del adapter a tu local

```bash
# Configurar S3 API (una vez)
# RunPod console → Network Volume → S3 endpoint
# Te da: endpoint URL + access key + secret

# Usar con awscli
aws s3 ls --endpoint-url https://s3api-us-ks-2.runpod.io s3://iuris-lora-vol/
aws s3 cp --endpoint-url https://s3api-us-ks-2.runpod.io s3://iuris-lora-vol/iuris-lora-qwen3-4b.tar.gz .
```

**Ahorro**: descargar 200MB adapter sin gastar $0.39/hr. Solo cobran storage estática.

### 4. Multi-LoRA en el mismo volumen

Una vez tengas el setup funcionando, podés entrenar varios adapters reusando todo:

```bash
# En el pod, después de primer LoRA exitoso
DATASET=/workspace/iuris_redaccion_dataset.jsonl \
OUTPUT_DIR=/workspace/iuris-lora-redaccion \
bash runpod_train_lora.sh
```

Hot-swap LoRAs en `llama-server` local sin reload del modelo base:
```
POST /v1/lora { "path": "/path/to/extraccion.gguf" }    # cambia adapter
```

### 5. Monitoreo GPU para no quemar plata idle

Mientras corre training, en otra ssh session:
```bash
nvidia-smi -l 1
```

Si GPU utilization es <50% sostenido → algo está mal (CPU bottleneck o I/O). Mata el job, debug, restart. NO dejes que un pod corra a 10% utilization durante 2 horas.

### 6. runpodctl CLI (auto-stop)

```bash
# En tu local
brew install runpod/tap/runpodctl  # o curl install
runpodctl config --apiKey <tu_api_key>

# Comandos útiles
runpodctl start pod <pod-id>
runpodctl stop pod <pod-id>
runpodctl get pods
runpodctl get logs <pod-id>

# Auto-stop después de N horas (importante!)
runpodctl create pod --gpu RTX4090 --auto-shutdown 3h ...
```

**Auto-shutdown te salva del olvido fatal**.

---

## Comparación final: tu opción vs lo que mostraban las pantallas

| Item | Lo que viste en pantalla (Secure) | Lo que recomiendo (Community) | Ahorro |
|------|-------------------------------------|--------------------------------|--------|
| GPU/hr | $0.69 | $0.39 | **44%** |
| Storage | Volume Disk $0.10/$0.20 | Network Volume $0.07 | **30-65%** |
| Total 2h training | $1.40 | **$0.79** | **$0.61** |

Y el managed Fine-Tuning service de RunPod ($199/mes) está **descartado**: pagás 250× más por menos control y sin Unsloth.

---

## Resumen acción inmediata Wilson

1. ✅ Login RunPod
2. ✅ Spin up pod RTX 4090 24GB con template PyTorch 2.4 CUDA 12.4
3. ✅ Subir 3 archivos vía SCP:
   - `data/iuris_lora_dataset.jsonl`
   - `data/iuris_lora_dataset_val.jsonl`
   - `scripts/runpod_train_lora.sh`
4. ✅ `bash runpod_train_lora.sh` dentro de tmux
5. ✅ Esperar 60-120 min (podés cerrar navegador con tmux detach)
6. ✅ Descargar tarball cuando complete
7. ✅ **APAGAR EL POD**
8. ✅ Cargar LoRA en `llama-server` local

Total tu tiempo activo: ~15 min. Resto es esperar.

---

## Próxima sesión post-training

Cuando tengas el adapter GGUF descargado, próxima sesión:
1. Setup `llama-server` en tu workstation (warm 24/7)
2. Reescribir `backend/agent/smart_router.py` para apuntar a `localhost:8765`
3. Bench post-LoRA: 5 prompts jurídicos sobre OCR real → meta ≥4/5 strict
4. Bench end-to-end: 50 casos sin API externa
5. Decisión hardware final con datos reales en mano
