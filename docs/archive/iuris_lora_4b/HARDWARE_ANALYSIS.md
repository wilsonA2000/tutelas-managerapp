# IURIS — Análisis de Hardware Appliance (2026-05-02)

> Producto: **IURIS** — appliance jurídico on-prem para procesamiento neurosimbólico de tutelas.
> Autor: Wilson Arguello, Ingeniero Legal.
> Pregunta original: ¿cómo lograr corrida fluida tipo M4 Mac mini, en formato económico, portable y competitivo?

---

## TL;DR ejecutivo

1. **Ganador objetivo**: NVIDIA Jetson Orin Nano Super 8GB ($249 USD) + carcasa CNC custom.
2. **Plan B robusto**: Beelink SER9 con AMD Ryzen AI 9 HX 370 ($999 USD, 32GB RAM).
3. **Plan C disruptivo (recomendado evaluar)**: arquitectura BitNet b1.58 sobre mini PC ARM o x86 barato — **rompe la dependencia de GPU/NPU**.
4. **Hallazgo crítico**: la era de "necesitas GPU para LLM" terminó. BitNet 2B corre en CPU a velocidad de lectura humana. Cambia toda la economía del appliance.

---

## 1. Tabla comparativa principal

| Métrica                   | M4 Mac mini (24GB)        | Jetson Orin Nano Super 8GB | AMD Ryzen AI 9 HX 370 (32GB) | Mini PC + BitNet (CPU only) |
|---------------------------|----------------------------|------------------------------|--------------------------------|-------------------------------|
| **Precio base USD**       | ~$700 (24GB) / ~$599 (16GB)| **$249**                     | $999 (Beelink SER9)            | $200-400                      |
| **Precio Colombia (CIF)** | ~$3.5M COP                 | ~$1.7-2.2M COP (importación) | ~$4.5M COP                     | ~$1M COP                      |
| **Compute IA**            | 38 TOPS Neural Engine      | **67 TOPS (post-Super)**     | 50 TOPS NPU + 80 TOPS hybrid   | CPU only (BitNet redefine)    |
| **RAM utilizable LLM**    | ~20 GB                     | **~6.5 GB** (cuello)         | ~28 GB                         | depende mini PC (8-32GB)      |
| **Bandwidth memoria**     | 120 GB/s                   | 102 GB/s                     | ~75 GB/s                       | ~40-60 GB/s                   |
| **Llama 3 7B Q4 gen**     | ~28-30 tok/s               | ~14-15 tok/s                 | ~17-20 tok/s (hybrid)          | ~5-7 tok/s                    |
| **Modelos hasta**         | 13B-14B cómodo             | 7B-8B Q4 al límite           | 14B sin sudar                  | 2B BitNet (perf de 7B)        |
| **Power draw idle/load**  | 5W / 30W                   | 7W / 25W                     | 28W / 54W                      | 5-15W                         |
| **Tamaño**                | 12.7×12.7×5cm              | 10.0×7.9×6.5cm (más chico)   | 13.6×13.6×5cm                  | variable                      |
| **CUDA stack**            | NO (MLX/Metal)             | **SÍ nativo**                | NO (ROCm)                      | irrelevante (CPU)             |
| **Refactor pipeline**     | 2-3 sem (port a MLX)       | **0 — drop-in**              | 1-2 sem (port a ROCm)          | 1 sem (cambio modelo, no API) |
| **NVIDIA Inception**      | ❌                         | ✅                           | ❌                             | ❌                            |
| **Fanless posible**       | ✅ pasivo                  | ✅ con disipador              | ❌ (requiere ventilador)       | depende                       |
| **Whitelabel/branding**   | ❌ (Apple prohíbe)         | ✅                           | ✅                             | ✅                            |
| **Disponibilidad CO**     | Alta (Apple Store)         | Media (Yaxa, ML)             | Media (importación)            | Alta (cualquier mini PC)      |

---

## 2. El hallazgo crítico — BitNet b1.58 redefine las reglas

### Qué es

Microsoft liberó BitNet en abril 2025: arquitectura de LLM cuyos pesos toman solo tres valores (-1, 0, +1), lo que requiere **1.58 bits por peso** en lugar de 16. Esto convierte las multiplicaciones matriciales en **sumas y restas enteras**, operaciones para las que las CPUs son excelentes.

### Cifras que importan para IURIS

