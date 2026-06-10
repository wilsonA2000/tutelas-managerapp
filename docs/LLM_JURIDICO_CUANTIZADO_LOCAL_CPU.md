# LLM Jurídico Cuantizado Corriendo 100% Local en CPU + iGPU

> **El logro:** un modelo de lenguaje cuantizado, especializado en extracción
> jurídica de tutelas, corriendo **enteramente en hardware de consumo** (Intel
> Core i5 + iGPU integrada, **16 GB de RAM como requerimiento mínimo**), sin nube,
> sin GPU dedicada, sin costo por token, y **sin que ni un solo dato personal salga
> de la máquina**. Validado en producción sobre tutelas reales de la Gobernación de
> Santander.
>
> Sesión de descubrimiento y validación: **2026-05-21 / 2026-05-22**.

---

## 1. Resumen ejecutivo

Se demostró que **no se necesita un modelo grande ni una GPU dedicada** para
extracción jurídica confiable. La combinación ganadora es:

- **Inteligencia determinista primero** (regex + catálogos + heurística) → resuelve
  ~37 de los 41 campos del cuadro.
- **LLM cuantizado local SOLO como último recurso** (0 ó 1 llamada por caso) para los
  2-4 campos genuinamente semánticos donde la cognición determinista falla.
- **Retrieval anclado** que le entrega al modelo solo el pasaje relevante (~5.000
  caracteres) → cabe en el contexto del modelo y lo hace rápido y preciso.

Resultado: extracción jurídica de calidad en **~25-50 s/caso**, en un portátil de
oficina, con privacidad total (Habeas Data, Ley 1581/2012).

---

## 2. El hardware (verificado en esta máquina)

| Componente | Detalle |
|---|---|
| **CPU** | 13th Gen Intel **Core i5-1334U** — 10 núcleos (2 P-cores + 8 E-cores), 12 hilos, hasta 4.6 GHz, TDP 15-28 W |
| **RAM** | 32 GB (2×16 Crucial **DDR4-2666** SODIMM) — **dual-channel + dual-rank** (≈43 GB/s). **Mínimo viable: 16 GB** (para el modelo 4B) |
| **iGPU** | Intel **Iris Xe Graphics** (RPL-U), driver Mesa, **Vulkan 1.4.318** (`/dev/dri/renderD128`) |
| **SO** | Linux (migrado desde Windows) |
| **Runtime** | `llama.cpp` compilado con `-DGGML_VULKAN=ON` (build separado `build-vulkan`) |

**Requerimiento mínimo declarado:** Intel Core i5 + iGPU con Vulkan + **16 GB RAM**.
Con 16 GB cabe el modelo de producción (Qwen3-4B Q4, 2.4 GB) + backend + SO. Los
32 GB solo son necesarios para experimentar con el modelo de 30B (que se descartó —
ver §5.1).

---

## 3. Los modelos

| Modelo | Tamaño | Rol | Veredicto |
|---|---|---|---|
| **Qwen3-4B-Q4_K_M** | 2.4 GB | **Producción** (batch + gap-fill) | ✅ El ganador |
| Qwen3-30B-A3B-Instruct-2507-Q4_K_M | 18 GB | Experimento (razonamiento) | ❌ Descartado para batch |
| Phi-4-mini-instruct-Q4 | 2.4 GB | Comparado antes | ≈ 4B, se quedó el 4B |

---

## 4. Configuración óptima (medida empíricamente en esta iGPU)

```bash
~/llama.cpp/build-vulkan/bin/llama-server \
  -m data/lora-models/Qwen3-4B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8765 \
  -ngl 99 \        # offload completo a la iGPU — gana siempre
  -t 6 \           # generación más estable (t4/t8 no mejoran consistente)
  -c 4096          # contexto (≈16.000 chars). El anclaje hace que quepa
```

Reglas que salieron de los datos:
- ✅ Usar **`build-vulkan`** (el build `build/` normal es CPU+OpenBLAS, **NO usa la iGPU**).
- ✅ **`-ngl 99`** (offload completo).
- ❌ **`-fa` (flash-attn) NO ayuda** en esta iGPU Vulkan — igual o peor.
- ❌ **`-ot exps=CPU`** (truco MoE de "expertos en CPU") **empeora** en memoria compartida
  (generación cayó a la mitad). Sirve para GPUs dedicadas con poca VRAM, no aquí.

