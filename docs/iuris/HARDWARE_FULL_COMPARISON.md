# IURIS — Comparativa Hardware EXHAUSTIVA (2026-05-03)
> Reemplaza FINAL_DECISION.md (que era prematuro). Esta es la versión honesta y completa.

---

## Hipótesis a validar antes de comprar

Antes de elegir hardware, primero hay que decidir **qué tipo de producto** es IURIS:

1. **All-in-one appliance** (1 dispositivo procesa todo: OCR + cognición + LLM)
2. **Brain + accelerator** (CPU host + chip dedicado para LLM)
3. **Co-processor distribuido** (microcontroladores + servidor central pequeño)
4. **Service play** (app móvil + servidor central, hardware del cliente)

Cada hipótesis cambia el ganador.

---

## Tabla 1 — Todas las opciones investigadas (10 caminos reales)

| # | Plataforma | BOM USD | Compute IA | RAM LLM | OCR | Tok/s LLM | Power | Pros | Contras |
|---|------------|---------|-------------|---------|-----|-----------|-------|------|---------|
| 1 | **Jetson Orin Nano Super 8GB** | $249-415 | 67 TOPS GPU CUDA | ~6.5GB | TensorRT acelerado | 14-15 (Llama 7B Q4) | 7-25W | CUDA stack, NVIDIA Inception, ecosistema maduro | RAM techo, single-stream |
| 2 | **Pi 5 8GB + Hailo-10H** | $195 (kit completo) | 40 TOPS INT4 NPU | 4-8GB on-module | CPU only (lento) | 6.9 (Qwen 1.5B) - 9.45 | 5-8W | Más barato standalone LLM, dedicado NPU LPDDR4 | Sin GPU para OCR; pipeline 2-3× más lento end-to-end |
| 3 | **Pi 5 8GB + Hailo-8 (no LLM)** | $150 | 26 TOPS INT8 | sin LPDDR | n/a (sin LLM) | n/a | 4-7W | barato | NO sirve para LLM (memoria interna) |
| 4 | **RK3588 mini PC (Orange Pi 5+)** | $150-180 | 6 TOPS NPU + GPU Mali | 16-32GB | CPU/GPU Mali | 10-15 (TinyLlama 1.1B) | 5-6W | Súper barato, RAM grande, RKLLM ecosystem | Calidad LLM 1.1B sub-óptima jurídicamente |
| 5 | **AMD Ryzen AI 9 HX 370 mini PC** | $999 (Beelink SER9) | 50 TOPS NPU + 80 TOPS hybrid | 28GB | iGPU 890M | 17-20 (8B hybrid) | 28-54W | RAM grande, modelos 13B sin sudar | Caro, sin Inception, sin CUDA |
| 6 | **Strix Halo 128GB (Framework)** | $2,599 | 50 TOPS NPU + 256 GB/s mem | ~110GB | iGPU RDNA 3.5 | 19 (122B Q4) | 80-120W | Rango premium, modelos 70B+ | Precio fuera de mercado personería |
| 7 | **ThinkCentre Tiny refurb + BitNet** | $250-350 | CPU only (Intel i7-8/9/10) | 16-32GB | CPU only | 5-7 (BitNet 2B) | 25-65W | Mínimo costo, brand neutro | Old hardware, mensaje comercial débil |
| 8 | **ESP32-S3 N16R8 from scratch** | $15-30 (board) | LX7 dual core 240MHz | 8MB PSRAM | imposible (memory) | 19 (260K params TinyStories) | 0.5-2W | Disruptivo, ultra cheap | NO viable como appliance jurídico solo (modelos 260K-15M params no razonan derecho) |
| 9 | **Old Snapdragon 8 Gen 2 phone (used)** | $300-400 | Hexagon NPU + Adreno | 8-12GB | CPU/GPU Mali | 15-25 (Llama 3B int4 vía QNN) | 3-8W (battery) | Pantalla integrada, batería, NPU moderna | Closed ecosystem, no Linux server, no legal whitelabel |
| 10 | **Mac mini M4 24GB** | $700-800 | 38 TOPS Neural Engine | ~20GB | Metal acelerado | 28-30 (Llama 8B Q4) | 5-30W | Mejor performance puro | **Apple PROHÍBE whitelabel comercial** |