- **BitNet b1.58 2B4T**: 2B parámetros, 0.4 GB de memoria, performance comparable a Qwen 2.5 7B en math, código y razonamiento.
- **Energía**: 0.028 J/inference vs 0.347 J de Qwen 2.5 → **12× más eficiente**.
- **Velocidad**: speedup 1.37–5.07× sobre ARM, 2.37–6.17× sobre x86.
- **bitnet.cpp** (framework propio Microsoft) corre incluso un modelo 100B en una sola CPU a velocidad de lectura humana (5-7 tok/s).
- Update enero 2026: kernels paralelos + tiling + embedding quantization → otro 1.15-2.1× boost.

### Implicación estratégica para IURIS

Si IURIS adopta arquitectura BitNet (o modelos post-cuantizados a 1.58-bit como Falcon3 / Llama 3 8B BitNet), entonces:

1. **No necesitas Jetson, ni Mac mini, ni Ryzen AI**. Un mini PC ARM de $200 o un ThinkCentre Tiny refurbished de $150 ejecuta razonamiento jurídico fluido.
2. **Margen disparado**: BOM puede caer a $250-400 USD. PVP $1,500 deja 70-80% margen bruto.
3. **Diferenciador comercial**: "IURIS corre LLM jurídico de calidad sin GPU. Consume 5W. Cabe en bolsillo de gabardina."
4. **Riesgo**: Microsoft mismo advierte no usar BitNet en producción comercial sin validación adicional. Calidad jurídica del razonamiento debe medirse contra modelos full-precision. Tu pipeline ya es 80% determinístico (regex + forensic + Bayesian) — la IA solo se usa para razonamiento semántico, donde 1-2 tokens menos por segundo es aceptable.

### Sobre el comentario "Llama en Arduino"

No es exageración, está documentado:

- **Arduino UNO Q (Linux ARM)** corre SmolLM2-135M vía llama.cpp y yzma.
- **ESP32-S3** (microcontrolador 8 USD): proyecto BitForge alcanza **15 tok/s** con Q4_K_M y memory-mapped flash.
- **Coral Dev Board Micro** (64MB RAM, Cortex-M7): 2.5 tok/s en TinyLlama.
- **Arduino Nano 33 BLE** (512KB RAM): 3 tok/s sobre modelo bonsai.

Para IURIS no tiene sentido un microcontrolador (necesitamos OCR, BD SQLite, FastAPI, frontend), pero confirma que la frontera de "donde corre IA" se desplazó. Cualquier mini PC moderno es overkill.

---

## 3. Análisis camino por camino

### Camino A — Jetson Orin Nano Super 8GB ($249)

**Pros:**
- CUDA nativo: tu pipeline actual (PaddleOCR, transformers HF, llama.cpp CUDA) corre sin tocarse.
- NVIDIA Inception ya aplicado → badge oficial de partner para marketing.
- Power 7-25W, tamaño 100×79mm, fanless con disipador pasivo.
- Comunidad robusta: NVIDIA Jetson AI Lab publica benchmarks oficiales y modelos optimizados.

**Contras (verificados con benchmarks reales):**
- 8GB RAM = techo real ~6.5GB para LLM. Llama 3.1 8B Q4 cabe pero al límite.
- Solo ~14-15 tok/s en 7B Q4. La mitad del M4 Mac mini.
- Single-stream: NO maneja peticiones LLM en paralelo. Si IURIS sirve a 2 usuarios concurrentes ya hace cola.
- Eric X. Liu (feb 2026) demuestra que el cuello no es compute sino memory bandwidth → los 67 TOPS están infrautilizados en inferencia LLM.
- En Colombia: $1.7-2.2M COP nacionalizado vs $249 oficial USD. Importación directa Amazon recomendada.

**Veredicto:** Sigue siendo mi #1 por **CUDA + Inception**, pero la limitación 8GB es real. Para 1 usuario por appliance está perfecto. Para multi-tenant no.

### Camino B — Beelink SER9 / Minisforum AI370 ($999-1399)

**Pros:**
- 32GB LPDDR5X-7500 → corre 13B-14B sin sudar.
- NPU XDNA2 50 TOPS + iGPU Radeon 890M 80 TOPS hybrid. AMD Lemonade Server ya en preview.
- Linux maduro, Windows opcional, casing ya aluminio premium.
- Rinde como mini PC gaming 1080p como bonus (utilidad doble).