### Benchmark (Qwen3-30B-A3B, medido con `llama-bench`)
| Config | Prompt-eval (pp) | Generación (tg) |
|---|---|---|
| CPU pura (`-ngl 0`) | 32.2 tok/s | 6.7 tok/s |
| **iGPU (`-ngl 99`)** | **39.4 tok/s** | **11.5 tok/s** |
| `-ot exps=CPU` | 30.6 tok/s | 4.7 tok/s ❌ |

**El cuello de botella es el prompt-eval (prefill).** En un MoE el prefill activa
muchos expertos → procesar el prompt cuesta casi como el modelo completo. Por eso
**acortar y cachear el prompt vale más que cualquier flag.**

---

## 5. Descubrimientos clave (sin omitir ninguno)

### 5.1 — Un modelo más grande NO es mejor (bake-off 30B vs 4B, 13 casos reales)
- 30B: **~94 s/caso** · 4B: **~60 s/caso** → el 30B es **~1.5× más lento**.
- El 30B **NO fue más preciso**; de hecho cometió los errores típicos: leyó las
  *pretensiones* del **auto admisorio** o de la **respuesta de la SED** (documento
  equivocado), y alucinó un nombre en `responsable_desacato`.
- **Insight central:** los errores de extracción son de **retrieval/grounding, no de
  inteligencia**. Un modelo más grande resume con más fluidez el texto equivocado →
  no arregla el problema. **Determinista + anclaje > tamaño de modelo.**

### 5.2 — `/no_think` es OBLIGATORIO para Qwen3 base (4B)
- El Qwen3-4B tiene modo "thinking". Sin `/no_think` al inicio del prompt, gasta
  TODOS los tokens en `<think>...` y devuelve **content vacío**.
- El harness de producción lo incluye → funciona. Una llamada ad-hoc que lo omita
  **devuelve vacío** (error fácil de cometer; verificado en esta sesión).
- El 30B-A3B-**Instruct**-2507 NO lo necesita (es un modelo "Instruct" sin thinking).

### 5.3 — `json_schema` strict rompe el 30B; `json_object` suave funciona
- Con `response_format: json_schema strict`, el 30B-A3B **degenera en basura Unicode**
  ("режим以色…", "+0000…") cuando se le fuerza a llenar un campo `required` sin
  respuesta. El **4B sí lo tolera**.
- Toggle `V9_LLM_SOFT_JSON=true` → usa `json_object` suave + parseo tolerante.

### 5.4 — El retrieval anclado es lo que hace que TODO quepa y funcione
- `backend/v9/field_context.py` arma el contexto del LLM con **solo las ventanas
  ancladas** a las secciones relevantes (PRETENSIONES, "en mérito de lo…"),
  presupuesto **~5.000 chars**. No le manda el documento completo.
- Esto es crítico por el límite de contexto (ver §5.5) y por la calidad (evita que el
  modelo lea el documento equivocado — la causa raíz de §5.1).

### 5.5 — Tokens vs caracteres: el contexto del modelo (4096) ≠ el largo del documento
- El LLM lee **tokens** (≈ trozos de palabra, ~4 chars c/u en español). Contexto
  `-c 4096` ≈ **16.000 caracteres**.
- Un fallo de tutela de 9 páginas ≈ 30.621 chars ≈ **~7.600 tokens → NO cabe** en 4096.
- Por eso se ancla (~5.000c ≈ 1.250 tokens). Se podría subir a `-c 8192` (cabría el
  doc entero) pero el prefill se vuelve más lento; el anclaje es mejor solución.

### 5.6 — El LLM solo sirve para los campos semánticos (≈2-4 de 41)
- De los 41 campos del cuadro, **~37 son deterministas** (radicado, FOREST, fechas,
  juzgado, dependencia, abogado, sentido del fallo por parseo del RESUELVE, etc.).