---

## Tabla 2 — Filtro por compatibilidad con tutelas-app actual

Pipeline tutelas-app v6 requiere:
- **PaddleOCR** (mejor con CUDA, aceptable con CPU+OpenVINO)
- **Cognición 7 capas** (Python puro, corre en cualquier CPU ARM/x86)
- **LLM** para 5 campos cognitivos (~50 tokens output cada uno)
- **SQLite + FastAPI + frontend React** (cualquier OS)

| # | Plataforma | tutelas-app refactor | Tiempo migración | Riesgo técnico |
|---|------------|---------------------|------------------|----------------|
| 1 | Jetson Orin Nano Super | Drop-in (CUDA nativo) | 0 días | Bajo |
| 2 | Pi 5 + Hailo-10H | OCR pasa a CPU+OpenVINO; LLM via Hailo SDK | 1-2 semanas | Medio (Hailo SDK joven) |
| 4 | RK3588 mini PC | OCR pasa a Mali GPU; LLM via RKLLM | 2-3 semanas | Medio-Alto |
| 5 | AMD HX 370 mini PC | OCR pasa a iGPU; LLM via Lemonade (preview) | 2-3 semanas | Medio |
| 6 | Strix Halo | Idem 5 + tuning Vulkan/ROCm | 2-3 semanas | Medio |
| 7 | ThinkCentre + BitNet | bitnet.cpp solamente; OCR CPU | 1 semana | Bajo |
| 8 | ESP32-S3 | **Reescritura completa** del pipeline | meses | **Alto — no viable** |
| 9 | Phone Snapdragon | App Android nueva, Termux + llama.cpp | meses | Alto |
| 10 | Mac mini M4 | MLX port + descart legal Apple | n/a | Legal blocker |

---

## Tabla 3 — Costo total real (incluyendo tiempo de migración valorizado a $50/h Wilson)

| # | Plataforma | BOM | Tiempo migración | Costo migración | **TOTAL real** |
|---|------------|-----|------------------|-----------------|----------------|
| 1 | Jetson Orin Nano Super | $415 | 0h | $0 | **$415** |
| 2 | Pi 5 + Hailo-10H | $195 | 60h | $3,000 | $3,195 |
| 4 | RK3588 mini PC | $180 | 100h | $5,000 | $5,180 |
| 5 | AMD HX 370 | $1,000 | 100h | $5,000 | $6,000 |
| 7 | ThinkCentre + BitNet | $300 | 40h | $2,000 | $2,300 |

**Conclusión sobria**: incluyendo costo de oportunidad, **Jetson sigue siendo la opción más rentable a corto plazo**, pero la diferencia con ThinkCentre+BitNet es solo $1,885 — y ese path es donde está la innovación de margen real.

---

## Reformulación honesta: ¿qué hacer?

### Opción A — Jetson como flagship único
- Comprar 1-2 Jetson, validar BitNet sobre Jetson (CPU ARM o GPU CUDA), lanzar IURIS Pro con Inception badge.
- **Riesgo**: si Hailo o RK3588 maduran rápido, IURIS Pro queda overpriced.

### Opción B — Doble plataforma desde día 1
- IURIS Pro = Jetson ($1,800 PVP, fast track)
- IURIS Lite = Pi 5 + Hailo-10H ($999 PVP, mismo precio que Apple Watch)
- **Riesgo**: 2 stacks de software a mantener; bug en uno no se replica en otro

### Opción C — Esperar 90 días, validar BitNet en workstation actual
- Antes de comprar nada, instalar bitnet.cpp en tu workstation y probar sobre 50 casos del corpus.
- Si BitNet alcanza ≥85% calidad de DeepSeek → arquitectura "any modern CPU" abre opciones radicalmente más baratas.
- Si NO alcanza → comprar Jetson con confianza porque CUDA + Llama es la única opción.

### Opción D — Arduino/ESP32 como diferenciador adicional (NO como brain principal)
- ESP32-S3 puede ser un **dongle USB de auditoría in-field** que un fiscal usa en una audiencia para checar radicados al vuelo.
- IURIS Pocket: $30 BOM, vendible como add-on a $150 con software custom.
- NO sirve como cerebro principal del appliance, pero es producto vendible adicional.