**Contras:**
- Pierdes badge NVIDIA Inception y co-marketing.
- Migrar pipeline CUDA → ROCm/Vulkan/DirectML implica 1-2 semanas de refactor.
- TDP 28-54W, requiere ventilador, no es silencioso bajo carga.
- DPC latency reportado en el Minisforum AI370 puede ser problema para apps reactivas.

**Veredicto:** Plan B sólido **si la limitación 8GB del Jetson te quema en producción**. PVP $2,000 deja margen razonable.

### Camino C — Mac mini M4 (descartado para appliance, recomendable para dev)

- Apple **prohíbe explícitamente** revender Mac minis con branding propio o como "appliance" embebido. Sus términos comerciales.
- Únicamente útil como **estación de desarrollo personal de Wilson** (compra una para ti, no para revender).

### Camino D — BitNet sobre mini PC barato ($200-500)

**Hardware candidato:**
- **Lenovo ThinkCentre M720q tiny** (i7-8700T, 16-32GB upgrade fácil): $150-250 usado en MercadoLibre Bucaramanga.
- **Beelink Mini S12 Pro** (N100, 16GB, 500GB): $179 nuevo aliexpress.
- **Orange Pi 5 Plus** (RK3588, 16-32GB): $200-280 nuevo.

**Stack:**
- bitnet.cpp + modelo BitNet 2B4T o post-cuantizado Llama 3 8B 1.58-bit.
- Pipeline tutelas-app actual (FastAPI + PaddleOCR + cognición v6) corre sin GPU.
- LLM solo se invoca para los huecos cognitivos (forest_impugnacion, decisión_incidente, etc.).

**Pros:**
- Margen extremo: BOM $200-400, PVP $1,500-2,000 → 75% margen.
- Power draw 5-15W → fanless real, silencioso.
- Branding total (logo, color, packaging) sin restricciones.
- Refurb path sostenible (e-waste reuse → narrativa ESG/sostenibilidad para gobierno).

**Contras:**
- BitNet aún no validado comercialmente. Microsoft lo dice. **Riesgo técnico real.**
- Calidad del razonamiento en español jurídico colombiano debe medirse explícitamente con tu corpus dorado.
- Sin badge Inception ni CUDA.

**Veredicto:** Camino más rentable y más arriesgado. **Recomendación: piloto interno antes de comprometer.**

---

## 4. Recomendación final escalonada

### Fase 0 (mayo-junio 2026) — VALIDACIÓN
1. Compra **un Jetson Orin Nano Super** vía Amazon US (~$320 con envío y nacionalización chunk pequeño) → **es tu rig de validación interna y demo a clientes**.
2. En paralelo, instala **bitnet.cpp** sobre tu workstation actual y mide:
   - Cobertura de los 5 campos huérfanos (forest_impugnacion, etc.) con BitNet 2B vs DeepSeek.
   - Calidad del razonamiento jurídico en 50 casos del corpus dorado.
   - Latencia end-to-end por caso.
3. Decisión gate: si BitNet alcanza ≥85% de la calidad de DeepSeek/Haiku → adoptar Camino D.

### Fase 1 (julio-agosto 2026) — PILOTO COMERCIAL
4. **Si Camino D gana** → BOM Lenovo ThinkCentre Tiny refurb $250 + carcasa custom + branding IURIS. Vendes a 3-5 personerías de Santander a $1,500. Margen ~$1,000/unidad.
5. **Si Camino A gana** → Jetson Orin Nano Super + carcasa CNC + accessoria. PVP $1,800. Margen ~$1,200/unidad.

### Fase 2 (sep-dic 2026) — ESCALA
6. Servidor central de licencias en Fly.io BOG (cuenta ya tienes).
7. Modelo subscripción anual: hardware $1,500 + soporte SaaS $50/mes/usuario.
8. Si tracción ≥10 unidades vendidas → encargo 50 unidades en BOM optimizado.

---

## 5. Patentes y patentes ajenas a respetar

**Tecnología accesible y libre que IURIS aprovecha (ya lo hace o puede):**
- **PaddleOCR** (Apache 2.0) — sin patentes problemáticas.
- **bitnet.cpp** (MIT) — fork-friendly, comercializable.
- **llama.cpp** (MIT) — idem.
- **GGUF format** (público, sin patente) — Microsoft no patentó BitNet (deliberado, abierto).
- **PostgreSQL/SQLite** (libre) — ya en uso.
- **FastAPI/React** (MIT) — ya en uso.

