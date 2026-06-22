# IURIS — Arquitectura FULL LOCAL (2026-05-03)

> Objetivo: tutelas-app corriendo 100% en hardware del cliente. Cero datos salen del dispositivo. Cero APIs externas. Cero GPU dedicada requerida.

---

## TL;DR — Lo que descubrimos

1. **Tu pipeline ya es 90% CPU-only**. Audit confirma: PaddleOCR `use_gpu=False`, Marker `device="cpu"`. Solo PaddleOCR-VL (opt-in) usaba GPU del pod.
2. **El problema NO es costo API** ($1.06 USD histórico, $0.0027/caso). El problema es **latencia (45-217 seg/llamada)** + **Habeas Data** (datos jurídicos van a US).
3. **Reemplazar APIs por LLM local** quita 45-200 segundos por caso y blinda Habeas Data.
4. **Dataset LoRA ya generado**: 2,585 ejemplos (2326 train + 259 val) listo en `data/iuris_lora_dataset.jsonl` para entrenar tu modelo.

---

## Audit completo del setup actual

### Componentes que usan GPU local
| Componente | Estado actual | GPU? | Impacto |
|------------|----------------|------|---------|
| PaddleOCR clásico | `use_gpu=False` | ❌ CPU | OK |
| Marker (PDF→md) | `device="cpu"` | ❌ CPU | OK |
| PaddleOCR-VL 1.5 | opt-in flag, requiere CUDA 12.6+ | ✅ solo si pod | **Eliminar dependencia pod** |
| pdftext / pdfplumber | C++ extraction | ❌ CPU | OK |
| Tesseract fallback | CPU | ❌ CPU | OK |
| sklearn classifiers (ML) | CPU | ❌ CPU | OK |

### Componentes que usan APIs externas
| Componente | Llamadas históricas | Latencia avg | Costo |
|------------|---------------------|--------------|-------|
| DeepSeek (smart_router primary) | 361 | 56.8 s | $1.05 |
| Google Gemini (legacy) | 289 | 44.6 s | $0 (free tier) |
| Anthropic Claude Haiku (fallback) | 2 | 217.5 s | $0.01 |
| **Total** | **652** | **avg ~50s** | **$1.06** |

**Costo medio por caso: $0.0027 USD** — irrelevante. La motivación de full-local es **latencia + privacidad**, no dinero.

---

## Arquitectura propuesta (todas las capas)