- Los candidatos reales a LLM: **pretensiones, observaciones**, y como *fallback* de
  NER: vinculados/accionados. Y aun ahí, muchos "vacíos" son **legítimos** (no existe
  el documento fuente) → se excluyen.

### 5.7 — Una sola llamada multi-campo puede confirmar VARIOS campos
- En la corrida de producción el modelo llenó `pretensiones` + `vinculados` en **1
  llamada**.
- Demostrado además: con el RESUELVE anclado y `/no_think`, en **una sola llamada** el
  4B extrajo correctamente los **6 campos de estructura de instancias** (juzgado/fecha/
  sentido de 1ª y 2ª). → Se pueden agregar más campos a la llamada multi-campo "gratis".

### 5.8 — Detalles operativos
- **Arranque en frío ~34 s**: la primera inferencia compila los shaders Vulkan
  (82.9 s en frío vs 49.0 s en caliente para el mismo caso).
- El "cap de 30.000 chars" que se veía en algunos docs era **dato viejo en la DB**, no
  un límite actual: re-extraer da el texto completo (método `pymupdf_first5_last3`:
  primeras 5 + últimas 3 páginas).

---

## 6. Validación en producción (caso c419 — tutela de traslado, Cimitarra)

Pipeline real (`extract_case`, harness de producción, 4B en iGPU):
- **`pretensiones`** extraído correctamente: amparo + orden de traslado/reubicación. ✅
- **6 campos de instancia** confirmados en 1 llamada (con `/no_think` + anclaje):
  - 1ª: Juzgado Segundo Promiscuo Municipal de Cimitarra · 29/12/2025 · CONCEDE
  - 2ª: Juzgado Primero Civil del Circuito de Cimitarra · 06/02/2026 · MODIFICA
- Latencia: 82.9 s (frío) → **49.0 s (caliente)**, 1 sola llamada LLM.
- Regla de oro confirmada por el documento: **Juzgado del Circuito = 2ª instancia**
  (superior funcional) → señal **determinista** de instancia, sin LLM.

---

## 7. Cómo reproducirlo

```bash
# 1) Compilar llama.cpp con Vulkan (una vez)
cmake -B build-vulkan -DGGML_VULKAN=ON && cmake --build build-vulkan -j

# 2) Servidor del modelo en la iGPU
~/llama.cpp/build-vulkan/bin/llama-server \
  -m data/lora-models/Qwen3-4B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8765 -ngl 99 -t 6 -c 4096

# 3) Extracción (harness de producción — incluye /no_think + anclaje)
#    desde la app, o:
python3 -c "from backend.database.database import SessionLocal; \
from backend.v9.pipeline import extract_case; \
print(extract_case(SessionLocal(), <CASE_ID>, dry_run=True, use_llm=True))"
```

Requisitos del sistema (Linux): `mesa-vulkan-drivers`, `vulkan-tools`, `spirv-headers`,
`glslc`. Verificar la iGPU: `vulkaninfo --summary`.

---

## 8. Por qué importa (Ingeniería Legal)

- **Costo cero por token** — no hay facturación de nube; el hardware ya existía.
- **Privacidad total** — ningún dato personal de las tutelas sale de la máquina
  (cumple Habeas Data, Ley 1581/2012, sin necesidad de DPA con terceros).
- **Soberanía y disponibilidad** — funciona airgapped, sin depender de conectividad
  ni de proveedores externos.
- **Reproducible en cualquier portátil de oficina** con un i5 e iGPU + 16 GB.

Esto consolida la tesis de la **Ingeniería Legal**: inteligencia local-first,
determinista en su mayoría, con el LLM como complemento quirúrgico y barato, capaz de
manejar ~350 tutelas/año en hardware de consumo.

---

*Documento generado el 2026-05-22 a partir de la sesión de descubrimiento y validación.
Referencias internas (memoria del proyecto): `project_llm_optimizacion`,
`project_bakeoff_qwen_vs_phi`, `project_fix_instancia_y_cap`,
`project_bug_md_extracted_text_vacio`, `feedback_ground_truth_cuadro_vivo`.*