**Patentes a evitar tocar (defensiva):**
- Patentes Apple sobre Neural Engine, MLX → solo importan si elijes Mac mini (descartado).
- Patentes NVIDIA sobre TensorRT-LLM optimizations → IURIS las usa **como licenciatario implícito** comprando el SDK (legal y limpio).
- Patentes IBM/Microsoft sobre OCR → PaddleOCR esquiva todas las relevantes.

**Tecnología de terceros que se puede comprar barato y remasterizar:**
- Lenovo ThinkCentre Tiny refurb (mercado libre BMA $150-250) → reflasheo BIOS, OS custom, branding sticker.
- Mini ITX cases industriales chinos ($30-80 aliexpress) → repintado con logo IURIS.
- Fuentes pico-PSU 12V ($25 aliexpress) → silenciosas, fanless.
- SSDs M.2 NVMe 256GB ($25-30) → performance suficiente.

**Crear nueva tecnología (no patentable directamente, pero defendible):**
- **Arquitectura cognitiva 7-capas con Bayesian doc-assignment** → posible modelo de utilidad (ver doc IP_STRATEGY.md).
- **Sello rotado como señal probabilística** → novedad técnica defendible.
- **Carcasa con airflow optimizado fanless para SBC ARM** → modelo de utilidad colombiano clarísimo si la diseñas tú.

---

## 6. Decisiones inmediatas que necesito de Wilson

1. **¿Compramos Jetson para validación esta semana?** (~$320 vía Amazon US importado a Colombia, llega en 7-14 días).
2. **¿Probamos BitNet 2B4T sobre tu workstation actual?** (yo arranco la integración mientras llega el Jetson, sin costo).
3. **¿Cerramos a Jetson como referencia y BitNet como path de costo, decisión final post-validación?**

---

## Fuentes
- [NVIDIA Jetson Orin Nano Super Developer Kit Review](https://thinkrobotics.com/blogs/product-reviews-buying-guides/nvidia-jetson-orin-nano-super-developer-kit-review-is-it-the-best-edge-ai-board-in-2025)
- [Why Your Jetson Orin Nano's 40 TOPS Goes Unused — Eric X. Liu](https://ericxliu.me/posts/benchmarking-llms-on-jetson-orin-nano/)
- [Jetson AI Lab Models Benchmark](https://www.jetson-ai-lab.com/models/)
- [MacMini im KI-Test: Apple M4 vs NVIDIA Jetson Orin Nano Super](https://marketmix.com/de/apple-macmini-m4-vs-nvidia-jetson-orin-nano/)
- [Best Hardware for OpenClaw 2026 — Mac Mini vs Jetson vs Pi (DEV)](https://dev.to/yankoaleksandrov/best-hardware-for-openclaw-in-2026-mac-mini-vs-jetson-vs-raspberry-pi-2f2a)
- [Beelink SER9 AMD Ryzen AI 9 HX 370 Review (ServeTheHome)](https://www.servethehome.com/beelink-ser9-amd-ryzen-ai-9-hx-370-mini-pc-review/)
- [AMD Ryzen AI 300 Hybrid NPU+iGPU LLM article](https://www.hardware-corner.net/amd-targets-faster-local-llms/)
- [Microsoft BitNet Official GitHub](https://github.com/microsoft/BitNet)
- [BitNet b1.58 2B4T HuggingFace](https://huggingface.co/microsoft/bitnet-b1.58-2B-4T)
- [Microsoft BitNet 1-Bit LLMs CPU (DEV)](https://dev.to/bspann/bitnet-microsofts-1-bit-llms-that-run-on-your-cpu-20h8)
- [Llama4Micro Project (GitHub maxbbraun)](https://github.com/maxbbraun/llama4micro)
- [BitForge: Run LLMs on Microcontrollers (DEV)](https://dev.to/aman_sachan_126d19c4a2773/bitforge-run-llms-on-microcontrollers-57ek)
- [Arduino UNO Q LLM Project Hub](https://projecthub.arduino.cc/marc-edgeimpulse/running-local-llms-and-vlms-on-the-arduino-uno-q-with-yzma-74e288)
- [Yaxa Colombia — Jetson Orin Nano Developer Kit](https://colombia.yaxa.co/products/nvidia-jetson-orin-nano-developer-kit)