```
┌─────────────────────────────────────────────────────────────────────┐
│                       IURIS — FULL LOCAL                            │
│                                                                     │
│  ┌─────────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │   Ingesta   │──→│  Normalizer  │──→│  Capa Cognitiva 0-7    │  │
│  │ Gmail/folder│   │  (CPU only)  │   │  (regex + forensic)    │  │
│  └─────────────┘   └──────────────┘   └────────────────────────┘  │
│         │                  │                       │                │
│         ▼                  ▼                       ▼                │
│   - email_id parse   - pdftext (CPU)         - 80% determinista    │
│   - thread match     - PP-OCRv5 mobile INT8  - regex zonal         │
│   - rad23 canonic    - Tesseract fallback    - Bayesian assignment │
│                                              - confidence scoring  │
│                                                                     │
│                                              │                      │
│                                              ▼                      │
│                                    ┌─────────────────────┐          │
│                                    │  LLM cognitive_fill │          │
│                                    │  (campos huecos)    │          │
│                                    └─────────────────────┘          │
│                                              │                      │
│                                              ▼                      │
│                            ┌──────────────────────────────────┐    │
│                            │  BitNet 2B + LoRA jurídico ES    │    │
│                            │   o Qwen3 4B Q4 + LoRA           │    │
│                            │  (local, sin API, ~5-15 tok/s)   │    │
│                            └──────────────────────────────────┘    │
│                                              │                      │
│                                              ▼                      │
│                                       Persist + UI                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Plan de cuantización/optimización por capa

### 1. OCR: PaddleOCR PP-OCRv5 mobile + INT8

**Estado actual**: PP-OCRv4 server, FP32, 8-12s init, 0.5-2s por página
**Target**: PP-OCRv5 mobile, INT8 ONNX, init 73% menor (≈3 seg), 30-50% menos latencia
**Cómo**:
- Descargar `PP-OCRv5_mobile_det` + `PP-OCRv5_mobile_rec` quantized models
- Convertir a ONNX si no vienen en formato
- Ejecutar con `onnxruntime` provider `CPUExecutionProvider` (Intel) o `OpenVINOExecutionProvider` (i5-1334U Intel = ideal)
- Settings flag: `NORMALIZER_OCR_INT8: bool = True`

**Alternativa disruptiva**: Qwen2.5-VL-3B GGUF Q4 reemplaza PaddleOCR + parte del LLM en una sola pasada
- 6 GB modelo (Q4_K_M), 95.7 DocVQA, español nativo
- Maneja imagen + texto + reasoning + structured output simultáneamente
- Cuesta más RAM pero simplifica pipeline

### 2. LLM: BitNet 2B + LoRA o Qwen3 4B + LoRA

**Estado actual**: DeepSeek/Haiku via API, 50s avg latency
**Target**: modelo local sub-segundo prefill + 5-15 tok/s gen
**Dataset YA generado**: `data/iuris_lora_dataset.jsonl` (2,585 ejemplos, 2.6 MB)

**Distribución del dataset:**

| Campo | Ejemplos LoRA |
|-------|----------------|
| accionante | 294 |
| juzgado | 285 |
| ciudad | 286 |
| impugnacion | 282 |
| fecha_fallo_1st | 255 |
| sentido_fallo_1st | 238 |
| derecho_vulnerado | 213 |
| categoria_tematica | 154 |
| quien_impugno | 89 |
| juzgado_2nd | 85 |
| sentido_fallo_2nd | 59 |
| decision_incidente | 20 |
| responsable_desacato | 16 |
| forest_impugnacion | 15 |

Los 3 últimos campos tienen pocos ejemplos — habrá que data-augment o priorizar regex sobre LLM para ellos.

**Opciones training**:

| Stack | Modelo base | RAM inferencia | Tooling | Costo entrenamiento |
|-------|-------------|----------------|---------|---------------------|
| **A. BitNet 2B + Tether QVAC** | microsoft/BitNet-b1.58-2B-4T | 0.4 GB | qvac-fabric | $0 (smartphone) o $1 GPU spot |
| **B. Qwen3 4B Q4 + Unsloth** | Qwen/Qwen3-4B | 3.2 GB | unsloth + LoRA | $3-5 GPU spot 1-2h |
| **C. Falcon-Edge 3B + qvac-fabric** | tiiuae/Falcon-Edge-3B | 2 GB | qvac-fabric | $2-3 GPU spot |

Recomendación: **A primero (BitNet)** — más eficiente, framework Tether ya maduro. **B fallback** si BitNet calidad no llega después de LoRA.

### 3. Embeddings (vector search)

**Estado actual**: probablemente sentence-transformers MiniLM (CPU, 80MB FP32)
**Target**: MiniLM int8 (40MB) o BGE-small int8 (130MB) → 2× faster
**Cómo**: convertir a ONNX + `optimum.onnxruntime` con quantization int8 dinámica

### 4. Smart Router → Local Router

**Estado actual**: `backend/agent/smart_router.py` rotea entre DeepSeek/Anthropic
**Target**: rotear a local LLM via llama-cli HTTP server o llama-cpp-python en proceso
**Implementación**:
- Levantar `llama-server` en port 8765 al boot del backend
- Modificar `smart_router.py` para hacer requests HTTP a localhost
- Settings flag: `LLM_LOCAL_URL: str = "http://localhost:8765"`
- Mantener fallback API solo para overflow o emergencia

---

## Hardware target FULL LOCAL

Con todas estas optimizaciones, el hardware mínimo viable es **drásticamente menor**:

| SKU | Hardware | RAM | Modelo LLM target | OCR | Pipeline tot/caso |
|-----|----------|-----|--------------------|------|--------------------|
| **IURIS Lite** | ThinkCentre M720q refurb | 16 GB | BitNet 2B + LoRA (0.4GB) | PP-OCRv5 mobile INT8 | est. 8-15 seg |
| **IURIS Pro** | Jetson Orin Nano Super 8GB | 8 GB | BitNet 2B + LoRA / Qwen3 4B Q4 | PP-OCRv5 + TensorRT | est. 4-10 seg |
| **IURIS Pro NX** | Jetson Orin NX 16GB | 16 GB | Qwen3 30B-A3B Q4 + LoRA | PP-OCRv5 + TensorRT | est. 6-15 seg |
| **IURIS Edge** | RK3588 mini PC | 16 GB | BitNet 2B vía RKLLM | PP-OCRv5 INT8 | est. 12-25 seg |
| **IURIS Mobile** | Smartphone Snapdragon 8 Gen 2 | 8-12 GB | BitNet via QVAC Fabric | Qwen2-VL en GGUF | est. 15-30 seg |

Nota: PaddleOCR-VL fallback puede ser **eliminado del producto final** o reemplazado por Qwen2-VL-OCR-2B que sí corre CPU.

---

## Plan de migración (3 fases, 6 semanas)

### Fase 1 — LLM local (1-2 semanas)
1. ✅ Compilar bitnet.cpp (hecho)
2. ✅ Generar dataset LoRA (hecho, 2,585 ejemplos)
3. **Entrenar LoRA** sobre BitNet 2B usando dataset → adaptador en HuggingFace privado
4. **Validar calidad**: correr 50 casos con BitNet+LoRA vs DeepSeek baseline; meta ≥85% paridad
5. **Reescribir smart_router** para hablar con `llama-server` local
6. **Bench end-to-end** sin API: tiempo/caso, RAM peak

### Fase 2 — OCR cuantizado (1 semana)
1. **Descargar PP-OCRv5 mobile INT8** desde PaddleX
2. **Convertir a ONNX** con `paddle2onnx`
3. **Integrar** en `document_normalizer.py` con feature flag `NORMALIZER_OCR_INT8`
4. **Bench**: comparar accuracy + speed vs PaddleOCR clásico FP32

### Fase 3 — Hardware piloto (2 semanas)
1. **Comprar 1 unidad** del SKU ganador (decisión post Fase 1+2)
2. **Build IURIS appliance**: instalar OS endurecido + tutelas-app + LoRA + OCR cuantizado
3. **Demo a personería piloto** en Floridablanca o Bucaramanga

---

## Métricas objetivo end-to-end

| Métrica | Workstation actual (con API) | IURIS Pro target | Mejora |
|---------|-------------------------------|---------------------|--------|
| Tiempo por caso (2-5 docs) | 60-120 seg | **8-15 seg** | 5-10× |
| Datos enviados a US | 100% texto OCR | **0%** | ∞ |
| Costo operativo / 1000 casos | $2.70 | **$0** | -100% |
| Habeas Data exposure | Alto (texto sensible va a DeepSeek US) | **0** | ✓ compliance |
| Hardware costo | Workstation $1500 | **Appliance $250-700** | 2-6× |

---

## Documentos relacionados

- [HARDWARE_FULL_COMPARISON.md](HARDWARE_FULL_COMPARISON.md) — 10 plataformas evaluadas + KV-cache tricks
- [HARDWARE_ANALYSIS.md](HARDWARE_ANALYSIS.md) — comparativa inicial M4 vs Jetson vs AMD
- [HARDWARE_SIMULATION.md](HARDWARE_SIMULATION.md) — proyecciones perf por caso
- [IP_STRATEGY.md](IP_STRATEGY.md) — marca SIC + modelo utilidad + DNDA
- [legal/TRADEMARK_SIC_DRAFT.md](legal/TRADEMARK_SIC_DRAFT.md) — borrador marca IURIS
- [legal/UTILITY_MODEL_DRAFT.md](legal/UTILITY_MODEL_DRAFT.md) — borrador modelo utilidad
- [legal/DNDA_COPYRIGHT_DRAFT.md](legal/DNDA_COPYRIGHT_DRAFT.md) — borrador derecho autor

---

## Estado al cierre 2026-05-03

| Componente | Status |
|------------|--------|
| F1.B.1 forest_impugnacion integrado | ✓ código, batch pendiente |
| B.2 responsable_desacato | ✓ patrones nuevos, +9 capturas en muestra |
| B.3 decision_incidente | ✓ patrones nuevos, +8 capturas |
| F2 confidence scoring (35 campos) | ✓ persistido sobre 295 casos |
| BitNet b1.58 2B4T compilado | ✓ `~/BitNet/build/bin/llama-cli` |
| BitNet inference test ES jurídico | ⚠️ 2/5 strict, 4/5 semántico (sin LoRA) |
| Dataset LoRA generado | ✓ 2,585 ejemplos (2326 train + 259 val) |
| Audit GPU/API | ✓ ya 90% local, solo APIs faltan |
| Plan OCR cuantización | ✓ PP-OCRv5 mobile INT8 + ONNX vía OpenVINO |

---

## Próxima sesión — orden propuesto

1. **Train LoRA sobre BitNet 2B** usando `iuris_lora_dataset.jsonl` (alquilar GPU spot $1-3, 1-2h)
2. **Test post-LoRA**: re-correr los 5 prompts jurídicos, esperar ≥4/5 strict
3. **Reescribir smart_router** para usar local LLM
4. **Bench end-to-end**: 50 casos sin API
5. **Decisión hardware con datos reales**: ¿Jetson Nano 8GB suficiente? ¿NX 16GB?

---

## Fuentes investigación esta sesión
- [TildAlice — PaddleOCR INT8 init time -73%](https://tildalice.io/paddleocr-vs-easyocr-benchmark/)
- [PaddleOCR 3.0 Technical Report (arxiv 2507.05595)](https://arxiv.org/html/2507.05595v1)
- [PP-OCRv5 mobile + ONNX Runtime](https://paddlepaddle.github.io/PaddleX/3.3/en/pipeline_usage/tutorials/ocr_pipelines/OCR.html)
- [Qwen2.5-VL Blog](https://qwen.ai/blog?id=qwen2.5-vl)
- [Qwen2-VL-OCR-2B GGUF](https://huggingface.co/mradermacher/Qwen2-VL-OCR-2B-Instruct-i1-GGUF)
- [Tether QVAC Fabric BitNet LoRA](https://github.com/tetherto/qvac-rnd-fabric-llm-bitnet)
- [Tether announcement March 2026](https://tether.io/news/tethers-qvac-launches-worlds-first-cross-platform-bitnet-lora-framework-to-enable-billion-parameter-ai-training-and-inference-on-consumer-gpus-and-smartphones/)
- [Falcon-Edge BitNet TII](https://falcon-lm.github.io/blog/falcon-edge/)
- [E-ARMOR Multilingual OCR Edge Benchmark (arxiv 2509.03615)](https://arxiv.org/html/2509.03615v1)
- [olmOCR-2-7B](https://blog.roboflow.com/local-vision-language-models/)
- [Best OCR Models 2026 — Codesota](https://www.codesota.com/ocr)