---

## Update 2026-05-03: insight KV-cache q8 + Flash Attention + MoE expert offload

Wilson trajo este comando del facebook de un amigo:
```
llama-server --model Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf -c 131072 -n 32768 \
  --no-context-shift --temp 0.6 --top-p 0.95 --top-k 20 \
  --fit on -fa on -ctk q8_0 -ctv q8_0
```

Las técnicas son reales y verificadas:
- `-ctk/-ctv q8_0` = mitad de VRAM en KV cache, calidad casi idéntica
- `-fa on` = flash attention, otro 30% menos de VRAM en attention
- `Q4_K_XL` Unsloth Dynamic = mayor fidelidad que Q4 estándar
- MoE A3B = solo 3B params activos por token

**El "secreto" final** no está en el comando: es el flag `-ot` (expert offloading) que mantiene los expertos inactivos en RAM del sistema, no en VRAM. Por eso un GPU 12GB + 32GB RAM corren un modelo de 35B.

### Aplicación a cada plataforma IURIS

| Plataforma | Memoria | ¿Corre 30B-A3B con tricks? | Modelo recomendado |
|------------|---------|----------------------------|---------------------|
| Jetson Orin Nano Super 8GB | 8GB unified (sin offload posible) | ❌ no cabe | Qwen3 4B Q4 + KV q8 + flash → 32-64K context |
| **Jetson Orin NX 16GB** | **16GB unified** | **✅ tight pero cabe** | **Qwen3 30B-A3B-Q4_K_XL** (calidad jurídica top) |
| RTX 4060 12GB + 32GB RAM | 44GB pool | ✅ cómodo con `-ot` | Qwen3 30B-A3B + KV q8 |
| Strix Halo 128GB | 128GB unified | ✅ cómodo | Cualquiera, hasta Llama 70B |
| RK3588 mini PC 16-32GB | 16-32GB system | ❌ NPU 6 TOPS muy lento para 30B | TinyLlama 1.1B vía RKLLM |
| Pi 5 + Hailo-10H 8GB | 8GB on-module | ❌ no cabe | Qwen 1.5B Q4 (6.9 tok/s) |
| ThinkCentre + BitNet | 16-32GB system | irrelevante (BitNet es 2B) | BitNet b1.58 2B4T |

### Bug crítico Jetson Orin (SM87)

llama.cpp tiene bug confirmado: **MoE decode hangs en Jetson Orin después de commit b7309 (dic 2025)**. Afecta a Nano y NX. Workaround: pinar a b7309 hasta que NVIDIA arregle. No bloquea adopción pero es deuda técnica.

---

## Cinco SKUs candidatos finales (con KV-cache tricks aplicados)

| SKU | Hardware | LLM | BOM | PVP | Margen | Calidad jurídica |
|---|---|---|---|---|---|---|
| **IURIS Lite Nano** | Orin Nano Super 8GB | Qwen3 4B Q4 + KV q8 / BitNet 2B | $415 | $1,500 | 72% | media |
| **IURIS Pro NX** | Orin NX 16GB | Qwen3 30B-A3B con KV q8 + flash | $1,400 | $2,800 | 50% | **alta** |
| **IURIS Edge** | RK3588 mini PC | TinyLlama Q4 vía RKLLM | $250 | $999 | 75% | baja-media |
| **IURIS Workstation** | RTX 4060 12GB tower | Qwen3 30B-A3B + offload | $700 | $1,800 | 60% | alta (no portable) |
| **IURIS Max** | Strix Halo 128GB | Llama 70B+ | $2,800 | $4,500 | 38% | premium |

**Decisión hardware DEPENDE de validación BitNet**:
- Si BitNet 2B ≥85% calidad de Qwen3 30B sobre tu corpus → **IURIS Lite Nano** es flagship ($415 BOM)
- Si BitNet 70-85% → híbrido: Pro NX para clientes premium, Lite Nano para personerías
- Si BitNet <70% → **IURIS Pro NX** flagship único ($1,400 BOM)

---

## Mi recomendación honesta (revisada)

**Opción C primero, después decisión.** Antes de gastar $415 en Jetson o $195 en Pi+Hailo:

1. **Esta semana** instalo `bitnet.cpp` + BitNet 2B4T en tu workstation actual.
2. **Corro batch sobre 50 casos** del corpus dorado tutelas-app.
3. **Mido tres cosas**:
   - Calidad de extracción para los 5 campos cognitivos (vs DeepSeek baseline)
   - Latencia por caso end-to-end
   - RAM peak
4. **Con esos datos, decido**:
   - Si BitNet ≥85% calidad → cualquier hardware moderno sirve, elijo el más barato (RK3588 $180 o ThinkCentre refurb $300)
   - Si BitNet 70-85% → híbrido: BitNet para 70% de campos, Llama 8B vía Jetson para los críticos
   - Si BitNet <70% → Jetson + Llama 8B Q4 (camino seguro)

**Costo del experimento: $0 + 6h de mi trabajo**. Esto evita comprar hardware equivocado.

---

## Estado real de los campos pendientes (corrección honesta)

| Campo | Cobertura previa | Estado | Lo que falta |
|-------|------------------|--------|---------------|
| `forest_impugnacion` | 0% | Código integrado (B.1), batch real **NO** ejecutado todavía (pod caído) | Validar contra 50 casos cuando tengamos compute |
| `responsable_desacato` | 7.5% | Sin cambios | Patrones nuevos en `decision_extractor` (B.2 pendiente) |
| `decision_incidente` | 9.4% | Sin cambios | Patrones para "RESUELVE", "DECRETA"… (B.3 pendiente) |
| `quien_impugno` | 28.6% | Sin cambios | Mejor heurística contextual (B.4 pendiente) |
| `juzgado_2nd` | 46% | Sin cambios | Más patrones tribunal/sala (B.5 pendiente) |

**Conclusión**: solo B.1 está en código (no validado). B.2-B.5 siguen exactamente como antes. Mi reporte previo de "5 campos con cobertura <50% sin LLM" sigue vigente — no hubo curación real, solo scaffolding.

---

## Decisiones que pido (sin presión a comprar nada)

1. ¿Vamos por **Opción C** (validar BitNet primero, gratis, 6h de trabajo) antes de decidir hardware?
2. ¿Cierro **B.2-B.5** ahora (4-6h) para tener todos los quick wins de extracción listos antes de mover hardware?
3. ¿O priorizo **F2 batch sobre 295 casos persistir** (no solo dry-run) para tener datos reales de calidad de extracción que después comparamos contra BitNet?

Cualquiera de las 3 es valiosa. La 1 abre opciones de hardware más baratas. La 2 te da producto más sólido. La 3 te da baseline empírico.

¿Cuál arrancamos?

---

## Fuentes investigación 2026-05-03
- [Hailo-10H Edge AI With On-Device LLMs](https://awesomeagents.ai/hardware/hailo-10h/)
- [Raspberry Pi AI HAT+ 2 Generative AI](https://www.raspberrypi.com/news/introducing-the-raspberry-pi-ai-hat-plus-2-generative-ai-on-raspberry-pi-5/)
- [LLM Inference Edge: Mobile NPU GPU Trade-offs (arXiv 2603.23640)](https://arxiv.org/html/2603.23640)
- [Rockchip RK3588 NPU Deep Dive](https://tinycomputers.io/posts/rockchip-rk3588-npu-benchmarks.html)
- [RKLLM toolkit GitHub](https://github.com/airockchip/rknn-llm)
- [DaveBben/esp32-llm GitHub](https://github.com/DaveBben/esp32-llm)
- [Run Tiny Language Model on ESP32 (Hackster)](https://www.hackster.io/asadshafi5/run-tiny-language-model-on-esp32-8b5dd8)
- [Cactus AI Engine Mobile Inference](https://www.blog.brightcoding.dev/2026/04/02/cactus-ai-engine-the-revolutionary-mobile-inference-framework)
- [Run Local AI on Android 2026](https://dev.to/alichherawalla/how-to-run-local-ai-on-your-android-phone-in-2026-no-cloud-no-account-5cbp)
- [Hardware optimization Android AI inference (arXiv 2511.13453)](https://arxiv.org/html/2511.13453)
